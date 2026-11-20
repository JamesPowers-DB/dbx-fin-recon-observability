# Databricks notebook source
# MAGIC %md
# MAGIC # 05: Oracle Payables (AP subledger)
# MAGIC
# MAGIC `oracle/ap_invoices_all_<YYYY>M<MM>.csv` and `oracle/ap_checks_all_<YYYY>M<MM>.csv`.
# MAGIC
# MAGIC * Spend is anchored per month:
# MAGIC   * cost of revenue by segment: hosting for CLD and ENT, components for DEV,
# MAGIC     contractors for 50% of SVC (the rest is Workday payroll);
# MAGIC   * the non-payroll 42% of R&D, S&M, and G&A;
# MAGIC   * capex (4% of revenue) and prepaid additions.
# MAGIC   Each month's spend is split by entity mix in functional currency.
# MAGIC * One payment (check) per invoice around the due date. `check_number` is the
# MAGIC   EndToEndId the bank echoes, so it is the cash-matching key.
# MAGIC * Opening AP at 2024-12-31: subledger invoices dated December 2024, carried in
# MAGIC   the GL opening journal.
# MAGIC * Planted (M2, SLR-01): AP invoices validated in Payables but never
# MAGIC   transferred to the GL.
# MAGIC * Planted (M5): two real spend spikes in the active month (a marketing campaign
# MAGIC   and a hosting overage). The live flux review must flag both as unexplained
# MAGIC   material variances.

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
for p in ("ap_invoices_all", "ap_checks_all"):
    wipe_family(ORA, p)
planted = PlantedRegistry("05_oracle_ap")
rng = rng_for("oracle_ap")
targets = monthly_targets(read_scratch(catalog, schema, raw_volume, "anchors"))
suppliers = read_scratch(catalog, schema, raw_volume, "suppliers")
fin = read_scratch(catalog, schema, raw_volume, "finance_people")
ap_clerks = fin.filter(pl.col("job") == "AP Specialist")["user_id"].to_list()
ent_mix = {e["code"]: e["mix"] for e in ENTITIES}
OPEX_NONPAYROLL = 1.0 - PAYROLL_SHARE_OF_OPEX
PREPAID_SHARE_OF_GNA = 0.06
AVG = {"hosting": 420_000, "components": 160_000, "contractors": 65_000, "rnd_tools": 45_000, "marketing": 75_000,
       "gna_services": 32_000, "facilities": 125_000, "capex": 260_000, "prepaid": 220_000}
sup_by_cat = {c: suppliers.filter(pl.col("vendor_type_lookup_code") == c) for c in AVG}

# COMMAND ----------
inv_rows, seq = [], 0


def add_invoice(ent, cat, inv_date, amount_fc, account, segment, description, opening=False, gl_skip=False):
    global seq
    seq += 1
    s = sup_by_cat[cat].row(int(rng.integers(0, sup_by_cat[cat].height)), named=True)
    terms = 30 if cat not in ("capex", "facilities") else 45
    inv_rows.append({
        "invoice_id": 400000 + seq, "invoice_num": f"{s['segment1']}-{inv_date:%y%m}-{seq:05d}",
        "vendor_id": s["vendor_id"], "vendor_name": s["vendor_name"], "org_id": ENTITY_BY_CODE[ent]["ledger_id"],
        "invoice_date": inv_date, "gl_date": inv_date, "invoice_amount": float(amount_fc),
        "invoice_currency_code": ENTITY_BY_CODE[ent]["currency"], "terms_name": f"Net {terms}",
        "due_date": inv_date + timedelta(days=terms), "approval_status": "APPROVED",
        "description": description, "dist_code_combination_id": f"{ent}-{segment}-{account}",
        "source": "Manual Invoice Entry", "created_by": int(rng.choice(ap_clerks)),
        "creation_date": ts(inv_date, int(rng.integers(9, 17)), int(rng.integers(0, 59))),
        "_category": cat, "_entity": ent, "_opening": opening, "_gl_skip": gl_skip,
    })


def spend(ent, cat, y, m, total_fc, account, segment, label):
    days = [d for d in business_days(y, m) if d <= cutoff]
    if total_fc <= 0 or not days:
        return
    n = max(1, int(round(total_fc * fx_rate(ENTITY_BY_CODE[ent]["currency"], y, m) / AVG[cat])))
    for amt, d in zip(renormalize(rng, n, round(total_fc, 2), sigma=0.75), pick_dates(rng, days, n, 1.3)):
        add_invoice(ent, cat, d, amt, account, segment, f"{label} {d:%b %Y}")


# Opening AP (subledger only).
for e in ENTITIES:
    usd = -OPENING_BS_USD_M["20000"] * 1_000_000 * e["mix"]
    fc = usd / fx_rate(e["currency"], 2024, 12)
    n = max(4, int(usd / 150_000))
    for amt, d in zip(renormalize(rng, n, round(fc, 2)), pick_dates(rng, business_days(2024, 12), n)):
        add_invoice(e["code"], str(rng.choice(["hosting", "marketing", "gna_services", "components"])), d, amt,
                    "62000", CORPORATE_SEGMENT, "Opening balance invoice", opening=True)

seg_rows = {(r["period"], r["segment_code"]): r for r in targets.iter_rows(named=True)}
for (period, segc), row in sorted(seg_rows.items()):
    if segc != "CONSOL" or row["status"] == "FUTURE":
        continue
    y, m = int(row["fiscal_year"]), int(row["fiscal_month"])
    for ent in ENTITY_CODES:
        rate = fx_rate(ENTITY_BY_CODE[ent]["currency"], y, m)
        w = ent_mix[ent]
        for s in SEGMENTS:
            cor = float(seg_rows[(period, s["code"])]["cost_of_revenue"]) * w
            if s["code"] == "SVC":
                spend(ent, "contractors", y, m, cor * 0.5 / rate, "52000", "SVC", "Delivery subcontractors")
            elif s["code"] == "DEV":
                spend(ent, "components", y, m, cor / rate, "51000", "DEV", "Device components")
            else:
                spend(ent, "hosting", y, m, cor / rate, "50000", s["code"], "Hosting and capacity")
        spend(ent, "rnd_tools", y, m, float(row["rnd"]) * OPEX_NONPAYROLL * w / rate, "60000", CORPORATE_SEGMENT,
              "Engineering software and tools")
        spend(ent, "marketing", y, m, float(row["snm"]) * OPEX_NONPAYROLL * w / rate, "61000", CORPORATE_SEGMENT,
              "Marketing programs")
        # 6% of G&A arrives as prepaid amortization from the GL (06), so AP carries the rest.
        gna = float(row["gna"]) * (OPEX_NONPAYROLL - PREPAID_SHARE_OF_GNA) * w / rate
        spend(ent, "gna_services", y, m, gna * 0.55, "62000", CORPORATE_SEGMENT, "Professional and advisory services")
        spend(ent, "facilities", y, m, gna * 0.45, "62000", CORPORATE_SEGMENT, "Facilities and rent")
        spend(ent, "capex", y, m, float(row["revenue"]) * 0.04 * w / rate, "15000", CORPORATE_SEGMENT,
              "Servers and network equipment")
        if m in (1, 4, 7, 10):
            spend(ent, "prepaid", y, m, float(row["gna"]) * PREPAID_SHARE_OF_GNA * w / rate * 3, "12000", CORPORATE_SEGMENT,
                  "Annual insurance and support renewals")

# COMMAND ----------
# MAGIC %md ## Planted: active-month spend spikes (live flux) and unposted invoices (SLR-01)

# COMMAND ----------
act_days = [d for d in business_days(ay, am) if d <= cutoff]
spikes = [("GB01", "marketing", "61000", CORPORATE_SEGMENT, 1_450_000, "IS-310",
           "Brand campaign launch, EMEA (unbudgeted)"),
          ("US02", "hosting", "50000", "CLD", 2_600_000, "IS-200",
           "Hosting overage, GPU capacity burst (unbudgeted)")]
for ent, cat, acct, seg, usd, fsli, desc in spikes:
    if not act_days:
        break
    d = act_days[min(len(act_days) - 1, max(0, len(act_days) // 2))]
    fc = usd / fx_rate(ENTITY_BY_CODE[ent]["currency"], ay, am)
    for part in renormalize(rng, 3, round(fc, 2), sigma=0.3):
        add_invoice(ent, cat, d, part, acct, seg, desc)
    planted.add("M5", "FPA-03", f"{ACTIVE}|{ent}|{fsli}", ent, ACTIVE, usd,
                f"Material variance vs budget from {desc.lower()}; needs controller explanation",
                expected_disposition="open")

inv = frame(inv_rows)


def plant_unposted(ent, y, m, n, disposition):
    global inv
    cand = inv.filter((pl.col("_entity") == ent) & (pl.col("gl_date").dt.year() == y) & (pl.col("gl_date").dt.month() == m)
                      & ~pl.col("_opening") & (pl.col("_category") == "gna_services"))
    pick = cand.sort("gl_date", descending=True).head(n)["invoice_id"].to_list()
    inv = inv.with_columns(pl.when(pl.col("invoice_id").is_in(pick)).then(True).otherwise(pl.col("_gl_skip")).alias("_gl_skip"))
    fc = float(cand.filter(pl.col("invoice_id").is_in(pick))["invoice_amount"].sum())
    planted.add("M2", "SLR-01", f"{ent}|{period_key(y, m)}", ent, period_key(y, m),
                fc * fx_rate(ENTITY_BY_CODE[ent]["currency"], y, m),
                f"{len(pick)} validated AP invoice(s) not transferred to the GL: AP subledger exceeds GL control account",
                expected_disposition=disposition)


py, pm = (ay - 1, 12) if am == 1 else (ay, am - 1)
plant_unposted("IE01", py, pm, 2, "explained")
plant_unposted("US02", ay, am, 2, "open")
print(f"AP invoices={inv.height}")

# COMMAND ----------
# MAGIC %md ## Payments (one check per invoice)

# COMMAND ----------
checks, cseq = [], 0
for r in inv.iter_rows(named=True):
    delay = int(round(rng.normal(0, 4)))
    cdate = max(r["invoice_date"] + timedelta(days=7), r["due_date"] + timedelta(days=delay))
    if r["_opening"]:
        cdate = max(cdate, date(2025, 1, 2))          # opening AP is paid after the opening balance date
    while not is_business_day(cdate):
        cdate += timedelta(days=1)
    if cdate > cutoff:
        continue
    cseq += 1
    checks.append({"check_id": 800000 + cseq, "check_number": f"CHK-{r['_entity']}-{cseq:07d}",
                   "invoice_id": r["invoice_id"], "vendor_id": r["vendor_id"], "vendor_name": r["vendor_name"],
                   "org_id": r["org_id"], "amount": r["invoice_amount"], "currency_code": r["invoice_currency_code"],
                   "check_date": cdate, "bank_account_name": f"{r['_entity']}-OPS-0001",
                   "payment_method_code": str(rng.choice(["WIRE", "ACH"], p=[0.4, 0.6])),
                   "status_lookup_code": "NEGOTIABLE", "_entity": r["_entity"]})
chk = frame(checks)
paid_ids = set(chk["invoice_id"].to_list())
inv = inv.with_columns(pl.when(pl.col("invoice_id").is_in(list(paid_ids))).then(pl.lit("Y")).otherwise(pl.lit("N"))
                       .alias("payment_status_flag"))

# COMMAND ----------
public_inv = inv.drop([c for c in inv.columns if c.startswith("_")])
n1 = write_by_month(public_inv, "gl_date", ORA, "ap_invoices_all", "csv")
n2 = write_by_month(chk.drop("_entity"), "check_date", ORA, "ap_checks_all", "csv")
write_scratch(inv, catalog, schema, raw_volume, "ap_invoices")
write_scratch(chk, catalog, schema, raw_volume, "ap_checks")
planted.save(spark, catalog, schema)
print(f"checks={chk.height} files invoices={n1} checks={n2}")
