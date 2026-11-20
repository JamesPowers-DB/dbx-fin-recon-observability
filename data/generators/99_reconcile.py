# Databricks notebook source
# MAGIC %md
# MAGIC # 99: reconciliation gate (fails the job)
# MAGIC
# MAGIC Proves the generated sources are internally consistent before the pipeline
# MAGIC runs. Planted exceptions are the only allowed breaks.
# MAGIC
# MAGIC | Check | Rule |
# MAGIC |---|---|
# MAGIC | Revenue vs anchors | Salesforce invoices (USD) per quarter x segment within +/-tolerance_pct |
# MAGIC | Cost and opex vs anchors | GL accounted USD per completed quarter (excluding planted and adjustment journals) within +/-tolerance_pct |
# MAGIC | Journal balance | entered debits = credits for every journal except the planted legacy upload |
# MAGIC | Trial balance | cumulative accounted balance per entity = 0, except the entity with the legacy upload |
# MAGIC | Lineage keys | GL reference_1 resolves to Salesforce and AP documents; bank EndToEndIds resolve to GL reference_2 |
# MAGIC | Subledger tie-outs | AR, AP (balances) and payroll (cumulative cost) tie per entity x month-end, except planted entity-periods |
# MAGIC | Planted registry | every module plants at least one exception |

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
dbutils.widgets.text("tolerance_pct", "2.0")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
tol = float(get_widget("tolerance_pct", "2.0")) / 100.0
as_of = load_as_of(catalog, schema, raw_volume)
cutoff = data_cutoff(as_of)
ay, am = active_period(as_of)
ACTIVE = period_key(ay, am)
ORA = volume_dir(catalog, schema, raw_volume, "oracle")
failures, warnings, summary = [], [], []


def check(name, ok, detail):
    summary.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    if not ok:
        failures.append(f"{name}: {detail}")


anchors = read_scratch(catalog, schema, raw_volume, "anchors")
planted = spark.table(f"`{catalog}`.`{schema}`.meta_planted_exceptions").toPandas()
planted_keys = {(r["control_id"], r["record_key"]) for r in planted.to_dict("records")}
planted_ep = {(r["control_id"], r["record_key"]) for r in planted.to_dict("records") if "|" in r["record_key"]}
hdr = pl.scan_csv(f"{ORA}/gl_je_headers_*.csv", infer_schema_length=0).collect().with_columns(
    pl.col("je_header_id").cast(pl.Int64), pl.col("ledger_id").cast(pl.Int64),
    pl.col("default_effective_date").str.to_date())
lines = pl.scan_csv(f"{ORA}/gl_je_lines_*.csv", infer_schema_length=0).collect().with_columns(
    pl.col("je_header_id").cast(pl.Int64), *[pl.col(c).cast(pl.Float64) for c in
                                             ["entered_dr", "entered_cr", "accounted_dr", "accounted_cr"]])
gl = lines.join(hdr.select("je_header_id", "ledger_id", "je_source", "je_category", "name", "default_effective_date"),
                on="je_header_id").with_columns(
    pl.col("code_combination_id").str.slice(0, 4).alias("entity"),
    pl.col("code_combination_id").str.slice(-5).alias("account"),
    pl.col("default_effective_date").dt.strftime("%Y-%m").alias("period"))
print(f"GL journals={hdr.height} lines={gl.height}")

# COMMAND ----------
# MAGIC %md ## Anchors: revenue (all quarters), cost and opex (completed quarters)

# COMMAND ----------
sf = read_scratch(catalog, schema, raw_volume, "sf_invoices").filter(~pl.col("Corvane_Opening_Balance__c"))
sf = sf.with_columns(pl.struct(["Corvane_Entity__c", "blng__InvoiceDate__c", "blng__TotalAmount__c"]).map_elements(
    lambda s: s["blng__TotalAmount__c"] * entity_rate(s["Corvane_Entity__c"], s["blng__InvoiceDate__c"]),
    return_dtype=pl.Float64).alias("usd"),
    pl.col("blng__InvoiceDate__c").dt.year().alias("fy"),
    ((pl.col("blng__InvoiceDate__c").dt.month() - 1) // 3 + 1).alias("fq"))
rev = sf.group_by(["fy", "fq", "Corvane_Segment__c"]).agg(pl.col("usd").sum())
m_rows = anchors.filter((pl.col("period_type") == "M") & (pl.col("metric") == "revenue") & (pl.col("segment_code") != "CONSOL"))
exp_rev = m_rows.group_by(["fiscal_year", "fiscal_quarter", "segment_code"]).agg((pl.col("value_usd_m").sum() * 1e6).alias("exp"))
cmp = exp_rev.join(rev, left_on=["fiscal_year", "fiscal_quarter", "segment_code"], right_on=["fy", "fq", "Corvane_Segment__c"], how="left")
cmp = cmp.filter(pl.col("exp") > 0).with_columns(((pl.col("usd").fill_null(0) - pl.col("exp")) / pl.col("exp")).alias("drift"))
bad = cmp.filter(pl.col("drift").abs() > tol)
check("revenue_vs_anchors", bad.is_empty(), f"{cmp.height} quarter x segment cells, max drift {cmp['drift'].abs().max():.4%}")

planted_je = {int(k) for (c, k) in planted_keys if k.isdigit()}
q_status = anchors.filter((pl.col("period_type") == "M")).group_by(["fiscal_year", "fiscal_quarter"]).agg(
    (pl.col("status") == "CLOSED").all().alias("complete"))
complete_q = {(r["fiscal_year"], r["fiscal_quarter"]) for r in q_status.filter(pl.col("complete")).iter_rows(named=True)}
glq = (gl.filter(~pl.col("je_category").is_in(["Adjustment", "Reclass", "Opening Balances"]) & ~pl.col("je_header_id").is_in(list(planted_je)))
         .with_columns(pl.col("default_effective_date").dt.year().alias("fy"),
                       ((pl.col("default_effective_date").dt.month() - 1) // 3 + 1).alias("fq"),
                       (pl.col("accounted_dr") - pl.col("accounted_cr")).alias("net")))
METRIC_ACCOUNTS = {"cost_of_revenue": ["50000", "51000", "52000"], "rnd": ["60000"], "snm": ["61000"],
                   "gna": ["62000", "64000"], "dna": ["63000"]}
worst = 0.0
for metric, accts in METRIC_ACCOUNTS.items():
    act = glq.filter(pl.col("account").is_in(accts)).group_by(["fy", "fq"]).agg(pl.col("net").sum())
    exp = anchors.filter((pl.col("period_type") == "Q") & (pl.col("segment_code") == "CONSOL") & (pl.col("metric") == metric))
    for r in exp.iter_rows(named=True):
        if (r["fiscal_year"], r["fiscal_quarter"]) not in complete_q:
            continue
        a = act.filter((pl.col("fy") == r["fiscal_year"]) & (pl.col("fq") == r["fiscal_quarter"]))["net"]
        a = float(a[0]) if len(a) else 0.0
        e = r["value_usd_m"] * 1e6
        drift = (a - e) / e if e else 0.0
        worst = max(worst, abs(drift))
        if abs(drift) > tol:
            failures.append(f"{metric} {r['fiscal_year']}Q{r['fiscal_quarter']}: GL {a:,.0f} vs anchor {e:,.0f} ({drift:+.2%})")
summary.append({"check": "cost_opex_vs_anchors", "status": "PASS" if worst <= tol else "FAIL",
                "detail": f"completed quarters {sorted(complete_q)}, worst drift {worst:.4%}"})

# COMMAND ----------
# MAGIC %md ## Journal and trial balance integrity

# COMMAND ----------
jb = gl.group_by(["je_header_id", "name"]).agg((pl.col("entered_dr").sum() - pl.col("entered_cr").sum()).round(2).alias("diff"))
unbal = jb.filter(pl.col("diff").abs() > 0.005)
legacy = unbal.filter(pl.col("name").str.starts_with("LEGACY-UPLOAD"))
check("journals_balance", unbal.height == legacy.height and legacy.height == 1,
      f"{unbal.height} unbalanced journal(s); expected exactly 1 planted legacy upload")
tb = gl.group_by("entity").agg((pl.col("accounted_dr").sum() - pl.col("accounted_cr").sum()).round(2).alias("tb"))
tb_bad = tb.filter((pl.col("tb").abs() > 0.05) & (pl.col("entity") != "IE01"))
check("trial_balance_zero", tb_bad.is_empty(), f"entities off: {tb_bad.to_dicts()}")

# COMMAND ----------
# MAGIC %md ## Lineage keys

# COMMAND ----------
sf_all = read_scratch(catalog, schema, raw_volume, "sf_invoices")
sf_pay = read_scratch(catalog, schema, raw_volume, "sf_payments")
ap = read_scratch(catalog, schema, raw_volume, "ap_invoices")
chk = read_scratch(catalog, schema, raw_volume, "ap_checks")
recv = gl.filter((pl.col("je_source") == "Receivables") & (pl.col("je_line_num") == "1"))
known_sf = set(sf_all["Id"].to_list()) | set(sf_pay["Id"].to_list())
miss_sf = recv.filter(~pl.col("reference_1").is_in(list(known_sf))).height
paya = gl.filter((pl.col("je_source") == "Payables") & (pl.col("je_line_num") == "1"))
known_ap = {str(x) for x in ap["invoice_id"].to_list()} | {str(x) for x in chk["check_id"].to_list()}
miss_ap = paya.filter(~pl.col("reference_1").is_in(list(known_ap))).height
bank = read_scratch(catalog, schema, raw_volume, "bank_entries").filter(pl.col("kind") == "book")
gl_refs = set(gl["reference_2"].drop_nulls().to_list())
miss_bank = bank.filter((pl.col("e2e") != "") & ~pl.col("e2e").is_in(list(gl_refs))).height
check("lineage_keys_resolve", miss_sf == 0 and miss_ap == 0 and miss_bank == 0,
      f"unresolved: receivables={miss_sf}, payables={miss_ap}, bank e2e={miss_bank}")

# COMMAND ----------
# MAGIC %md ## Subledger tie-outs (only planted entity-periods may break)

# COMMAND ----------
closed = [(y, m) for (y, m) in periods_through(as_of)]
allowed = {k for k in planted_ep}
bal = gl.with_columns((pl.col("entered_dr") - pl.col("entered_cr")).alias("net"))


def gl_balance(account, ent, me):
    return float(bal.filter((pl.col("account") == account) & (pl.col("entity") == ent)
                            & (pl.col("default_effective_date") <= me))["net"].sum())


pr = read_scratch(catalog, schema, raw_volume, "payroll_results")
unexpected = []
for (y, m) in closed:
    me = min(month_end(y, m), cutoff)
    per = period_key(y, m)
    for ent in ENTITY_CODES:
        inv_e = sf_all.filter((pl.col("Corvane_Entity__c") == ent) & (pl.col("blng__InvoiceDate__c") <= me))
        paid = sf_pay.filter((pl.col("Corvane_Entity__c") == ent) & (pl.col("blng__PaymentDate__c") <= me))
        ar_sub = float(inv_e["blng__TotalAmount__c"].sum()) - float(paid["blng__Amount__c"].sum())
        ar_gl = gl_balance("11000", ent, me)
        if abs(ar_sub - ar_gl) > 1.0 and ("SLR-02", f"{ent}|{per}") not in allowed:
            unexpected.append(f"AR {ent} {per}: sub {ar_sub:,.2f} vs GL {ar_gl:,.2f}")
        ap_e = ap.filter((pl.col("_entity") == ent) & (pl.col("gl_date") <= me))
        ap_paid = chk.filter((pl.col("_entity") == ent) & (pl.col("check_date") <= me))
        ap_sub = float(ap_e["invoice_amount"].sum()) - float(ap_paid["amount"].sum())
        ap_gl = -gl_balance("20000", ent, me)
        if abs(ap_sub - ap_gl) > 1.0 and ("SLR-01", f"{ent}|{per}") not in allowed:
            unexpected.append(f"AP {ent} {per}: sub {ap_sub:,.2f} vs GL {ap_gl:,.2f}")
        wd = float(pr.filter((pl.col("Company") == ent) & (pl.col("Payment_Date") <= me))
                     .select((pl.col("Gross_Pay") + pl.col("Employer_Taxes")).sum()).item() or 0.0)
        glp = float(bal.filter((pl.col("entity") == ent) & (pl.col("je_source") == "Payroll") & (pl.col("je_category") == "Payroll Costing")
                               & (pl.col("account") != "22000") & (pl.col("default_effective_date") <= me))["net"].sum())
        if abs(wd - glp) > max(1000.0, 0.001 * wd) and ("SLR-03", f"{ent}|{per}") not in allowed:
            unexpected.append(f"Payroll {ent} {per}: Workday {wd:,.2f} vs GL {glp:,.2f}")
check("subledger_tieouts", not unexpected, f"{len(unexpected)} unplanned break(s): {unexpected[:6]}")

# COMMAND ----------
mods = set(planted["module"].unique())
check("planted_registry", {"M1", "M2", "M3", "M4", "M5", "DQ"} <= mods, f"modules planted: {sorted(mods)}; rows={len(planted)}")
for row in summary:
    print(f"{row['status']:5} {row['check']:24} {row['detail']}")
for f_ in failures:
    print("  -", f_)
if failures:
    raise AssertionError("Reconciliation gate failed:\n  " + "\n  ".join(failures))
dbutils.notebook.exit(json.dumps({"status": "PASS", "checks": summary, "planted": int(len(planted))}))
