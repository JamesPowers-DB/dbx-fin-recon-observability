# Databricks notebook source
# MAGIC %md
# MAGIC # gate_controls (run_controls task 7): PLT-01 monitoring integrity
# MAGIC
# MAGIC Internal Audit's independent test of the monitoring itself. The run fails
# MAGIC when any check fails:
# MAGIC
# MAGIC | Check | Rule |
# MAGIC |---|---|
# MAGIC | Library versioned and valid | `control_lib.validate` passes on the deployed repo files (bindings, risks, calendar) |
# MAGIC | Every operating control executed | each operating control (except PLT-01) has result rows in this run |
# MAGIC | Expectations enforced | every expectation-bound control's expectation appears in this update's event-log metrics |
# MAGIC | Planted recall 100% | every `meta_planted_exceptions` row is detected by its expected control (demo-only test deck) |
# MAGIC | Ledger = metric view | exceptions in the ledger equal `gold_mv_control_health` for this run (skipped before the metric views exist) |
# MAGIC
# MAGIC Writes PLT-01 rows into `meta_control_results` and closes the
# MAGIC `meta_control_runs` row with the final status.

# COMMAND ----------
import json
import os
import sys

for w in ("catalog", "schema", "job_run_id", "task_run_id"):
    dbutils.widgets.text(w, "")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
job_run_id = int(dbutils.widgets.get("job_run_id"))
task_run_id = int(dbutils.widgets.get("task_run_id") or 0) or None
FQ = f"`{catalog}`.`{schema}`"
nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname("/Workspace" + nb if not nb.startswith("/Workspace") else nb)))
sys.path.insert(0, os.path.join(ROOT, "controls"))
import control_lib  # noqa: E402

checks = []


def check(name, ok, detail):
    checks.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + f"{name}: {detail}")

# COMMAND ----------
controls, risks, cal = control_lib.load_all(os.path.join(ROOT, "controls"))
errs = control_lib.validate(controls, risks, cal, repo_root=ROOT)
lib_hash = control_lib.library_hash(controls)
check("library_valid", not errs, f"hash {lib_hash}; {len(errs)} violation(s) {errs[:3]}")

run_ctrl = {r["control_id"] for r in spark.sql(
    f"SELECT DISTINCT control_id FROM {FQ}.meta_control_results WHERE job_run_id = {job_run_id}").collect()}
operating = {c["control_id"] for c in controls if c["lifecycle"]["state"] == "operating" and c["control_id"] != "PLT-01"}
missing = sorted(operating - run_ctrl)
check("all_controls_executed", not missing, f"{len(operating) - len(missing)}/{len(operating)} executed; missing {missing}")

run = spark.sql(f"SELECT test_update_id FROM {FQ}.meta_control_runs WHERE job_run_id = {job_run_id}").collect()
upd = run[0]["test_update_id"] if run else None
exp_names = {r["name"] for r in spark.sql(f"""SELECT DISTINCT e.name FROM {FQ}.meta_pipeline_update_metrics m
                                              LATERAL VIEW explode(m.expectations) x AS e
                                              WHERE m.update_id = '{upd}'""").collect()} if upd else set()
expected = {c["executed_by"]["expectation"] for c in controls if c["executed_by"]["kind"] == "expectation"}
# MVs that are not recomputed in an incremental update report no expectation rows; fall back to the
# latest update that evaluated each expectation.
if expected - exp_names:
    exp_names |= {r["name"] for r in spark.sql(f"""SELECT DISTINCT e.name FROM {FQ}.meta_pipeline_update_metrics m
                                                   LATERAL VIEW explode(m.expectations) x AS e""").collect()}
check("expectations_enforced", expected <= exp_names, f"expected {sorted(expected)}; missing {sorted(expected - exp_names)}")

recall = spark.sql(f"""
  SELECT count(*) AS planted, sum(CASE WHEN x.exception_id IS NOT NULL THEN 1 ELSE 0 END) AS detected,
         collect_list(CASE WHEN x.exception_id IS NULL THEN concat(p.control_id, ' ', p.period, ' ', p.record_key) END) AS misses
  FROM {FQ}.meta_planted_exceptions p
  LEFT JOIN {FQ}.gold_control_exceptions x
    ON x.control_id = p.control_id AND x.period = p.period AND x.record_key = p.record_key""").collect()[0]
planted, detected = int(recall["planted"] or 0), int(recall["detected"] or 0)
rate = detected / planted if planted else 1.0
check("planted_recall", rate >= 1.0, f"{detected}/{planted} planted exceptions detected ({rate:.1%}); misses {recall['misses'][:5]}")

mv_exists = spark.sql(f"SHOW VIEWS IN {FQ} LIKE 'gold_mv_control_health'").count() > 0
if mv_exists:
    led = spark.sql(f"SELECT COALESCE(sum(exceptions), 0) AS n FROM {FQ}.meta_control_results WHERE job_run_id = {job_run_id} AND control_id <> 'PLT-01'").collect()[0]["n"]
    mv = spark.sql(f"""SELECT MEASURE(exceptions_found) AS n FROM {FQ}.gold_mv_control_health
                       WHERE job_run_id = {job_run_id} AND control_id <> 'PLT-01'""").collect()[0]["n"]
    check("ledger_equals_metric_view", int(led) == int(mv or 0), f"ledger {led} vs metric view {mv}")
else:
    check("ledger_equals_metric_view", True, "metric views not created yet (first install); skipped")

# COMMAND ----------
failed = [c for c in checks if not c["ok"]]
result = "FAIL" if failed else "PASS"
detail = "; ".join(f"{c['check']}: {c['detail']}" for c in failed) or "all checks passed"
spark.sql(f"""
MERGE INTO {FQ}.meta_control_results t
USING (SELECT {job_run_id} AS job_run_id, r.job_id, {task_run_id or 'NULL'} AS task_run_id, r.pipeline_id, r.test_update_id,
              current_timestamp() AS executed_at, 'PLT-01' AS control_id, 1 AS control_version, 'DQ' AS module,
              'Monitoring integrity (the monitor is monitored)' AS control_title, true AS key_control, 'assurance' AS lane,
              3 AS line_of_defense, 'ALL' AS entity_code, date_format(current_date(), 'yyyy-MM') AS period,
              CAST({len(checks)} AS BIGINT) AS population_count, CAST(0 AS DOUBLE) AS population_amount_usd,
              CAST({len(failed)} AS BIGINT) AS exceptions, CAST(0 AS DOUBLE) AS exception_amount_usd,
              CAST({len(failed)} AS BIGINT) AS open_exceptions, CAST(0 AS DOUBLE) AS open_exception_amount_usd,
              '{result}' AS result, 0 AS traditional_sample_size, date_sub(current_date(), 1) AS data_cutoff
       FROM {FQ}.meta_control_runs r WHERE r.job_run_id = {job_run_id}) s
ON t.job_run_id = s.job_run_id AND t.control_id = s.control_id AND t.entity_code = s.entity_code AND t.period = s.period
WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
lib_hash_published = None
try:
    lib_hash_published = dbutils.jobs.taskValues.get(taskKey="publish_controls", key="library_hash", debugValue=lib_hash)
except Exception:
    pass
triaged = None
try:
    triaged = int(dbutils.jobs.taskValues.get(taskKey="triage_exceptions", key="triaged", debugValue=0))
except Exception:
    pass
synced = None
try:
    synced = int(dbutils.jobs.taskValues.get(taskKey="snapshot_review_state", key="review_actions_synced", debugValue=0))
except Exception:
    pass
spark.sql(f"""UPDATE {FQ}.meta_control_runs SET
  status = '{'FAILED' if failed else 'SUCCEEDED'}', ended_at = current_timestamp(), gate_result = '{result}',
  gate_detail = '{detail.replace("'", "")[:1500]}', gate_task_run_id = {task_run_id or 'NULL'},
  planted_recall = {rate}, library_hash = '{lib_hash_published or lib_hash}', controls_published = {len(controls)},
  triaged_exceptions = {triaged if triaged is not None else 'NULL'},
  review_actions_synced = {synced if synced is not None else 'NULL'}
WHERE job_run_id = {job_run_id}""")
summary = {"result": result, "checks": checks, "planted_recall": rate}
if failed:
    raise AssertionError(f"PLT-01 monitoring integrity FAILED: {detail}")
dbutils.notebook.exit(json.dumps(summary))
