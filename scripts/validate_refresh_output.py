# Databricks notebook source
# MAGIC %md
# MAGIC # validate_refresh_output (last task of `refresh`)
# MAGIC
# MAGIC Fails the daily refresh when the continuous close would show stale or wrong numbers.
# MAGIC
# MAGIC Hard failures (raise):
# MAGIC * the GL fact is missing or empty, or has a row dated after today (as-of cap broken);
# MAGIC * no control run today, or the latest run's monitoring-integrity gate (PLT-01) did not pass;
# MAGIC * the active close has no close-task status rows, or they were not updated by today's run.
# MAGIC
# MAGIC Warnings: latest accounting date older than `freshness_window_days`.

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("fact_table", "gold_fact_gl_lines")
dbutils.widgets.text("date_col", "accounting_date")
dbutils.widgets.text("freshness_window_days", "5")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
assert catalog and schema, "catalog / schema must be set"
FQ = f"`{catalog}`.`{schema}`"
fact, date_col = f"{FQ}.{dbutils.widgets.get('fact_table')}", dbutils.widgets.get("date_col")
fresh_days = int(dbutils.widgets.get("freshness_window_days"))
failures, warnings = [], []

# COMMAND ----------
try:
    f = spark.sql(f"""SELECT count(*) AS n, max({date_col}) AS max_dt, datediff(current_date(), max({date_col})) AS behind,
                             sum(CASE WHEN {date_col} > current_date() THEN 1 ELSE 0 END) AS future_rows
                      FROM {fact}""").collect()[0]
except Exception as e:  # noqa: BLE001
    raise AssertionError(f"HARD FAIL: cannot read {fact}; the pipeline did not build gold. ({e})")
print(f"{fact}: {f['n']} rows, latest {date_col} {f['max_dt']} ({f['behind']} days behind), future rows {f['future_rows']}")
if not f["n"]:
    failures.append(f"{fact} is empty")
if f["future_rows"]:
    failures.append(f"{f['future_rows']} rows in {fact} are dated after today")
if f["behind"] is not None and f["behind"] > fresh_days:
    warnings.append(f"latest {date_col} is {f['behind']} days old (window {fresh_days})")

# COMMAND ----------
run = spark.sql(f"""SELECT job_run_id, started_at, status, gate_result, gate_detail, active_period, trigger_source
                    FROM {FQ}.meta_control_runs ORDER BY started_at DESC LIMIT 1""").collect()
if not run:
    failures.append("no control run recorded")
else:
    r = run[0]
    print(f"latest control run {r['job_run_id']} ({r['trigger_source']}) at {r['started_at']}: {r['status']}, gate {r['gate_result']}")
    if r["started_at"] is None or r["started_at"].date() < spark.sql("SELECT current_date() AS d").collect()[0]["d"]:
        failures.append(f"latest control run {r['job_run_id']} did not run today")
    if r["gate_result"] != "PASS":
        failures.append(f"PLT-01 gate {r['gate_result']}: {(r['gate_detail'] or '')[:300]}")

# COMMAND ----------
cts = spark.sql(f"""SELECT count(*) AS n, max(updated_at) AS updated, max(last_job_run_id) AS run,
                           sum(CASE WHEN status = 'COMPLETE' THEN 1 ELSE 0 END) AS complete,
                           max(projected_close_day) FILTER (WHERE task_code = 'CLS-12') AS projected
                    FROM {FQ}.meta_close_task_status WHERE period = date_format(current_date(), 'yyyy-MM')""").collect()[0]
print(f"active close: {cts['n']} tasks, {cts['complete']} complete, projected T+{cts['projected']}, from run {cts['run']}")
if not cts["n"]:
    failures.append("no close-task status for the active close")
elif run and cts["run"] != run[0]["job_run_id"]:
    failures.append(f"close status is from run {cts['run']}, not the latest run {run[0]['job_run_id']}")

# COMMAND ----------
for w_ in warnings:
    print("WARNING:", w_)
if failures:
    raise AssertionError("Refresh validation failed: " + "; ".join(failures))
print("refresh output valid")
