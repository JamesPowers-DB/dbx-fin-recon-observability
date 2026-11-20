# Databricks notebook source
# MAGIC %md
# MAGIC # 06: Oracle General Ledger (journals)
# MAGIC
# MAGIC `oracle/gl_je_headers_<YYYY>M<MM>.csv` + `oracle/gl_je_lines_<YYYY>M<MM>.csv`.
# MAGIC Every journal balances in entered (functional) currency and in accounted USD
# MAGIC (one rate per journal), except the planted legacy upload (FSC-01).
# MAGIC
# MAGIC | Family | Source / category | Created by |
# MAGIC |---|---|---|
# MAGIC | Opening balances 2024-12-31 | Spreadsheet / Opening Balances | controller, approved |
# MAGIC | One journal per Salesforce invoice / payment | Receivables / Sales Invoices, Receipts | SFDC_INTEGRATION |
# MAGIC | One journal per AP invoice / check | Payables / Purchase Invoices, Payments | ORACLE_INTERFACE, AP_PAYMENT_BATCH |
# MAGIC | One journal per Workday run (+ payment) | Payroll / Payroll Costing, Payroll Payment | WORKDAY_INTEGRATION |
# MAGIC | Depreciation | Assets / Depreciation | FA_DEPRECIATION |
# MAGIC | Bank charges | Cash Management / Bank Charges | CASH_MGMT_AUTO |
# MAGIC | Accruals (+ reversals), prepaid amortization, tax, interest, reclasses | Manual | accountants, approved by the entity controller |
# MAGIC
# MAGIC Cash lines carry the bank EndToEndId in `reference_2` (the cash-matching
# MAGIC key). `reference_1` carries the subledger document id (the lineage key).
# MAGIC
# MAGIC Planted scenarios, registered in `meta_planted_exceptions`:
# MAGIC * JET-01 to JET-05 (journal testing).
# MAGIC * SLR-04, a manual JE to an AP control account (creates SLR-01 too).
# MAGIC * PAM-03, postings by terminated users.
# MAGIC * DQ-03, an orphan account (creates FSC-02).
# MAGIC * FSC-01, an unbalanced legacy upload (creates FSC-02).
# MAGIC * CASH-02, a GL-only cash entry.

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
as_of = load_as_of(catalog, schema, raw_volume)
cutoff = data_cutoff(as_of)
ay, am = active_period(as_of)
ACTIVE = period_key(ay, am)
ORA = volume_dir(catalog, schema, raw_volume, "oracle")
for p in ("gl_je_headers", "gl_je_lines"):
    wipe_family(ORA, p)
planted = PlantedRegistry("06_oracle_gl")
rng = rng_for("oracle_gl")
targets = monthly_targets(read_scratch(catalog, schema, raw_volume, "anchors"))
fin = read_scratch(catalog, schema, raw_volume, "finance_people")
ghosts = read_scratch(catalog, schema, raw_volume, "ghost_users")
sod_user = int(read_scratch(catalog, schema, raw_volume, "scenario_users")["sod_journal_user"][0])
sf_inv = read_scratch(catalog, schema, raw_volume, "sf_invoices")
sf_pay = read_scratch(catalog, schema, raw_volume, "sf_payments")
ap_inv = read_scratch(catalog, schema, raw_volume, "ap_invoices")
ap_chk = read_scratch(catalog, schema, raw_volume, "ap_checks")
pr = read_scratch(catalog, schema, raw_volume, "payroll_results")
pr_runs = read_scratch(catalog, schema, raw_volume, "payroll_runs")
ent_mix = {e["code"]: e["mix"] for e in ENTITIES}
preparers = {e: fin.filter((pl.col("entity") == e) & pl.col("job").is_in(["Accountant", "Senior Accountant"]))["user_id"].to_list()
             for e in ENTITY_CODES}
controllers = {e: fin.filter((pl.col("entity") == e) & (pl.col("job") == "Controller"))["user_id"].to_list() for e in ENTITY_CODES}
JE_BASE = 1_000_000
TERMINATED = {int(r["user_id"]): r["termination_date"] for r in ghosts.iter_rows(named=True)}


def active_preparers(ent, by_date):
    """Preparers still employed through by_date (terminated users only post in planted PAM-03 scenarios)."""
    act = [u for u in preparers[ent] if TERMINATED.get(int(u)) is None or TERMINATED[int(u)] > by_date]
    return act or preparers[ent]

# FX lookup frame (currency, year, month) -> rate, for vectorized families.
fx_rows = [{"ccy": c, "y": y, "m": m, "rate": fx_rate(c, y, m)} for c in FX_BASE
           for (y, m) in [(2024, 12)] + periods_through(as_of)]
FX = frame(fx_rows).with_columns(pl.col("y").cast(pl.Int32), pl.col("m").cast(pl.Int8))

HDR_COLS = ["je_header_id", "ledger_id", "period_name", "je_source", "je_category", "name", "description", "status",
            "actual_flag", "default_effective_date", "posted_date", "created_by", "creation_date",
            "approval_status_code", "approved_by", "approval_date", "currency_code"]
LINE_COLS = ["je_header_id", "je_line_num", "code_combination_id", "entered_dr", "entered_cr", "accounted_dr",
             "accounted_cr", "description", "reference_1", "reference_2", "currency_conversion_rate"]

# COMMAND ----------
# MAGIC %md ## Vectorized families: one journal per subledger document

# COMMAND ----------
def doc_journals(docs: pl.DataFrame, start_id: int):
    """docs: ent, d, amount (fc, > 0), dr_ccid, cr_ccid, ref1, ref2, source, category, name, desc,
    created_by, hour. Returns (headers, lines, next_id)."""
    n = docs.height
    if n == 0:
        return pl.DataFrame(), pl.DataFrame(), start_id
    ccy_map = {e: ENTITY_BY_CODE[e]["currency"] for e in ENTITY_CODES}
    led_map = {e: ENTITY_BY_CODE[e]["ledger_id"] for e in ENTITY_CODES}
    d = (docs.with_columns(
            pl.int_range(start_id, start_id + n).alias("je_header_id"),
            pl.col("ent").replace_strict(ccy_map).alias("ccy"),
            pl.col("ent").replace_strict(led_map).alias("ledger_id"),
            pl.col("d").dt.year().cast(pl.Int32).alias("y"), pl.col("d").dt.month().cast(pl.Int8).alias("m"))
         .join(FX, on=["ccy", "y", "m"], how="left")
         .with_columns((pl.col("amount") * pl.col("rate")).round(2).alias("acct")))
    posted = pl.col("d").cast(pl.Datetime) + pl.duration(hours=pl.col("hour"), minutes=(pl.col("je_header_id") % 50))
    hdr = d.select(
        "je_header_id", "ledger_id",
        pl.col("d").dt.strftime("%b-%y").str.to_uppercase().alias("period_name"),
        pl.col("source").alias("je_source"), pl.col("category").alias("je_category"),
        "name", pl.col("desc").alias("description"), pl.lit("P").alias("status"), pl.lit("A").alias("actual_flag"),
        pl.col("d").alias("default_effective_date"), posted.alias("posted_date"), "created_by",
        (posted - pl.duration(minutes=3)).alias("creation_date"),
        pl.lit("N").alias("approval_status_code"), pl.lit(None, pl.Int64).alias("approved_by"),
        pl.lit(None, pl.Datetime).alias("approval_date"), pl.col("ccy").alias("currency_code"))
    l1 = d.select("je_header_id", pl.lit(1).alias("je_line_num"), pl.col("dr_ccid").alias("code_combination_id"),
                  pl.col("amount").alias("entered_dr"), pl.lit(0.0).alias("entered_cr"),
                  pl.col("acct").alias("accounted_dr"), pl.lit(0.0).alias("accounted_cr"),
                  pl.col("desc").alias("description"), pl.col("ref1").alias("reference_1"),
                  pl.col("ref2").alias("reference_2"), pl.col("rate").alias("currency_conversion_rate"))
    l2 = d.select("je_header_id", pl.lit(2).alias("je_line_num"), pl.col("cr_ccid").alias("code_combination_id"),
                  pl.lit(0.0).alias("entered_dr"), pl.col("amount").alias("entered_cr"),
                  pl.lit(0.0).alias("accounted_dr"), pl.col("acct").alias("accounted_cr"),
                  pl.col("desc").alias("description"), pl.col("ref1").alias("reference_1"),
                  pl.col("ref2").alias("reference_2"), pl.col("rate").alias("currency_conversion_rate"))
    return hdr, pl.concat([l1, l2]), start_id + n


families = []
next_id = JE_BASE + 100_000     # 1,000,001..1,099,999 reserved for manual and planted journals

inv_seg = sf_inv.select(pl.col("Id"), pl.col("Corvane_Segment__c").alias("seg"), "Corvane_Opening_Balance__c", "_gl_skip")
rev_acct = {s["code"]: s["rev_acct"] for s in SEGMENTS}
sfi = (sf_inv.filter(~pl.col("Corvane_Opening_Balance__c") & ~pl.col("_gl_skip"))
       .select(pl.col("Corvane_Entity__c").alias("ent"), pl.col("blng__InvoiceDate__c").alias("d"),
               pl.col("blng__TotalAmount__c").alias("amount"),
               (pl.col("Corvane_Entity__c") + "-" + pl.col("Corvane_Segment__c") + "-11000").alias("dr_ccid"),
               (pl.col("Corvane_Entity__c") + "-" + pl.col("Corvane_Segment__c") + "-"
                + pl.col("Corvane_Segment__c").replace_strict(rev_acct)).alias("cr_ccid"),
               pl.col("Id").alias("ref1"), pl.col("Name").alias("ref2"),
               pl.lit("Receivables").alias("source"), pl.lit("Sales Invoices").alias("category"),
               ("SFDC " + pl.col("Name")).alias("name"), pl.lit("Salesforce Billing invoice").alias("desc"),
               pl.lit(2).alias("created_by"), pl.lit(22).alias("hour")))
h, l, next_id = doc_journals(sfi, next_id); families.append(("receivables", h, l))

sfp = (sf_pay.join(inv_seg, left_on="blng__Invoice__c", right_on="Id", how="left")
       .select(pl.col("Corvane_Entity__c").alias("ent"), pl.col("blng__PaymentDate__c").alias("d"),
               pl.col("blng__Amount__c").alias("amount"),
               (pl.col("Corvane_Entity__c") + "-COR-10100").alias("dr_ccid"),
               (pl.col("Corvane_Entity__c") + "-" + pl.col("seg") + "-11000").alias("cr_ccid"),
               pl.col("Id").alias("ref1"), pl.col("Bank_Reference__c").alias("ref2"),
               pl.lit("Receivables").alias("source"), pl.lit("Receipts").alias("category"),
               ("SFDC receipt " + pl.col("Name")).alias("name"), pl.lit("Customer receipt").alias("desc"),
               pl.lit(2).alias("created_by"), pl.lit(23).alias("hour")))
h, l, next_id = doc_journals(sfp, next_id); families.append(("receipts", h, l))

api = (ap_inv.filter(~pl.col("_opening") & ~pl.col("_gl_skip"))
       .select(pl.col("_entity").alias("ent"), pl.col("gl_date").alias("d"), pl.col("invoice_amount").alias("amount"),
               pl.col("dist_code_combination_id").alias("dr_ccid"), (pl.col("_entity") + "-COR-20000").alias("cr_ccid"),
               pl.col("invoice_id").cast(pl.Utf8).alias("ref1"), pl.col("invoice_num").alias("ref2"),
               pl.lit("Payables").alias("source"), pl.lit("Purchase Invoices").alias("category"),
               ("AP " + pl.col("invoice_num")).alias("name"), pl.col("description").alias("desc"),
               pl.lit(1).alias("created_by"), pl.lit(20).alias("hour")))
h, l, next_id = doc_journals(api, next_id); families.append(("payables", h, l))

apc = (ap_chk.select(pl.col("_entity").alias("ent"), pl.col("check_date").alias("d"), pl.col("amount"),
                     (pl.col("_entity") + "-COR-20000").alias("dr_ccid"), (pl.col("_entity") + "-COR-10100").alias("cr_ccid"),
                     pl.col("check_id").cast(pl.Utf8).alias("ref1"), pl.col("check_number").alias("ref2"),
                     pl.lit("Payables").alias("source"), pl.lit("Payments").alias("category"),
                     ("AP payment " + pl.col("check_number")).alias("name"), pl.lit("Supplier payment").alias("desc"),
                     pl.lit(4).alias("created_by"), pl.lit(19).alias("hour")))
h, l, next_id = doc_journals(apc, next_id); families.append(("payments", h, l))

# Payroll: one costing journal per run x department line, one payment journal per run.
dept_acct = {"RND": "60000", "SNM": "61000", "GNA": "62000", "SVC": "52000"}
pr_ok = pr.join(pr_runs.select("Payroll_Run_ID", "_gl_skip"), on="Payroll_Run_ID").filter(~pl.col("_gl_skip"))
pr_agg = (pr_ok.group_by(["Payroll_Run_ID", "Company", "Supervisory_Org", "Payment_Date"])
          .agg((pl.col("Gross_Pay") + pl.col("Employer_Taxes")).sum().round(2).alias("amount")))
prc = (pr_agg.select(pl.col("Company").alias("ent"), pl.col("Payment_Date").alias("d"), "amount",
                     (pl.col("Company") + "-" + pl.when(pl.col("Supervisory_Org") == "SVC").then(pl.lit("SVC"))
                      .otherwise(pl.lit("COR")) + "-" + pl.col("Supervisory_Org").replace_strict(dept_acct)).alias("dr_ccid"),
                     (pl.col("Company") + "-COR-22000").alias("cr_ccid"), pl.col("Payroll_Run_ID").alias("ref1"),
                     pl.col("Supervisory_Org").alias("ref2"), pl.lit("Payroll").alias("source"),
                     pl.lit("Payroll Costing").alias("category"), ("Payroll " + pl.col("Payroll_Run_ID")).alias("name"),
                     ("Payroll costing " + pl.col("Supervisory_Org")).alias("desc"), pl.lit(3).alias("created_by"),
                     pl.lit(18).alias("hour")))
h, l, next_id = doc_journals(prc, next_id); families.append(("payroll", h, l))
prp_src = pr_ok.group_by(["Payroll_Run_ID", "Company", "Payment_Date"]).agg(
    (pl.col("Gross_Pay") + pl.col("Employer_Taxes")).sum().round(2).alias("amount"))
prp = prp_src.select(pl.col("Company").alias("ent"), pl.col("Payment_Date").alias("d"), "amount",
                     (pl.col("Company") + "-COR-22000").alias("dr_ccid"), (pl.col("Company") + "-COR-10200").alias("cr_ccid"),
                     pl.col("Payroll_Run_ID").alias("ref1"), ("PAY-" + pl.col("Payroll_Run_ID")).alias("ref2"),
                     pl.lit("Payroll").alias("source"), pl.lit("Payroll Payment").alias("category"),
                     ("Payroll payment " + pl.col("Payroll_Run_ID")).alias("name"),
                     pl.lit("Net pay, taxes and deductions remitted").alias("desc"), pl.lit(3).alias("created_by"),
                     pl.lit(19).alias("hour"))
h, l, next_id = doc_journals(prp, next_id); families.append(("payroll_payment", h, l))
print({k: hh.height for k, hh, _ in families})

# COMMAND ----------
# MAGIC %md ## Row-built families: opening, depreciation, fees, manual journals, plants

# COMMAND ----------
H, L = [], []
mseq = JE_BASE


def mj(ent, d, source, category, name, desc, lines, created_by, approved_by=None, hour=11, minute=None,
       approval_lag_min=45, approval_code=None, posted_override=None, created_override=None, approved_override=None):
    """Row-built journal. lines = [(ccid, dr_fc, cr_fc, line_desc, ref1, ref2)]. Returns je_header_id."""
    global mseq
    mseq += 1
    e = ENTITY_BY_CODE[ent]
    rate = fx_rate(e["currency"], d.year, d.month)
    minute = int(rng.integers(0, 59)) if minute is None else minute
    created = created_override or ts(d, hour, minute)
    approved = approved_override or (created + timedelta(minutes=approval_lag_min) if approved_by else None)
    posted = posted_override or ((approved or created) + timedelta(minutes=20))
    code = approval_code or ("A" if approved_by else "N")
    H.append((mseq, e["ledger_id"], oracle_period_name(d.year, d.month), source, category, name, desc, "P", "A", d,
              posted, created_by, created, code, approved_by, approved, e["currency"]))
    acc = []
    for i, (ccid, dr, cr, ldesc, r1, r2) in enumerate(lines, start=1):
        adr, acr = round(dr * rate, 2), round(cr * rate, 2)
        acc.append([mseq, i, ccid, round(dr, 2), round(cr, 2), adr, acr, ldesc, r1, r2, rate])
    # Force accounted balance (rounding) unless entered is intentionally unbalanced.
    edr, ecr = sum(a[3] for a in acc), sum(a[4] for a in acc)
    if abs(edr - ecr) < 0.005:
        diff = round(sum(a[5] for a in acc) - sum(a[6] for a in acc), 2)
        if diff:
            last = acc[-1]
            if last[6]:
                last[6] = round(last[6] + diff, 2)
            else:
                last[5] = round(last[5] - diff, 2)
    L.extend(tuple(a) for a in acc)
    return mseq


def pick(seq_list):
    return int(seq_list[int(rng.integers(0, len(seq_list)))])


# Opening balances, 2024-12-31 (per entity, in functional currency at the December rate).
op_date = date(2024, 12, 31)
for e in ENTITIES:
    rate = fx_rate(e["currency"], 2024, 12)
    lines = []
    for acct, usd_m in OPENING_BS_USD_M.items():
        fc = round(usd_m * 1_000_000 * e["mix"] / rate, 2)
        if fc == 0:
            continue
        ccid = f"{e['code']}-COR-{acct}"
        lines.append((ccid, fc if fc > 0 else 0.0, -fc if fc < 0 else 0.0, "Opening balance", "OPENING", None))
    drs, crs = sum(x[1] for x in lines), sum(x[2] for x in lines)
    if abs(drs - crs) >= 0.005:
        lines.append((f"{e['code']}-COR-31000", max(0.0, crs - drs), max(0.0, drs - crs), "Opening balance rounding", "OPENING", None))
    mj(e["code"], op_date, "Spreadsheet", "Opening Balances", f"Opening balances {e['code']}", "Conversion from legacy ERP",
       lines, created_by=controllers[e["code"]][0], approved_by=controllers["US01" if e["code"] != "US01" else "GB01"][0], hour=10)

# Monthly recurring journals per entity.
consol = {r["period"]: r for r in targets.filter(pl.col("segment_code") == "CONSOL").iter_rows(named=True)}
prepaid_q = (ap_inv.filter((pl.col("_category") == "prepaid") & ~pl.col("_opening"))
             .with_columns(pl.col("gl_date").dt.year().alias("y"), ((pl.col("gl_date").dt.month() - 1) // 3 + 1).alias("q"))
             .group_by(["_entity", "y", "q"]).agg(pl.col("invoice_amount").sum().alias("amt")))
prepaid_q = {(r["_entity"], r["y"], r["q"]): r["amt"] for r in prepaid_q.iter_rows(named=True)}
tax_accrued: Dict[Tuple[str, int, int], float] = {}
cash_manual = []   # (je, line, ent, account_type, date, amount_signed_fc, ref2, no_bank)

# The opening balance sheet's accrued liabilities include the December 2024
# month-end accrual; reverse it on the first business day of January 2025 like
# every other month-end accrual.
jan = consol[period_key(*FIRST_PERIOD)]
jan_bd = business_days(*FIRST_PERIOD)[0]
for e in ENTITIES:
    ent, rate = e["code"], fx_rate(e["currency"], 2024, 12)
    acc = round((float(jan["snm"]) + float(jan["gna"])) * e["mix"] / rate * 0.02, 2)
    a1, a2 = round(acc * 0.8, 2), round(acc * 0.2, 2)
    mj(ent, jan_bd, "Manual", "Accrual Reversal", f"Reverse accrual {ent} 2024-12", "Reversal of the December 2024 accrual (opening balance)",
       [(f"{ent}-COR-21000", a1 + a2, 0.0, "Reverse accrual", "OPENING", None),
        (f"{ent}-COR-61000", 0.0, a1, "Reverse accrual", "OPENING", None),
        (f"{ent}-COR-62000", 0.0, a2, "Reverse accrual", "OPENING", None)],
       created_by=pick(active_preparers(ent, cutoff)), approved_by=pick(controllers[ent]), hour=9)

for (y, m) in periods_through(as_of):
    row = consol[period_key(y, m)]
    bds = [d for d in business_days(y, m) if d <= cutoff]
    if not bds:
        continue
    last_bd_full = business_days(y, m)[-1]
    month_closed = last_bd_full <= cutoff
    full_frac = 1.0 if month_closed else max(elapsed_business_fraction(y, m, as_of), 1e-9)
    q = (m - 1) // 3 + 1
    for e in ENTITIES:
        ent, w = e["code"], e["mix"]
        rate = fx_rate(e["currency"], y, m)
        prep, ctrl = active_preparers(ent, month_end(y, m)), controllers[ent]
        # Depreciation (month end, so only for closed months).
        if month_closed:
            dep = round(float(row["dna"]) * w / rate, 2)
            mj(ent, last_bd_full, "Assets", "Depreciation", f"Depreciation {ent} {y}-{m:02d}", "Straight-line depreciation",
               [(f"{ent}-COR-63000", dep, 0.0, "Depreciation expense", f"FA-{ent}-{y}{m:02d}", None),
                (f"{ent}-COR-15500", 0.0, dep, "Accumulated depreciation", f"FA-{ent}-{y}{m:02d}", None)],
               created_by=5, hour=21)
        # Bank charges recorded from the bank's monthly analysis (matched to bank fee debits).
        fee_d = bds[min(len(bds) - 1, 2)]
        fee = round(float(rng.uniform(600, 2600)) / rate, 2)
        fee_ref = f"FEE-{ent}-OPS-{y}{m:02d}"
        je = mj(ent, fee_d, "Cash Management", "Bank Charges", f"Bank charges {ent} {y}-{m:02d}", "Account analysis fees",
                [(f"{ent}-COR-64000", fee, 0.0, "Bank charges", fee_ref, fee_ref),
                 (f"{ent}-COR-10100", 0.0, fee, "Bank charges", fee_ref, fee_ref)], created_by=6, hour=16)
        cash_manual.append((je, 2, ent, "OPS", fee_d, -fee, fee_ref, False))
        if month_closed:
            # Month-end accrual (reversed on the first business day of next month).
            opex_m = (float(row["snm"]) + float(row["gna"])) * w / rate
            acc = round(opex_m * 0.02, 2)
            je_acc = mj(ent, last_bd_full, "Manual", "Accrual", f"Month-end accrual {ent} {y}-{m:02d}",
                        "Accrue unbilled services and marketing", [
                            (f"{ent}-COR-61000", round(acc * 0.8, 2), 0.0, "Accrued marketing", None, None),
                            (f"{ent}-COR-62000", round(acc * 0.2, 2), 0.0, "Accrued services", None, None),
                            (f"{ent}-COR-21000", 0.0, round(acc * 0.8, 2) + round(acc * 0.2, 2), "Accrued liabilities", None, None)],
                        created_by=pick(prep), approved_by=pick(ctrl), hour=15)
            ny, nm = next_month(y, m)
            rev_d = business_days(ny, nm)[0]
            if rev_d <= cutoff:
                mj(ent, rev_d, "Manual", "Accrual Reversal", f"Reverse accrual {ent} {y}-{m:02d}",
                   f"Auto-reversal of journal {je_acc}", [
                       (f"{ent}-COR-21000", round(acc * 0.8, 2) + round(acc * 0.2, 2), 0.0, "Reverse accrual", str(je_acc), None),
                       (f"{ent}-COR-61000", 0.0, round(acc * 0.8, 2), "Reverse accrual", str(je_acc), None),
                       (f"{ent}-COR-62000", 0.0, round(acc * 0.2, 2), "Reverse accrual", str(je_acc), None)],
                   created_by=pick(prep), approved_by=pick(ctrl), hour=9)
            # Prepaid amortization (1/3 of the quarter's prepaid additions).
            amort = round(prepaid_q.get((ent, y, q), 0.0) / 3.0, 2)
            if amort > 0:
                mj(ent, last_bd_full, "Manual", "Prepaid Amortization", f"Prepaid amortization {ent} {y}-{m:02d}",
                   "Amortize insurance and support renewals",
                   [(f"{ent}-COR-62000", amort, 0.0, "Prepaid amortization", None, None),
                    (f"{ent}-COR-12000", 0.0, amort, "Prepaid amortization", None, None)],
                   created_by=pick(prep), approved_by=pick(ctrl), hour=14)
            # Tax provision.
            tax = round(float(row["tax"]) * w / rate, 2)
            mj(ent, last_bd_full, "Manual", "Tax Provision", f"Income tax provision {ent} {y}-{m:02d}",
               "Monthly effective-rate provision", [(f"{ent}-COR-80000", tax, 0.0, "Tax expense", None, None),
                                                    (f"{ent}-COR-24000", 0.0, tax, "Tax payable", None, None)],
               created_by=pick(prep), approved_by=pick(ctrl), hour=16)
            tax_accrued[(ent, y, q)] = tax_accrued.get((ent, y, q), 0.0) + tax
        # Quarterly tax payment on the 8th business day after quarter end.
        if m in (1, 4, 7, 10):
            pq_y, pq = (y - 1, 4) if m == 1 else (y, q - 1)
            due = tax_accrued.get((ent, pq_y, pq), 0.0)
            pay_d = business_days(y, m)[7]
            if due > 0 and pay_d <= cutoff:
                ref = f"TAX-{ent}-{pq_y}Q{pq}"
                je = mj(ent, pay_d, "Manual", "Tax Payment", f"Tax installment {ent} {pq_y}Q{pq}", "Quarterly installment",
                        [(f"{ent}-COR-24000", round(due, 2), 0.0, "Tax paid", ref, ref),
                         (f"{ent}-COR-10100", 0.0, round(due, 2), "Tax paid", ref, ref)],
                        created_by=pick(prep), approved_by=pick(ctrl), hour=11)
                cash_manual.append((je, 2, ent, "OPS", pay_d, -round(due, 2), ref, False))
        # Interest on corporate debt (US01).
        if ent == "US01" and len(bds) >= 5:
            int_d = bds[4]
            amt = round(float(row["interest"]) / full_frac if not month_closed else float(row["interest"]), 2)
            ref = f"INT-US01-{y}{m:02d}"
            je = mj(ent, int_d, "Manual", "Interest", f"Term loan interest {y}-{m:02d}", "Monthly interest payment",
                    [("US01-COR-70000", amt, 0.0, "Interest expense", ref, ref), ("US01-COR-10100", 0.0, amt, "Interest paid", ref, ref)],
                    created_by=pick(prep), approved_by=pick(ctrl), hour=10)
            cash_manual.append((je, 2, ent, "OPS", int_d, -amt, ref, False))
        # Reclasses within the same statement line (no effect on line totals).
        for k in range(int(rng.integers(3, 7))):
            d = bds[int(rng.integers(0, len(bds)))]
            amt = round(float(rng.lognormal(10.2, 0.9)) / rate, 2)
            a_from, a_to = (("62000", "64000") if k % 2 else ("64000", "62000"))
            mj(ent, d, "Manual", "Reclass", f"Reclass {ent} {d:%Y%m%d}-{k}", "Reclass between G&A accounts",
               [(f"{ent}-COR-{a_to}", amt, 0.0, "Reclass", None, None), (f"{ent}-COR-{a_from}", 0.0, amt, "Reclass", None, None)],
               created_by=pick(prep), approved_by=pick(ctrl), hour=int(rng.integers(9, 17)))

# COMMAND ----------
# MAGIC %md ## Planted journal scenarios

# COMMAND ----------
act_bds = [d for d in business_days(ay, am) if d <= cutoff]
py, pm = (ay - 1, 12) if am == 1 else (ay, am - 1)
prev_bds = business_days(py, pm)
PREV = period_key(py, pm)
sod_ent = fin.filter(pl.col("user_id") == sod_user)["entity"][0]


def usd(ent, d, fc):
    return fc * entity_rate(ent, d)


def mid(bds, k=0):
    return bds[min(len(bds) - 1, max(0, len(bds) // 2 + k))]


# JET-01: preparer approved their own journal (the SoD user in the active month).
for k, amt_usd in enumerate([48_250.00, 186_400.00, 312_900.00]):
    if not act_bds:
        break
    d = mid(act_bds, k - 1)
    fc = round(amt_usd / entity_rate(sod_ent, d), 2)
    je = mj(sod_ent, d, "Manual", "Reclass", f"Reclass G&A costs {d:%Y%m%d}-{k}", "Reclass to correct cost center",
            [(f"{sod_ent}-COR-62000", fc, 0.0, "Reclass", None, None), (f"{sod_ent}-COR-64000", 0.0, fc, "Reclass", None, None)],
            created_by=sod_user, approved_by=sod_user, hour=17)
    planted.add("M3", "JET-01", str(je), sod_ent, ACTIVE, amt_usd, f"Journal {je} created and approved by the same user ({sod_user})")
for k, amt_usd in enumerate([95_000.00, 61_300.00]):
    ent = ENTITY_CODES[(k + 3) % 8]
    d = prev_bds[5 + k]
    u = pick(active_preparers(ent, cutoff))
    fc = round(amt_usd / entity_rate(ent, d), 2)
    je = mj(ent, d, "Manual", "Adjustment", f"Adjust deferred costs {d:%Y%m%d}", "Adjustment",
            [(f"{ent}-COR-62000", fc, 0.0, "Adjustment", None, None), (f"{ent}-COR-64000", 0.0, fc, "Adjustment", None, None)],
            created_by=u, approved_by=u, hour=12)
    planted.add("M3", "JET-01", str(je), ent, PREV, amt_usd, f"Journal {je} self-approved (approval delegation misconfigured)",
                expected_disposition="explained")

# JET-02: manual journal over $250k posted before (or without) approval.
for k, amt_usd in enumerate([420_000.00, 1_250_000.00]):
    if not act_bds:
        break
    ent = ["US01", "DE01"][k]
    d = mid(act_bds, k)
    fc = round(amt_usd / entity_rate(ent, d), 2)
    created = ts(d, 10, 5)
    if k == 0:   # approved after posting
        je = mj(ent, d, "Manual", "Adjustment", f"True-up hosting accrual {d:%Y%m%d}", "True-up",
                [(f"{ent}-COR-62000", fc, 0.0, "True-up", None, None), (f"{ent}-COR-21000", 0.0, fc, "True-up", None, None)],
                created_by=pick(active_preparers(ent, cutoff)), approved_by=pick(controllers[ent]), created_override=created,
                posted_override=created + timedelta(minutes=12), approved_override=created + timedelta(days=2, hours=3))
    else:        # never approved
        je = mj(ent, d, "Manual", "Adjustment", f"Restructuring reserve {d:%Y%m%d}", "Reserve top-up",
                [(f"{ent}-COR-62000", fc, 0.0, "Reserve", None, None), (f"{ent}-COR-21000", 0.0, fc, "Reserve", None, None)],
                created_by=pick(active_preparers(ent, cutoff)), approved_by=None, approval_code="R", created_override=created)
    planted.add("M3", "JET-02", str(je), ent, ACTIVE, amt_usd,
                f"Manual journal {je} over the $250k threshold posted {'before approval' if k == 0 else 'without approval'}")
    if k == 1:
        planted.add("M5", "FPA-03", f"{ACTIVE}|{ent}|IS-320", ent, ACTIVE, amt_usd,
                    "Unexplained G&A variance caused by the unapproved restructuring reserve")
d = prev_bds[9]
fc = round(275_000.00 / entity_rate("GB01", d), 2)
je = mj("GB01", d, "Manual", "Adjustment", f"Bonus accrual {d:%Y%m%d}", "Bonus accrual",
        [("GB01-COR-61000", fc, 0.0, "Bonus", None, None), ("GB01-COR-21000", 0.0, fc, "Bonus", None, None)],
        created_by=pick(active_preparers("GB01", cutoff)), approved_by=None, approval_code="R", created_override=ts(d, 11, 0))
planted.add("M3", "JET-02", str(je), "GB01", PREV, 275_000.00, f"Manual journal {je} over threshold posted without approval",
            expected_disposition="explained")

# JET-03: weekend or after-hours postings by people.
weekend_days = [date(ay, am, 1) + timedelta(days=i) for i in range((cutoff - date(ay, am, 1)).days + 1)]
weekend_days = [d for d in weekend_days if d.weekday() >= 5]
for k, (amt_usd, when) in enumerate([(37_800.00, "weekend"), (152_000.00, "weekend"), (64_500.00, "late")]):
    ent = ["SG01", "US02", "BR01"][k]
    if when == "weekend" and weekend_days:
        d, hour = weekend_days[min(k, len(weekend_days) - 1)], 22
    elif act_bds:
        d, hour = mid(act_bds, 2), 23
    else:
        continue
    fc = round(amt_usd / entity_rate(ent, d), 2)
    je = mj(ent, d, "Manual", "Adjustment", f"Adjustment {d:%Y%m%d} {hour}h", "Late adjustment",
            [(f"{ent}-COR-62000", fc, 0.0, "Adjustment", None, None), (f"{ent}-COR-21000", 0.0, fc, "Adjustment", None, None)],
            created_by=pick(active_preparers(ent, cutoff)), approved_by=pick(controllers[ent]), hour=hour, minute=41, approval_lag_min=8)
    planted.add("M3", "JET-03", str(je), ent, ACTIVE, amt_usd,
                f"Manual journal {je} posted {'on a weekend' if when == 'weekend' else 'after hours'} ({d:%a} {hour}:41)")

# JET-04: duplicate journals (same account, same amount, within 3 days).
for k, amt_usd in enumerate([88_120.55, 233_407.10]):
    if len(act_bds) < 4:
        break
    ent = ["IE01", "US01"][k]
    d1 = act_bds[min(len(act_bds) - 3, 2 + k)]
    d2 = add_business_days(d1, 1)
    if d2 > cutoff:
        d2 = d1
    fc = round(amt_usd / entity_rate(ent, d1), 2)
    lines = [(f"{ent}-COR-61000", fc, 0.0, "Agency invoice accrual", None, None), (f"{ent}-COR-21000", 0.0, fc, "Agency invoice accrual", None, None)]
    mj(ent, d1, "Manual", "Accrual", f"Agency accrual {d1:%Y%m%d}", "Agency invoice accrual", lines,
       created_by=pick(active_preparers(ent, cutoff)), approved_by=pick(controllers[ent]), hour=14)
    je2 = mj(ent, d2, "Manual", "Accrual", f"Agency accrual {d2:%Y%m%d}", "Agency invoice accrual", lines,
             created_by=pick(active_preparers(ent, cutoff)), approved_by=pick(controllers[ent]), hour=15)
    planted.add("M3", "JET-04", str(je2), ent, ACTIVE, amt_usd, f"Journal {je2} duplicates an accrual posted the prior business day")

# JET-05: round-dollar, outsized manual journals (KRI, INFO).
for k, amt_usd in enumerate([5_000_000.00, 1_000_000.00]):
    if not act_bds:
        break
    ent = ["US01", "GB01"][k]
    d = mid(act_bds, -2 + k)
    fc = amt_usd                                   # round in the entity's own currency
    je = mj(ent, d, "Manual", "Reclass", f"Reclass R&D allocation {d:%Y%m%d}", "Allocation of shared engineering",
            [(f"{ent}-COR-62000", fc, 0.0, "Allocation", None, None), (f"{ent}-COR-64000", 0.0, fc, "Allocation", None, None)],
            created_by=pick(active_preparers(ent, cutoff)), approved_by=pick(controllers[ent]), hour=16)
    planted.add("M3", "JET-05", str(je), ent, ACTIVE, amt_usd, f"Round-amount manual journal {je} far above this account's normal size")

# SLR-04 (+ SLR-01): manual journal to the AP control account (bypasses the subledger).
if act_bds:
    d = mid(act_bds, 1)
    fc = round(640_000.00 / entity_rate("CA01", d), 2)
    je = mj("CA01", d, "Manual", "Accrual", f"Topside AP accrual {d:%Y%m%d}", "Accrue unvouchered receipts directly to AP",
            [("CA01-COR-62000", fc, 0.0, "Topside accrual", None, None), ("CA01-COR-20000", 0.0, fc, "Topside accrual to AP control", None, None)],
            created_by=pick(active_preparers("CA01", cutoff)), approved_by=pick(controllers["CA01"]), hour=13)
    planted.add("M2", "SLR-04", str(je), "CA01", ACTIVE, 640_000.00, f"Manual journal {je} posted directly to the AP control account 20000")
    planted.add("M2", "SLR-01", f"CA01|{ACTIVE}", "CA01", ACTIVE, 640_000.00,
                "AP control account differs from the AP subledger by a manual topside journal")
    planted.add("M5", "FPA-03", f"{ACTIVE}|CA01|IS-320", "CA01", ACTIVE, 640_000.00,
                "Unexplained G&A variance caused by the topside AP accrual")

# PAM-03: postings by users after their Workday termination date.
for g in ghosts.filter(pl.col("posts_after_termination")).iter_rows(named=True):
    term, ent = g["termination_date"], g["entity"]
    end = g["access_end"] or cutoff
    days = [d for d in [term + timedelta(days=i) for i in range(1, 30)] if is_business_day(d) and d <= min(end, cutoff)]
    if not days:
        continue
    d = days[min(1, len(days) - 1)]
    fc = round(29_900.00 / entity_rate(ent, d), 2)
    je = mj(ent, d, "Manual", "Adjustment", f"Adjustment {d:%Y%m%d}", "Adjustment",
            [(f"{ent}-COR-62000", fc, 0.0, "Adjustment", None, None), (f"{ent}-COR-21000", 0.0, fc, "Adjustment", None, None)],
            created_by=int(g["user_id"]), approved_by=pick(controllers[ent]), hour=15)
    planted.add("M4", "PAM-03", str(je), ent, period_key(d.year, d.month), 29_900.00,
                f"Journal {je} posted by user {g['user_id']} {(d - term).days} days after termination ({term})",
                expected_disposition="open" if d.month == am and d.year == ay else "explained")

# DQ-03 (+ FSC-02): journal line to an account that is not in the chart of accounts.
if act_bds:
    d = mid(act_bds, -1)
    fc = round(18_400.00 / entity_rate("SG01", d), 2)
    je = mj("SG01", d, "Manual", "Adjustment", f"Adjustment {d:%Y%m%d}", "Legacy account code used",
            [(f"SG01-COR-{ORPHAN_ACCOUNT}", fc, 0.0, "Legacy suspense code", None, None),
             ("SG01-COR-62000", 0.0, fc, "Legacy suspense code", None, None)],
            created_by=pick(active_preparers("SG01", cutoff)), approved_by=pick(controllers["SG01"]), hour=12)
    planted.add("DQ", "DQ-03", f"{je}:1", "SG01", ACTIVE, 18_400.00, f"Journal {je} line 1 uses account {ORPHAN_ACCOUNT}, which is not in the chart of accounts")
    planted.add("M5", "FSC-02", f"SG01|{ACTIVE}", "SG01", ACTIVE, 18_400.00, "Balance sheet out of balance: unmapped account excluded from statements")
    planted.add("M5", "FSC-03", f"SG01|{ACTIVE}", "SG01", ACTIVE, 18_400.00, "Cash flow does not tie to balance sheet cash: unmapped account movement")

# FSC-01 (+ FSC-02): unbalanced legacy spreadsheet upload.
if act_bds:
    d = mid(act_bds, 0)
    je = mj("IE01", d, "Spreadsheet", "Adjustment", f"LEGACY-UPLOAD {d:%Y%m%d}", "Legacy interface batch (balancing check bypassed)",
            [("IE01-COR-62000", 21_250.00, 0.0, "Legacy upload", "LEGACY01", None),
             ("IE01-COR-21000", 0.0, 20_000.00, "Legacy upload", "LEGACY01", None)],
            created_by=pick(active_preparers("IE01", cutoff)), approved_by=pick(controllers["IE01"]), hour=19)
    planted.add("M5", "FSC-01", f"IE01|{ACTIVE}", "IE01", ACTIVE, usd("IE01", d, 1_250.00), f"Trial balance does not balance: journal {je} debits exceed credits by EUR 1,250.00")
    planted.add("M5", "FSC-02", f"IE01|{ACTIVE}", "IE01", ACTIVE, usd("IE01", d, 1_250.00), "Balance sheet out of balance by the unbalanced legacy upload")
    planted.add("M5", "FSC-03", f"IE01|{ACTIVE}", "IE01", ACTIVE, usd("IE01", d, 1_250.00), "Cash flow does not tie to balance sheet cash by the unbalanced amount")

# CASH-02: GL-only cash entry (no bank counterpart), dated past the aging window.
aged_act = aged_business_days(act_bds, 6)
if aged_act:
    d = aged_act[len(aged_act) // 2]
    fc = round(42_750.00 / entity_rate("DE01", d), 2)
    ref = f"MAN-DE01-{d:%Y%m%d}"
    je = mj("DE01", d, "Manual", "Adjustment", f"Expected customer refund {d:%Y%m%d}", "Record refund expected from customer",
            [("DE01-COR-10100", fc, 0.0, "Expected refund", ref, ref), ("DE01-COR-21000", 0.0, fc, "Expected refund", ref, ref)],
            created_by=pick(active_preparers("DE01", cutoff)), approved_by=pick(controllers["DE01"]), hour=11)
    cash_manual.append((je, 1, "DE01", "OPS", d, fc, ref, True))
    planted.add("M1", "CASH-02", f"GL:{je}:1", "DE01", ACTIVE, 42_750.00, f"Book-only cash entry (journal {je}) with no bank transaction")
    planted.add("M1", "CASH-03", f"DE01-OPS-0001|{ACTIVE}", "DE01", ACTIVE, 42_750.00, "Unexplained book-to-bank difference")

# COMMAND ----------
# MAGIC %md ## Re-interface last period's failed documents (cut-off timing breaks)
# MAGIC
# MAGIC Interface failures planted in the prior period are re-run on the active
# MAGIC month's second business day (T+2 of the prior close). The prior period keeps
# MAGIC its subledger break (dispositioned "explained" in close-tool history). The
# MAGIC active period ties. The payroll payment line is book-only: the bank already
# MAGIC paid the off-cycle run last month, and cash matching pairs them by EndToEndId.

# COMMAND ----------
if len(act_bds) >= 2:
    rd = act_bds[1]
    note = f"Re-interfaced {rd} after the interface failure in {PREV}"
    for r in sf_inv.filter(pl.col("_gl_skip") & (pl.col("blng__InvoiceDate__c").dt.strftime("%Y-%m") == PREV)).iter_rows(named=True):
        ent, seg = r["Corvane_Entity__c"], r["Corvane_Segment__c"]
        amt = r["blng__TotalAmount__c"]
        mj(ent, rd, "Receivables", "Sales Invoices", f"SFDC {r['Name']}", note,
           [(f"{ent}-{seg}-11000", amt, 0.0, "Salesforce Billing invoice", r["Id"], r["Name"]),
            (f"{ent}-{seg}-{rev_acct[seg]}", 0.0, amt, "Salesforce Billing invoice", r["Id"], r["Name"])],
           created_by=2, hour=22)
    for r in ap_inv.filter(pl.col("_gl_skip") & (pl.col("gl_date").dt.strftime("%Y-%m") == PREV)).iter_rows(named=True):
        ent = r["_entity"]
        mj(ent, rd, "Payables", "Purchase Invoices", f"AP {r['invoice_num']}", note,
           [(r["dist_code_combination_id"], r["invoice_amount"], 0.0, r["description"], str(r["invoice_id"]), r["invoice_num"]),
            (f"{ent}-COR-20000", 0.0, r["invoice_amount"], r["description"], str(r["invoice_id"]), r["invoice_num"])],
           created_by=1, hour=20)
    for run in pr_runs.filter(pl.col("_gl_skip") & (pl.col("Payment_Date").dt.strftime("%Y-%m") == PREV)).iter_rows(named=True):
        ent, rid = run["Company"], run["Payroll_Run_ID"]
        agg = (pr.filter(pl.col("Payroll_Run_ID") == rid).group_by("Supervisory_Org")
                 .agg((pl.col("Gross_Pay") + pl.col("Employer_Taxes")).sum().round(2).alias("amt")))
        total = round(float(agg["amt"].sum()), 2)
        lines = [(f"{ent}-{'SVC' if d == 'SVC' else 'COR'}-{dept_acct[d]}", a, 0.0, f"Payroll costing {d}", rid, d)
                 for d, a in zip(agg["Supervisory_Org"].to_list(), agg["amt"].to_list())]
        lines.append((f"{ent}-COR-22000", 0.0, total, "Payroll liabilities", rid, None))
        mj(ent, rd, "Payroll", "Payroll Costing", f"Payroll {rid}", note, lines, created_by=3, hour=18)
        je = mj(ent, rd, "Payroll", "Payroll Payment", f"Payroll payment {rid}", note,
                [(f"{ent}-COR-22000", total, 0.0, "Payroll paid", rid, f"PAY-{rid}"),
                 (f"{ent}-COR-10200", 0.0, total, "Payroll paid", rid, f"PAY-{rid}")], created_by=3, hour=19)
        cash_manual.append((je, 2, ent, "PAY", rd, -total, f"PAY-{rid}", True))

# COMMAND ----------
# MAGIC %md ## Assemble, write, hand off

# COMMAND ----------
mh = pl.DataFrame(H, schema=dict(zip(HDR_COLS, [pl.Int64, pl.Int64, pl.Utf8, pl.Utf8, pl.Utf8, pl.Utf8, pl.Utf8, pl.Utf8,
                                                pl.Utf8, pl.Date, pl.Datetime, pl.Int64, pl.Datetime, pl.Utf8, pl.Int64,
                                                pl.Datetime, pl.Utf8])), orient="row")
ml = pl.DataFrame(L, schema=dict(zip(LINE_COLS, [pl.Int64, pl.Int64, pl.Utf8, pl.Float64, pl.Float64, pl.Float64,
                                                 pl.Float64, pl.Utf8, pl.Utf8, pl.Utf8, pl.Float64])), orient="row")
headers = pl.concat([mh] + [h.select(HDR_COLS).cast(mh.schema) for _, h, _ in families], how="vertical")
lines = pl.concat([ml] + [l.select(LINE_COLS).cast(ml.schema) for _, _, l in families], how="vertical")
headers = headers.filter(pl.col("default_effective_date") <= cutoff)
lines = lines.join(headers.select("je_header_id", "default_effective_date"), on="je_header_id", how="inner")
tot = lines.group_by("je_header_id").agg(pl.col("accounted_dr").sum().round(2).alias("running_total_dr"),
                                         pl.col("accounted_cr").sum().round(2).alias("running_total_cr"))
headers = headers.join(tot, on="je_header_id", how="left").sort(["default_effective_date", "je_header_id"])
n_h = write_by_month(headers, "default_effective_date", ORA, "gl_je_headers", "csv")
n_l = write_by_month(lines.sort(["je_header_id", "je_line_num"]).rename({"default_effective_date": "effective_date"}),
                     "effective_date", ORA, "gl_je_lines", "csv")
print(f"journals={headers.height} lines={lines.height} files={n_h}/{n_l}")

# Cash lines for the bank generator (07): what the book says hit each bank account.
cash = (lines.filter(pl.col("code_combination_id").str.ends_with("-10100") | pl.col("code_combination_id").str.ends_with("-10200"))
        .join(headers.select("je_header_id", "je_source", "je_category"), on="je_header_id")
        .with_columns(pl.col("code_combination_id").str.slice(0, 4).alias("entity"),
                      pl.when(pl.col("code_combination_id").str.ends_with("-10200")).then(pl.lit("PAY")).otherwise(pl.lit("OPS")).alias("acct_type"),
                      (pl.col("entered_dr") - pl.col("entered_cr")).round(2).alias("amount_fc")))
no_bank = [(c[0], c[1]) for c in cash_manual if c[7]]
cash = cash.with_columns(pl.struct(["je_header_id", "je_line_num"]).map_elements(
    lambda s: (s["je_header_id"], s["je_line_num"]) in no_bank, return_dtype=pl.Boolean).alias("_no_bank"))
write_scratch(cash.filter(pl.col("default_effective_date") > date(2024, 12, 31)), catalog, schema, raw_volume, "gl_cash_lines")
write_scratch(headers.select("je_header_id", "ledger_id", "je_source", "created_by", "default_effective_date"),
              catalog, schema, raw_volume, "gl_headers_index")
planted.save(spark, catalog, schema)
