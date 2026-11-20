# Databricks notebook source
# MAGIC %md
# MAGIC # 03: Salesforce Billing (AR subledger)
# MAGIC
# MAGIC `salesforce/blng__Invoice__c_<YYYY>M<MM>.json` and
# MAGIC `salesforce/blng__Payment__c_<YYYY>M<MM>.json` (JSON lines, native API names).
# MAGIC
# MAGIC * Invoices are anchored to monthly segment revenue x entity mix, in the entity's
# MAGIC   functional currency. Revenue is recognized at invoice (no deferral in v1).
# MAGIC * Collections follow terms (30/45/60) plus noise; about 2% stay unpaid.
# MAGIC * Opening AR at 2024-12-31 exists as subledger invoices dated December 2024
# MAGIC   (`Corvane_Opening_Balance__c = true`), carried in the GL opening journal.
# MAGIC * Planted (M2): invoices posted in Salesforce but never interfaced to the GL
# MAGIC   (SLR-02 subledger-to-GL break). Planted (DQ-02): schema drift, a new field in
# MAGIC   the active month's payment feed.
# MAGIC
# MAGIC Hand-off for 06_oracle_gl and 07_bank: `_generator/sf_invoices`, `_generator/sf_payments`.

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
SF = volume_dir(catalog, schema, raw_volume, "salesforce")
for p in ("blng__Invoice__c", "blng__Payment__c"):
    wipe_family(SF, p)
planted = PlantedRegistry("03_salesforce_billing")
rng = rng_for("salesforce")
targets = monthly_targets(read_scratch(catalog, schema, raw_volume, "anchors"))
customers = read_scratch(catalog, schema, raw_volume, "customers")
cust_by_ent = {e: customers.filter(pl.col("Corvane_Entity__c") == e)["Id"].to_list() for e in ENTITY_CODES}
ent_mix = {e["code"]: e["mix"] for e in ENTITIES}
AVG_INVOICE_USD = {"CLD": 280_000, "ENT": 350_000, "DEV": 95_000, "SVC": 125_000}

# COMMAND ----------
invoices, seq = [], 0


def new_invoice(ent, seg, inv_date, amount_fc, opening=False):
    global seq
    seq += 1
    ccy = ENTITY_BY_CODE[ent]["currency"]
    terms = int(rng.choice([30, 45, 60], p=[0.55, 0.30, 0.15]))
    return {
        "Id": "a0B" + stable_id("inv", seq)[:15],
        "Name": f"INV-{ent}-{inv_date:%Y%m}-{seq:06d}",
        "blng__Account__c": str(rng.choice(cust_by_ent[ent] or customers["Id"].to_list())),
        "blng__InvoiceDate__c": inv_date, "blng__DueDate__c": inv_date + timedelta(days=terms),
        "blng__TotalAmount__c": float(amount_fc), "CurrencyIsoCode": ccy,
        "blng__InvoiceStatus__c": "Posted", "Corvane_Entity__c": ent, "Corvane_Segment__c": seg,
        "Corvane_Opening_Balance__c": opening, "_gl_skip": False,
    }


# Opening AR (subledger only; the GL carries it in the opening balance journal).
open_ar_usd = OPENING_BS_USD_M["11000"] * 1_000_000
for e in ENTITIES:
    usd = open_ar_usd * e["mix"]
    fc_total = usd / fx_rate(e["currency"], 2024, 12) if e["currency"] != "USD" else usd
    n = max(5, int(usd / 300_000))
    for amt, d in zip(renormalize(rng, n, round(fc_total, 2)), pick_dates(rng, business_days(2024, 12), n)):
        invoices.append(new_invoice(e["code"], str(rng.choice(SEGMENT_CODES, p=[s["mix"] for s in SEGMENTS])), d,
                                    amt, opening=True))

# Monthly invoicing anchored to revenue targets.
for row in targets.filter(pl.col("segment_code") != "CONSOL").iter_rows(named=True):
    y, m, seg = int(row["fiscal_year"]), int(row["fiscal_month"]), row["segment_code"]
    rev_usd = float(row["revenue"])
    if rev_usd <= 0:
        continue
    days = [d for d in business_days(y, m) if d <= cutoff]
    for ent in ENTITY_CODES:
        usd = rev_usd * ent_mix[ent]
        rate = fx_rate(ENTITY_BY_CODE[ent]["currency"], y, m)
        fc_total = round(usd / rate, 2)
        n = max(2, int(round(usd / AVG_INVOICE_USD[seg])))
        for amt, d in zip(renormalize(rng, n, fc_total, sigma=0.8), pick_dates(rng, days, n)):
            invoices.append(new_invoice(ent, seg, d, amt))

inv = frame(invoices).sort(["blng__InvoiceDate__c", "Name"])
print(f"invoices={inv.height}")

# COMMAND ----------
# MAGIC %md ## Planted: Salesforce invoices not interfaced to Oracle GL (SLR-02)

# COMMAND ----------
def plant_unposted(y, m, ent, n_invoices, disposition):
    global inv
    cand = inv.filter((pl.col("Corvane_Entity__c") == ent) & (pl.col("blng__InvoiceDate__c").dt.year() == y)
                      & (pl.col("blng__InvoiceDate__c").dt.month() == m) & ~pl.col("Corvane_Opening_Balance__c")
                      & pl.col("Corvane_Segment__c").is_in(["CLD", "ENT"]))   # large revenue line: break, not a flux trigger
    pick = cand.sort("blng__InvoiceDate__c", descending=True).head(n_invoices)["Id"].to_list()
    inv = inv.with_columns(pl.when(pl.col("Id").is_in(pick)).then(True).otherwise(pl.col("_gl_skip")).alias("_gl_skip"))
    amt_fc = float(cand.filter(pl.col("Id").is_in(pick))["blng__TotalAmount__c"].sum())
    usd = amt_fc * fx_rate(ENTITY_BY_CODE[ent]["currency"], y, m)
    planted.add("M2", "SLR-02", f"{ent}|{period_key(y, m)}", ent, period_key(y, m), usd,
                f"{len(pick)} Salesforce invoice(s) posted but not interfaced to the GL (Receivables): AR subledger exceeds GL",
                expected_disposition=disposition)
    return pick


py, pm = (ay - 1, 12) if am == 1 else (ay, am - 1)
plant_unposted(py, pm, "DE01", 2, "explained")        # prior close: interface failed, re-interfaced on T+2 (cut-off timing)
active_unposted = plant_unposted(ay, am, "GB01", 3, "open")

# COMMAND ----------
# MAGIC %md ## Collections

# COMMAND ----------
pays, pseq = [], 0
for r in inv.iter_rows(named=True):
    if rng.random() < 0.02 and not r["Corvane_Opening_Balance__c"]:
        continue                                          # stays unpaid (aging)
    delay = int(round(rng.normal(4, 9)))
    pdate = max(r["blng__InvoiceDate__c"] + timedelta(days=5), r["blng__DueDate__c"] + timedelta(days=delay))
    if r["Corvane_Opening_Balance__c"]:
        pdate = max(pdate, date(2025, 1, 2))          # opening AR is collected after the opening balance date
    while not is_business_day(pdate):
        pdate += timedelta(days=1)
    if pdate > cutoff:
        continue
    pseq += 1
    pays.append({
        "Id": "a0P" + stable_id("pay", pseq)[:15], "Name": f"PMT-{pseq:07d}", "blng__Invoice__c": r["Id"],
        "blng__Account__c": r["blng__Account__c"], "blng__Amount__c": r["blng__TotalAmount__c"],
        "blng__PaymentDate__c": pdate, "blng__PaymentType__c": str(rng.choice(["Wire", "ACH"], p=[0.6, 0.4])),
        "blng__Status__c": "Posted", "CurrencyIsoCode": r["CurrencyIsoCode"], "Corvane_Entity__c": r["Corvane_Entity__c"],
        "Bank_Reference__c": f"SFP-{pseq:07d}",
    })
pay = frame(pays).sort("blng__PaymentDate__c")
paid = pay.group_by("blng__Invoice__c").agg(pl.col("blng__Amount__c").sum().alias("_paid"))
inv = (inv.join(paid, left_on="Id", right_on="blng__Invoice__c", how="left")
          .with_columns((pl.col("blng__TotalAmount__c") - pl.col("_paid").fill_null(0)).round(2).alias("blng__Balance__c"),
                        pl.lit(f"{cutoff}T23:30:00.000+0000").alias("LastModifiedDate"))
          .drop("_paid"))
print(f"payments={pay.height}, open invoices={inv.filter(pl.col('blng__Balance__c') > 0).height}")

# COMMAND ----------
# MAGIC %md ## Write files (+ DQ-02 schema drift in the active month's payments)

# COMMAND ----------
def dates_to_str(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns([pl.col(c).cast(pl.Utf8) for c, t in df.schema.items() if t == pl.Date])

n_inv = write_by_month(inv.drop("_gl_skip"), "blng__InvoiceDate__c", SF, "blng__Invoice__c", "json")
in_active = (pl.col("blng__PaymentDate__c").dt.year() == ay) & (pl.col("blng__PaymentDate__c").dt.month() == am)
n_pay = write_by_month(pay.filter(~in_active), "blng__PaymentDate__c", SF, "blng__Payment__c", "json")
act = dates_to_str(pay.filter(in_active))
# Active month: an admin added a field mid-month; later records carry it (rescued in bronze).
drift_from = act.height // 2
act_rows = act.to_dicts()
for r in act_rows[drift_from:]:
    r["Payment_Method_Detail__c"] = "Instant payment rail"
os.makedirs(SF, exist_ok=True)
drift_file = month_file("blng__Payment__c", ay, am, "json")
with open(f"{SF}/{drift_file}", "w") as f:
    for r in act_rows:
        f.write(json.dumps(r) + "\n")
if act_rows[drift_from:]:
    planted.add("DQ", "DQ-02", f"bronze_sfdc_blng__payment__c|{drift_file}", "ALL", ACTIVE, 0.0,
                "Schema drift: Salesforce payments feed started sending a new field (Payment_Method_Detail__c); rows land in _rescued_data",
                expected_disposition="open")
print(f"files: invoices={n_inv} payments={n_pay + 1}")

# COMMAND ----------
write_scratch(inv, catalog, schema, raw_volume, "sf_invoices")
write_scratch(pay, catalog, schema, raw_volume, "sf_payments")
planted.save(spark, catalog, schema)
