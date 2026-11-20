# Databricks notebook source
# MAGIC %md
# MAGIC # 01: seed `meta_dim_period_anchors`
# MAGIC
# MAGIC Hand-curated consolidated quarters for Corvane Technologies (fictional),
# MAGIC shaped like a large-cap software/cloud 10-K and scaled to about $4B revenue.
# MAGIC The issuer is never named. Two grains in one table:
# MAGIC
# MAGIC * `period_type = 'Q'`: quarterly anchors per segment (revenue, cost of revenue)
# MAGIC   plus consolidated opex, D&A, interest, and tax (segment_code = CONSOL).
# MAGIC * `period_type = 'M'`: monthly targets derived from the quarter with a
# MAGIC   quarter-end-heavy weighting. The active month is prorated by elapsed
# MAGIC   business days (data runs through yesterday), so nothing is future-dated.
# MAGIC
# MAGIC Quarters after the last curated one are projected (same quarter last year
# MAGIC x growth) and tagged PROJECTED. Add a tuple to extend.

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
assert catalog and schema
FQ = f"`{catalog}`.`{schema}`"

# COMMAND ----------
# (fy, fq, revenue, cost_of_revenue, rnd, snm, gna, dna, interest, status)  USD millions
CONSOL_QUARTERS = [
    (2025, 1,  902.0, 271.0, 186.0, 214.0, 82.0, 27.0, 4.6, "ACTUAL"),
    (2025, 2,  960.0, 287.0, 195.0, 224.0, 85.0, 28.0, 4.6, "ACTUAL"),
    (2025, 3,  980.0, 292.0, 199.0, 228.0, 86.0, 28.5, 4.5, "ACTUAL"),
    (2025, 4, 1078.0, 321.0, 212.0, 258.0, 93.0, 29.5, 4.5, "ACTUAL"),
    (2026, 1, 1010.0, 300.0, 207.0, 236.0, 88.0, 30.0, 4.4, "ACTUAL"),
    (2026, 2, 1075.0, 318.0, 219.0, 248.0, 92.0, 30.5, 4.4, "ACTUAL"),
    (2026, 3, 1098.0, 324.0, 223.0, 251.0, 93.0, 31.0, 4.3, "ACTUAL"),
]
TAX_RATE = 0.21
YOY_GROWTH = 1.12
MONTH_WEIGHTS = [0.31, 0.32, 0.37]   # quarter-end heavy

# COMMAND ----------
as_of = generation_as_of()
cy, cq = as_of.year, (as_of.month - 1) // 3 + 1
by_q = {(r[0], r[1]): r for r in CONSOL_QUARTERS}
fy, fq = max(by_q)
while True:
    fq += 1
    if fq == 5:
        fy, fq = fy + 1, 1
    if (fy, fq) > (cy, cq):
        break
    base = by_q[(fy - 1, fq)]
    by_q[(fy, fq)] = (fy, fq, *[round(v * YOY_GROWTH, 1) for v in base[2:9]], "PROJECTED")
quarters = [by_q[k] for k in sorted(by_q)]
print(f"as_of={as_of}; quarters={len(quarters)} (last {quarters[-1][0]}Q{quarters[-1][1]} {quarters[-1][-1]})")

# COMMAND ----------
METRICS = ["revenue", "cost_of_revenue", "rnd", "snm", "gna", "dna", "interest"]
rows = []
for (fy_, fq_, rev, cor, rnd, snm, gna, dna, intr, status) in quarters:
    vals = dict(zip(METRICS, [rev, cor, rnd, snm, gna, dna, intr]))
    pretax = rev - cor - rnd - snm - gna - dna - intr
    vals["tax"] = round(pretax * TAX_RATE, 2)
    months = [(fy_, (fq_ - 1) * 3 + i + 1) for i in range(3)]
    # Quarter rows: segment split of revenue and cost of revenue; opex stays consolidated.
    for metric, v in vals.items():
        rows.append(dict(period_type="Q", fiscal_year=fy_, fiscal_quarter=fq_, fiscal_month=None,
                         period=f"{fy_}Q{fq_}", segment_code="CONSOL", metric=metric,
                         value_usd_m=round(v, 3), status=status))
    for s in SEGMENTS:
        for metric in ("revenue", "cost_of_revenue"):
            rows.append(dict(period_type="Q", fiscal_year=fy_, fiscal_quarter=fq_, fiscal_month=None,
                             period=f"{fy_}Q{fq_}", segment_code=s["code"], metric=metric,
                             value_usd_m=round(vals[metric] * s["mix"], 3), status=status))
    # Month rows: weighted split; active month prorated by elapsed business days; future = 0.
    for (y, m), w in zip(months, MONTH_WEIGHTS):
        if (y, m) > (as_of.year, as_of.month):
            factor, mstatus = 0.0, "FUTURE"
        elif (y, m) == (as_of.year, as_of.month):
            factor, mstatus = elapsed_business_fraction(y, m, as_of), "IN_PROGRESS"
        else:
            factor, mstatus = 1.0, "CLOSED" if status == "ACTUAL" or (y, m) < (as_of.year, as_of.month) else status
        for metric, v in vals.items():
            rows.append(dict(period_type="M", fiscal_year=y, fiscal_quarter=fq_, fiscal_month=m,
                             period=period_key(y, m), segment_code="CONSOL", metric=metric,
                             value_usd_m=round(v * w * factor, 4), status=mstatus))
        for s in SEGMENTS:
            for metric in ("revenue", "cost_of_revenue"):
                rows.append(dict(period_type="M", fiscal_year=y, fiscal_quarter=fq_, fiscal_month=m,
                                 period=period_key(y, m), segment_code=s["code"], metric=metric,
                                 value_usd_m=round(vals[metric] * s["mix"] * w * factor, 4), status=mstatus))

anchors = pl.DataFrame(rows, schema={"period_type": pl.Utf8, "fiscal_year": pl.Int32, "fiscal_quarter": pl.Int32,
                                     "fiscal_month": pl.Int32, "period": pl.Utf8, "segment_code": pl.Utf8,
                                     "metric": pl.Utf8, "value_usd_m": pl.Float64, "status": pl.Utf8})
anchors = anchors.with_columns(pl.lit(as_of).alias("generated_as_of"))
write_delta(spark, anchors, f"{FQ}.meta_dim_period_anchors")
spark.sql(f"""COMMENT ON TABLE {FQ}.meta_dim_period_anchors IS
  'Generator anchors for Corvane Technologies (fictional). Q rows: hand-curated quarterly totals (USD millions), segment split for revenue and cost of revenue. M rows: monthly targets; IN_PROGRESS month prorated by elapsed business days, FUTURE months zero. Read by generators and the reconciliation gate. Not a source system.'""")
print(anchors.filter(pl.col("period_type") == "M").group_by("status").len())

# COMMAND ----------
# Scratch hand-off for downstream generators (they run without Spark reads).
write_scratch(anchors, catalog, schema, raw_volume, "anchors")
os.makedirs(scratch_dir(catalog, schema, raw_volume), exist_ok=True)
with open(os.path.join(scratch_dir(catalog, schema, raw_volume), "as_of.json"), "w") as f:
    json.dump({"as_of": as_of.isoformat(), "active_period": period_key(as_of.year, as_of.month)}, f)
print("anchors written")

# COMMAND ----------
# A regeneration starts a clean source set: intraday batches appended by
# simulate_activity are wiped with their families, so their planted items
# leave the ground-truth registry too (each other generator replaces its own).
if spark.catalog.tableExists(f"{catalog}.{schema}.meta_planted_exceptions"):
    spark.sql(f"DELETE FROM {FQ}.meta_planted_exceptions WHERE generator = '40_simulate_activity'")
