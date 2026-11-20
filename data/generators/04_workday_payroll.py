# Databricks notebook source
# MAGIC %md
# MAGIC # 04: Workday payroll results
# MAGIC
# MAGIC `workday/payroll_results_<YYYY>M<MM>.parquet` (RaaS Title_Case columns).
# MAGIC
# MAGIC * Semi-monthly regular runs per company: the 15th and the last business day
# MAGIC   (moved back to the prior business day if needed). Active month: only runs
# MAGIC   on or before yesterday.
# MAGIC * Run totals are anchored: payroll = 58% of each opex function (R&D, S&M,
# MAGIC   G&A) and 50% of Services cost of revenue, x entity share. Workers are
# MAGIC   weights (salary), allocated within company x department.
# MAGIC * Planted (M2, SLR-03): an off-cycle bonus run in Workday that never reached
# MAGIC   the GL. Payroll cost in Workday exceeds GL payroll postings, and the bank
# MAGIC   still paid it (unmatched bank debit for M1).

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
WD = volume_dir(catalog, schema, raw_volume, "workday")
wipe_family(WD, "payroll_results")
planted = PlantedRegistry("04_workday_payroll")
rng = rng_for("workday")
targets = monthly_targets(read_scratch(catalog, schema, raw_volume, "anchors"))
workers = read_scratch(catalog, schema, raw_volume, "workers")
ent_mix = {e["code"]: e["mix"] for e in ENTITIES}
EMPLOYER_TAX = {"US": 0.0765, "CA": 0.07, "GB": 0.138, "IE": 0.11, "DE": 0.20, "SG": 0.17, "BR": 0.28}
DEPT_TARGET = {"RND": "rnd", "SNM": "snm", "GNA": "gna"}
PAYROLL_SHARE_SVC = 0.50


def pay_dates(y, m):
    out = []
    for d in (date(y, m, 15), month_end(y, m)):
        while not is_business_day(d):
            d -= timedelta(days=1)
        out.append(d)
    return out

# COMMAND ----------
consol = targets.filter(pl.col("segment_code") == "CONSOL")
svc = targets.filter(pl.col("segment_code") == "SVC")
results, run_index = [], []
for row in consol.iter_rows(named=True):
    y, m = int(row["fiscal_year"]), int(row["fiscal_month"])
    if row["status"] == "FUTURE":
        continue
    # Full-month payroll by department (USD), then split across the runs.
    month_full = {d: float(row[t]) * PAYROLL_SHARE_OF_OPEX for d, t in DEPT_TARGET.items()}
    svc_row = svc.filter(pl.col("period") == row["period"])
    month_full["SVC"] = float(svc_row["cost_of_revenue"][0]) * PAYROLL_SHARE_SVC if svc_row.height else 0.0
    runs = pay_dates(y, m)
    if (y, m) == (ay, am):
        # Active month targets are already prorated; rescale to a per-run amount.
        frac = elapsed_business_fraction(y, m, as_of)
        month_full = {d: (v / frac if frac > 0 else 0.0) for d, v in month_full.items()}
        runs = [d for d in runs if d <= cutoff]
    for run_date in runs:
        active = workers.filter((pl.col("Hire_Date") <= run_date)
                                & (pl.col("Termination_Date").is_null() | (pl.col("Termination_Date") > run_date)))
        for ent in ENTITY_CODES:
            e = ENTITY_BY_CODE[ent]
            rate = fx_rate(e["currency"], y, m)
            run_id = f"PR-{ent}-{run_date:%Y%m%d}"
            run_total_usd = 0.0
            for dept, full_usd in month_full.items():
                share_usd = full_usd * ent_mix[ent] / 2.0
                staff = active.filter((pl.col("Company") == ent) & (pl.col("Supervisory_Org") == dept))
                if staff.is_empty() or share_usd <= 0:
                    continue
                cost_fc = share_usd / rate                    # gross + employer taxes, functional currency
                tax_rate = EMPLOYER_TAX[e["country"]]
                gross_total = cost_fc / (1 + tax_rate)
                w = staff["Annual_Base_Salary"].to_numpy()
                gross = np.round(gross_total * w / w.sum(), 2)
                for wid, cc, g in zip(staff["Worker_ID"].to_list(), staff["Cost_Center"].to_list(), gross):
                    results.append({
                        "Payroll_Result_ID": f"PRR-{run_date:%Y%m%d}-{wid}", "Payroll_Run_ID": run_id,
                        "Worker_ID": wid, "Company": ent, "Cost_Center": cc, "Supervisory_Org": dept,
                        "Pay_Group": f"{ent} Semi-Monthly", "Run_Type": "Regular",
                        "Period_End_Date": run_date, "Payment_Date": run_date,
                        "Gross_Pay": float(g), "Employer_Taxes": float(round(g * tax_rate, 2)),
                        "Net_Pay": float(round(g * 0.71, 2)), "Employee_Deductions": float(round(g * 0.29, 2)),
                        "Currency": e["currency"],
                    })
                run_total_usd += share_usd
            run_index.append({"Payroll_Run_ID": run_id, "Company": ent, "Payment_Date": run_date,
                              "Run_Type": "Regular", "_gl_skip": False, "total_usd": run_total_usd})

# COMMAND ----------
# MAGIC %md ## Planted: off-cycle bonus runs not interfaced to the GL (SLR-03)

# COMMAND ----------
def plant_offcycle(ent, y, m, n_workers, disposition):
    bds = [d for d in business_days(y, m) if d <= cutoff]
    if len(bds) < 4:
        return
    aged = aged_business_days(bds, 6)
    run_date = aged[len(aged) // 2] if aged else bds[len(bds) // 2]
    e = ENTITY_BY_CODE[ent]
    run_id = f"PR-{ent}-{run_date:%Y%m%d}-OFF"
    staff = workers.filter((pl.col("Company") == ent) & (pl.col("Supervisory_Org") == "SNM")
                           & (pl.col("Hire_Date") <= run_date) & pl.col("Termination_Date").is_null()).head(n_workers)
    total_fc = 0.0
    for wid, cc in zip(staff["Worker_ID"].to_list(), staff["Cost_Center"].to_list()):
        g = float(round(rng.uniform(4000, 9000) / fx_rate(e["currency"], y, m), 2))
        t = round(g * EMPLOYER_TAX[e["country"]], 2)
        total_fc += g + t
        results.append({"Payroll_Result_ID": f"PRR-{run_date:%Y%m%d}-OFF-{wid}", "Payroll_Run_ID": run_id,
                        "Worker_ID": wid, "Company": ent, "Cost_Center": cc, "Supervisory_Org": "SNM",
                        "Pay_Group": f"{ent} Off-Cycle", "Run_Type": "Off-Cycle", "Period_End_Date": run_date,
                        "Payment_Date": run_date, "Gross_Pay": g, "Employer_Taxes": t,
                        "Net_Pay": float(round(g * 0.71, 2)), "Employee_Deductions": float(round(g * 0.29, 2)),
                        "Currency": e["currency"]})
    usd = total_fc * fx_rate(e["currency"], y, m)
    run_index.append({"Payroll_Run_ID": run_id, "Company": ent, "Payment_Date": run_date, "Run_Type": "Off-Cycle",
                      "_gl_skip": True, "total_usd": usd})
    planted.add("M2", "SLR-03", f"{ent}|{period_key(y, m)}", ent, period_key(y, m), usd,
                f"Off-cycle sales bonus run {run_id} ({staff.height} workers) paid from Workday but not interfaced to the GL",
                expected_disposition=disposition)


py, pm = (ay - 1, 12) if am == 1 else (ay, am - 1)
plant_offcycle("US01", py, pm, 12, "explained")
plant_offcycle("SG01", ay, am, 8, "open")

pr = frame(results)
n_files = write_by_month(pr, "Payment_Date", WD, "payroll_results", "parquet")
runs_df = frame(run_index)
write_scratch(pr, catalog, schema, raw_volume, "payroll_results")
write_scratch(runs_df, catalog, schema, raw_volume, "payroll_runs")
planted.save(spark, catalog, schema)
print(f"payroll results={pr.height} runs={runs_df.height} files={n_files}")
