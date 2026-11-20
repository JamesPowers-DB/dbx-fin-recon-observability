# Databricks notebook source
# MAGIC %md
# MAGIC # 08: Anaplan plan export (budget, forecast, phasing)
# MAGIC
# MAGIC `anaplan/plan_<version>.csv`: Version, Time ("Nov 26"), E1_Entity, G1_Account,
# MAGIC Currency (USD), Amount. Full-month values for P&L accounts by entity.
# MAGIC
# MAGIC Versions:
# MAGIC * `Budget FY25` covers 2025.
# MAGIC * `Budget FY26` covers 2026.
# MAGIC * `Forecast 3+9 FY26` covers April to December 2026.
# MAGIC
# MAGIC `anaplan/plan_phasing.csv` is the month-to-date phasing profile per account:
# MAGIC * `linear`: by business days.
# MAGIC * `payroll`: semi-monthly runs on the 15th and the last business day, blended
# MAGIC   with linear by `Payroll_Share`.
# MAGIC * `period_end`: depreciation and tax.
# MAGIC * `step_bd5`: interest.
# MAGIC
# MAGIC The live (active-month) flux review compares month-to-date actuals with the
# MAGIC phased budget, so payroll timing does not raise false variances.
# MAGIC
# MAGIC The budget is the anchored expectation x (1 + small noise). Planted (M5):
# MAGIC five budget misses in recent closed months. 09 explains four in history;
# MAGIC one stays unexplained (FPA-03) and one is acknowledged by its own author (FPA-04).

# COMMAND ----------
# MAGIC %run ./_lib

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
catalog, schema, raw_volume = get_widget("catalog"), get_widget("schema"), get_widget("raw_volume", "files")
as_of = load_as_of(catalog, schema, raw_volume)
ay, am = active_period(as_of)
AP_DIR = volume_dir(catalog, schema, raw_volume, "anaplan")
wipe_family(AP_DIR, "plan_")
planted = PlantedRegistry("08_anaplan_plan")
rng = rng_for("anaplan")
anchors = read_scratch(catalog, schema, raw_volume, "anchors")
q = anchors.filter(pl.col("period_type") == "Q")
MONTH_WEIGHTS = [0.31, 0.32, 0.37]
FSLI_OF = {row[0]: row[3] for row in COA}


def qval(fy, fq, seg, metric):
    r = q.filter((pl.col("fiscal_year") == fy) & (pl.col("fiscal_quarter") == fq) & (pl.col("segment_code") == seg)
                 & (pl.col("metric") == metric))
    return float(r["value_usd_m"][0]) * 1_000_000 if r.height else 0.0


def expected_month(fy, m):
    """Full-month expected P&L by account (consolidated USD) from the quarter anchors."""
    fq = (m - 1) // 3 + 1
    w = MONTH_WEIGHTS[(m - 1) % 3]
    rev = {s: qval(fy, fq, s, "revenue") * w for s in SEGMENT_CODES}
    cor = {s: qval(fy, fq, s, "cost_of_revenue") * w for s in SEGMENT_CODES}
    c = lambda metric: qval(fy, fq, "CONSOL", metric) * w   # noqa: E731
    return {"40000": rev["CLD"] + rev["ENT"], "41000": rev["DEV"], "42000": rev["SVC"],
            "50000": cor["CLD"] + cor["ENT"], "51000": cor["DEV"], "52000": cor["SVC"],
            "60000": c("rnd"), "61000": c("snm"), "62000": c("gna"), "64000": 12_800.0,
            "63000": c("dna"), "70000": c("interest"), "80000": c("tax")}

# COMMAND ----------
months = [(y, m) for y in (2025, 2026) for m in range(1, 13)]
months = [(y, m) for (y, m) in months if (y, (m - 1) // 3 + 1) <= (q["fiscal_year"].max(), 4)
          and q.filter((pl.col("fiscal_year") == y) & (pl.col("fiscal_quarter") == (m - 1) // 3 + 1)).height]

# Planted budget misses in the four closed months before the active one.
recent = []
y, m = ay, am
for _ in range(4):
    y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    recent.append((y, m))
recent = list(reversed(recent))   # oldest first: P-4, P-3, P-2, P-1
MISSES = [  # (month index into recent, entity, account, budget factor, history treatment)
    (0, "DE01", "61000", 1.18, "explained"),
    (1, "US01", "50000", 0.82, "explained"),
    (2, "SG01", "60000", 0.85, "self_acknowledged"),
    (3, "GB01", "62000", 0.80, "unexplained"),
    (3, "US02", "40000", 1.11, "explained"),
]
miss_map = {(recent[i][0], recent[i][1], ent, acct): (f, t) for i, ent, acct, f, t in MISSES}

rows, variance_plan = [], []
for (y, m) in months:
    exp = expected_month(y, m)
    for e in ENTITIES:
        ent = e["code"]
        for acct, cons in exp.items():
            if acct == "70000" and ent != "US01":
                continue
            actual_exp = cons if acct == "70000" else cons * e["mix"]
            base = actual_exp * (1 + rng.normal(0, 0.012))
            treat = miss_map.get((y, m, ent, acct))
            if treat:
                base = actual_exp * treat[0]
                variance_plan.append({"period": period_key(y, m), "entity_code": ent, "account": acct,
                                      "fsli_code": FSLI_OF[acct], "budget_factor": treat[0], "treatment": treat[1],
                                      "expected_actual_usd": actual_exp, "budget_usd": base})
            version = "Budget FY25" if y == 2025 else "Budget FY26"
            rows.append({"Version": version, "Time": date(y, m, 1).strftime("%b %y"), "E1_Entity": ent,
                         "G1_Account": acct, "Currency": "USD", "Amount": round(base, 2)})
            if y == 2026 and m >= 4:
                rows.append({"Version": "Forecast 3+9 FY26", "Time": date(y, m, 1).strftime("%b %y"), "E1_Entity": ent,
                             "G1_Account": acct, "Currency": "USD", "Amount": round(actual_exp * (1 + rng.normal(0, 0.008)), 2)})

plan = frame(rows)
for version, part in plan.group_by("Version"):
    write_csv(part, f"{AP_DIR}/plan_{version[0].replace(' ', '_').replace('+', 'p')}.csv")

PHASING = [  # G1_Account, Profile, Payroll_Share, Period_End_Share (posted at month end, e.g. prepaid amortization)
    ("40000", "linear", 0.0, 0.0), ("41000", "linear", 0.0, 0.0), ("42000", "linear", 0.0, 0.0),
    ("50000", "linear", 0.0, 0.0), ("51000", "linear", 0.0, 0.0), ("52000", "payroll", 0.50, 0.0),
    ("60000", "payroll", 0.58, 0.0), ("61000", "payroll", 0.58, 0.0), ("62000", "payroll", 0.55, 0.06),
    ("64000", "linear", 0.0, 0.0), ("63000", "period_end", 0.0, 1.0), ("70000", "step_bd5", 0.0, 0.0),
    ("80000", "period_end", 0.0, 1.0),
]
write_csv(frame([{"G1_Account": a, "Profile": p, "Payroll_Share": s, "Period_End_Share": pe} for a, p, s, pe in PHASING]),
          f"{AP_DIR}/plan_phasing.csv")

for v in variance_plan:
    if v["treatment"] == "unexplained":
        planted.add("M5", "FPA-03", f"{v['period']}|{v['entity_code']}|{v['fsli_code']}", v["entity_code"], v["period"],
                    abs(v["expected_actual_usd"] - v["budget_usd"]),
                    "Material budget variance closed without an explanation (close tool marked flux review complete)",
                    expected_disposition="open")
    if v["treatment"] == "self_acknowledged":
        planted.add("M5", "FPA-04", f"{v['period']}|{v['entity_code']}|{v['fsli_code']}", v["entity_code"], v["period"],
                    abs(v["expected_actual_usd"] - v["budget_usd"]),
                    "Variance explanation acknowledged by its own author (no independent review)",
                    expected_disposition="open")
write_scratch(frame(variance_plan), catalog, schema, raw_volume, "variance_plan")
planted.save(spark, catalog, schema)
print(f"plan rows={plan.height}, versions={plan['Version'].unique().to_list()}, planted misses={len(variance_plan)}")
