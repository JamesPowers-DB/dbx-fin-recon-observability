# Databricks notebook source
# MAGIC %md
# MAGIC # record_results (run_controls task 5): the checklist updates here
# MAGIC
# MAGIC 1. **Resolve the pipeline update** that tested the controls. The event log's
# MAGIC    `create_update` event carries `job_task.run_id`, the run id of the
# MAGIC    `test_update` task.
# MAGIC 2. **Observability.** Per-dataset metrics for that update go to
# MAGIC    `meta_pipeline_update_metrics`: current row count, rows written, duration,
# MAGIC    expectations passed and failed, and lineage inputs. Domain and layer come
# MAGIC    from parsing the pipeline's own SQL files.
# MAGIC 3. **Results ledger.** An immutable snapshot of `gold_control_results` goes to
# MAGIC    `meta_control_results`, stamped with job, task, and pipeline-update ids.
# MAGIC 4. **Exception log.** NEW, RECURRING, and RESOLVED versus the previous run
# MAGIC    go to `meta_control_exception_log`.
# MAGIC 5. **Close tasks.** `meta_close_task_status` gets closed periods from the
# MAGIC    close-tool history. For the active period, a task completes when its
# MAGIC    controls are green and its sign-off exists. It reopens when its controls
# MAGIC    fail again. The task also projects days to close.
# MAGIC 6. **Run ledger.** Updates the `meta_control_runs` row.
# MAGIC
# MAGIC Every write MERGEs on run-scoped keys, so a repaired run is safe.

# COMMAND ----------
import json
import os
import re
from datetime import datetime, timezone

for w in ("catalog", "schema", "job_id", "job_run_id", "task_run_id", "test_update_task_run_id", "pipeline_id"):
    dbutils.widgets.text(w, "")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
job_id = int(dbutils.widgets.get("job_id") or 0) or None
job_run_id = int(dbutils.widgets.get("job_run_id"))
dbutils.widgets.text("rebaseline", "false")
rebaseline = dbutils.widgets.get("rebaseline").strip().lower() == "true"
task_run_id = int(dbutils.widgets.get("task_run_id") or 0) or None
test_task_run_id = dbutils.widgets.get("test_update_task_run_id")
pipeline_id = dbutils.widgets.get("pipeline_id")
FQ = f"`{catalog}`.`{schema}`"
nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname("/Workspace" + nb if not nb.startswith("/Workspace") else nb)))
now = datetime.now(timezone.utc).replace(tzinfo=None)   # Spark returns naive UTC timestamps

# COMMAND ----------
# MAGIC %md ## 1. Which pipeline update tested the controls

# COMMAND ----------
EL = f"{FQ}.meta_pipeline_event_log"
upd = spark.sql(f"""
  SELECT origin.update_id AS update_id, timestamp FROM {EL}
  WHERE event_type = 'create_update' AND details:create_update.job_task.run_id::string = '{test_task_run_id}'
  ORDER BY timestamp DESC LIMIT 1""").collect()
method = "event_log.job_task"
if not upd:
    upd = spark.sql(f"""SELECT origin.update_id AS update_id, timestamp FROM {EL} WHERE event_type = 'create_update'
                        ORDER BY timestamp DESC LIMIT 1""").collect()
    method = "latest_update_fallback"
test_update_id = upd[0]["update_id"] if upd else None
print(f"test update: {test_update_id} (resolved via {method})")

# COMMAND ----------
# MAGIC %md ## 2. Pipeline observability for this update

# COMMAND ----------
import yaml

with open(os.path.join(ROOT, "resources", "pipeline.yml")) as f:
    libs = yaml.safe_load(f)["resources"]["pipelines"]["lakehouse"]["libraries"]
ds_map = {}
for lib in libs:
    rel = lib["file"]["path"].replace("../", "")
    parts = rel.split("/")
    domain, layer = parts[1], parts[2]
    text = open(os.path.join(ROOT, rel)).read()
    for kind, name in re.findall(r"CREATE OR REFRESH (STREAMING TABLE|MATERIALIZED VIEW) \$\{schema\}\.(\w+)", text):
        ds_map[name] = {"domain": domain, "layer": layer, "file": rel,
                        "kind": "streaming_table" if kind.startswith("STREAMING") else "materialized_view"}
spark.createDataFrame([{"dataset": k, **v} for k, v in ds_map.items()]).createOrReplaceTempView("ds_map")
counts_sql = " UNION ALL ".join(f"SELECT '{d}' AS dataset, count(*) AS n FROM {FQ}.`{d}`" for d in sorted(ds_map))
spark.sql(counts_sql).createOrReplaceTempView("ds_counts")

spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.meta_pipeline_update_metrics (
  update_id STRING, job_run_id BIGINT, dataset STRING, domain STRING, layer STRING, dataset_kind STRING, source_file STRING,
  input_datasets ARRAY<STRING>, rows_in_table BIGINT, rows_written BIGINT, duration_s DOUBLE,
  expectations ARRAY<STRUCT<name: STRING, passed: BIGINT, failed: BIGINT>>, passed_records BIGINT, failed_records BIGINT,
  status STRING, recorded_at TIMESTAMP)
  COMMENT 'Pipeline observability per update x dataset (copied from the published event log by run_controls.record_results): row counts, rows written, duration, expectation pass/fail, lineage inputs. Feeds the data-quality Sankey. Writer: record_results.'""")
if test_update_id:
    spark.sql(f"""
    WITH ev AS (SELECT * FROM {EL} WHERE origin.update_id = '{test_update_id}'),
    defs AS (
      SELECT element_at(split(details:flow_definition.output_dataset::string, '\\\\.'), -1) AS dataset,
             transform(from_json(details:flow_definition.input_datasets::string, 'array<string>'), x -> element_at(split(x, '\\\\.'), -1)) AS input_datasets
      FROM ev WHERE event_type = 'flow_definition'),
    prog AS (
      SELECT element_at(split(origin.flow_name, '\\\\.'), -1) AS dataset,
             sum(COALESCE(details:flow_progress.metrics.num_output_rows::bigint, 0)) AS rows_written,
             (max(CASE WHEN details:flow_progress.status::string = 'COMPLETED' THEN unix_millis(timestamp) END)
              - min(CASE WHEN details:flow_progress.status::string IN ('STARTING', 'RUNNING', 'PLANNING') THEN unix_millis(timestamp) END)) / 1000.0 AS duration_s,
             max_by(details:flow_progress.status::string, timestamp) AS status
      FROM ev WHERE event_type = 'flow_progress' GROUP BY 1),
    exp AS (
      SELECT element_at(split(e.dataset, '\\\\.'), -1) AS dataset, e.name, sum(e.passed_records) AS passed, sum(e.failed_records) AS failed
      FROM (SELECT explode(from_json(details:flow_progress.data_quality.expectations::string,
                     'array<struct<name:string,dataset:string,passed_records:bigint,failed_records:bigint>>')) AS e
            FROM ev WHERE event_type = 'flow_progress' AND details:flow_progress.data_quality.expectations IS NOT NULL) GROUP BY 1, 2),
    expa AS (SELECT dataset, collect_list(named_struct('name', name, 'passed', passed, 'failed', failed)) AS expectations,
                    sum(passed) AS passed_records, sum(failed) AS failed_records FROM exp GROUP BY dataset)
    MERGE INTO {FQ}.meta_pipeline_update_metrics t
    USING (
      SELECT '{test_update_id}' AS update_id, {job_run_id} AS job_run_id, m.dataset, m.domain, m.layer, m.kind AS dataset_kind,
             m.file AS source_file, d.input_datasets, c.n AS rows_in_table, p.rows_written, p.duration_s, x.expectations,
             x.passed_records, x.failed_records, COALESCE(p.status, 'NOT_RUN') AS status, current_timestamp() AS recorded_at
      FROM ds_map m LEFT JOIN defs d USING (dataset) LEFT JOIN prog p USING (dataset) LEFT JOIN expa x USING (dataset)
      LEFT JOIN ds_counts c USING (dataset)) s
    ON t.update_id = s.update_id AND t.dataset = s.dataset
    WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
print(f"datasets mapped: {len(ds_map)}")

# COMMAND ----------
# MAGIC %md ## 3. Results ledger (immutable snapshot of this run)

# COMMAND ----------
spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.meta_control_results (
  job_run_id BIGINT NOT NULL, job_id BIGINT, task_run_id BIGINT, pipeline_id STRING, test_update_id STRING, executed_at TIMESTAMP,
  control_id STRING, control_version INT, module STRING, control_title STRING, key_control BOOLEAN, lane STRING,
  line_of_defense INT, entity_code STRING, period STRING, population_count BIGINT, population_amount_usd DOUBLE,
  exceptions BIGINT, exception_amount_usd DOUBLE, open_exceptions BIGINT, open_exception_amount_usd DOUBLE, result STRING,
  traditional_sample_size INT, data_cutoff DATE)
  COMMENT 'Immutable control-results ledger: one snapshot per run_controls run x control x entity x period, stamped with the job run, task run and pipeline update that produced it. Source of gold_mv_control_health and the checklist. Writers: record_results, gate_controls (PLT-01).'""")
spark.sql(f"""
MERGE INTO {FQ}.meta_control_results t
USING (
  SELECT {job_run_id} AS job_run_id, {job_id or 'NULL'} AS job_id, {task_run_id or 'NULL'} AS task_run_id,
         '{pipeline_id}' AS pipeline_id, {f"'{test_update_id}'" if test_update_id else 'NULL'} AS test_update_id,
         current_timestamp() AS executed_at, control_id, control_version, module, control_title, key_control, lane,
         line_of_defense, entity_code, period, population_count, CAST(population_amount_usd AS DOUBLE) AS population_amount_usd,
         exceptions, CAST(exception_amount_usd AS DOUBLE) AS exception_amount_usd, open_exceptions,
         CAST(open_exception_amount_usd AS DOUBLE) AS open_exception_amount_usd, result, traditional_sample_size,
         date_sub(current_date(), 1) AS data_cutoff
  FROM {FQ}.gold_control_results) s
ON t.job_run_id = s.job_run_id AND t.control_id = s.control_id AND t.entity_code = s.entity_code AND t.period = s.period
WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
res = spark.sql(f"""SELECT count(*) AS n, count(DISTINCT control_id) AS controls,
                           sum(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END) AS fail_rows,
                           count(DISTINCT CASE WHEN result = 'FAIL' THEN control_id END) AS failed_controls,
                           count(DISTINCT CASE WHEN result = 'FAIL' AND key_control THEN control_id END) AS failed_key,
                           sum(exceptions) AS exceptions
                    FROM {FQ}.meta_control_results WHERE job_run_id = {job_run_id}
                      AND period = date_format(current_date(), 'yyyy-MM')""").collect()[0]
print(f"results snapshot: {res['n']} rows, {res['controls']} controls in active period, failed={res['failed_controls']}")

# COMMAND ----------
# MAGIC %md ## 4. Exception log: NEW / RECURRING / RESOLVED vs the previous run

# COMMAND ----------
spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.meta_control_exception_log (
  job_run_id BIGINT NOT NULL, exception_id STRING NOT NULL, control_id STRING, entity_code STRING, period STRING,
  record_key STRING, amount_usd DOUBLE, change STRING, disposition_status STRING, first_seen_job_run_id BIGINT,
  first_seen_at TIMESTAMP, logged_at TIMESTAMP)
  COMMENT 'Per-run exception log: NEW, RECURRING, or RESOLVED versus the previous run_controls run. Writer: record_results.'""")
# Previous run by time (job run ids are not time-ordered).
prev = spark.sql(f"""SELECT max_by(job_run_id, logged_at) AS r FROM {FQ}.meta_control_exception_log
                     WHERE job_run_id <> {job_run_id}""").collect()[0]["r"]
spark.sql(f"""
MERGE INTO {FQ}.meta_control_exception_log t
USING (
  WITH cur AS (SELECT exception_id, control_id, entity_code, period, record_key, amount_usd, disposition_status
               FROM {FQ}.gold_control_exceptions),
  prv AS (SELECT * FROM {FQ}.meta_control_exception_log WHERE job_run_id = {prev or -1} AND change <> 'RESOLVED'),
  first_seen AS (SELECT exception_id, min(first_seen_job_run_id) AS fs_run, min(first_seen_at) AS fs_at
                 FROM {FQ}.meta_control_exception_log GROUP BY exception_id)
  SELECT {job_run_id} AS job_run_id, COALESCE(c.exception_id, p.exception_id) AS exception_id,
         COALESCE(c.control_id, p.control_id) AS control_id, COALESCE(c.entity_code, p.entity_code) AS entity_code,
         COALESCE(c.period, p.period) AS period, COALESCE(c.record_key, p.record_key) AS record_key,
         COALESCE(c.amount_usd, p.amount_usd) AS amount_usd,
         CASE WHEN c.exception_id IS NULL THEN 'RESOLVED' WHEN p.exception_id IS NULL AND {1 if prev else 0} = 1 THEN 'NEW'
              WHEN p.exception_id IS NULL THEN 'BASELINE' ELSE 'RECURRING' END AS change,
         COALESCE(c.disposition_status, 'resolved') AS disposition_status,
         COALESCE(f.fs_run, {job_run_id}) AS first_seen_job_run_id, COALESCE(f.fs_at, current_timestamp()) AS first_seen_at,
         current_timestamp() AS logged_at
  FROM cur c FULL OUTER JOIN prv p ON c.exception_id = p.exception_id
  LEFT JOIN first_seen f ON f.exception_id = COALESCE(c.exception_id, p.exception_id)) s
ON t.job_run_id = s.job_run_id AND t.exception_id = s.exception_id
WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
chg = {r["change"]: r["n"] for r in spark.sql(f"""SELECT change, count(*) AS n FROM {FQ}.meta_control_exception_log
                                                  WHERE job_run_id = {job_run_id} GROUP BY change""").collect()}
print(f"exception changes vs run {prev}: {chg}")

# COMMAND ----------
# MAGIC %md ## 5. Close task status (closed periods from history, active period live)

# COMMAND ----------
spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.meta_close_task_status (
  period STRING NOT NULL, task_code STRING NOT NULL, task_name STRING, workstream STRING, owner_role STRING,
  period_status STRING, due_offset_bd INT, traditional_due_bd INT, earliest_offset_bd INT, pre_close BOOLEAN,
  signoff_role STRING, controls ARRAY<STRING>, depends_on ARRAY<STRING>, controls_green BOOLEAN,
  failing_controls ARRAY<STRING>, ready_at TIMESTAMP, signed_off_by STRING, signed_off_at TIMESTAMP,
  completed_at TIMESTAMP, completed_close_day INT, projected_close_day INT, status STRING, source STRING,
  reopened_count INT, is_overdue BOOLEAN, target_days_to_close INT, traditional_days_to_close INT, today_close_day INT,
  last_job_run_id BIGINT, updated_at TIMESTAMP)
  COMMENT 'Close task status per period x task. Closed periods: prior close-tool history. Active period: derived on every run_controls run from control results (controls green) and sign-offs; reopened when controls fail again. completed_close_day is T+n (business days after month end); CLS-12 completion = days to close. Writer: record_results.'""")

prev_status = {(r["period"], r["task_code"]): r.asDict() for r in spark.sql(
    f"SELECT * FROM {FQ}.meta_close_task_status WHERE period_status = 'ACTIVE'").collect()}
if rebaseline:   # demo reset: the active close is derived afresh from today's controls and sign-offs
    print(f"rebaseline: ignoring {len(prev_status)} earlier active-period task rows")
    prev_status = {}
active = spark.sql("SELECT date_format(current_date(), 'yyyy-MM') AS p").collect()[0]["p"]
per = spark.sql(f"SELECT * FROM {FQ}.gold_dim_period WHERE period = '{active}'").collect()[0]
# Today's position in the close (T-n / T+n) on the calendar date, the same mapping
# close_day() applies to completion timestamps (a weekend maps to the prior business day).
today_seq = spark.sql(f"SELECT bd_seq FROM {FQ}.gold_dim_business_day WHERE cal_date = current_date()").collect()[0][0]
today_offset = int(today_seq) - int(per["bd_seq_at_period_end"])
cal = [r.asDict() for r in spark.table(f"{FQ}.silver_close_calendar").collect()]
fails = {r["control_id"] for r in spark.sql(f"""SELECT DISTINCT control_id FROM {FQ}.gold_control_results
                                               WHERE period = '{active}' AND result = 'FAIL'""").collect()}
signs = {r["item_key"]: r.asDict() for r in spark.sql(f"""SELECT * FROM {FQ}.silver_review_status
                                                         WHERE item_type = 'close_task' AND period = '{active}'""").collect()}
bd_rows = {r["bd_seq"]: r["cal_date"] for r in spark.sql(
    f"SELECT bd_seq, max(cal_date) AS cal_date FROM {FQ}.gold_dim_business_day WHERE is_business_day GROUP BY bd_seq").collect()}


def close_day(ts):
    if ts is None:
        return None
    s = spark.sql(f"SELECT bd_seq FROM {FQ}.gold_dim_business_day WHERE cal_date = to_date('{ts.date().isoformat()}')").collect()
    return int(s[0][0]) - int(per["bd_seq_at_period_end"]) if s else None


rows, done = [], {}
for t in sorted(cal, key=lambda x: (len(x["depends_on"] or []), x["due_offset_bd"])):
    code = t["task_code"]
    prev_row = prev_status.get((active, code), {})
    ctl = list(t["controls"] or [])
    failing = sorted(c for c in ctl if c in fails)
    green = not failing and today_offset >= t["earliest_offset_bd"]
    deps_done = all(done.get(d) for d in (t["depends_on"] or []))
    ready_at = prev_row.get("ready_at") if (green and prev_row.get("ready_at")) else (now if green else None)
    s = signs.get(f"{active}|{code}") or {}
    signed_by, signed_at = s.get("signed_off_by"), s.get("signed_off_at")
    need_sign = t["signoff"] is not None
    signoff_ok = (not need_sign) or (signed_at is not None)
    complete = green and deps_done and signoff_ok
    completed_at = None
    if complete:
        completed_at = prev_row.get("completed_at") or max([x for x in (ready_at, signed_at) if x is not None] + [now if not need_sign else signed_at])
        dep_times = [done[d] for d in (t["depends_on"] or []) if done.get(d)]
        if dep_times:
            completed_at = max([completed_at] + dep_times)
    reopened = int(prev_row.get("reopened_count") or 0) + (1 if prev_row.get("status") == "COMPLETE" and not complete else 0)
    status = ("COMPLETE" if complete else "REOPENED" if prev_row.get("status") in ("COMPLETE", "REOPENED") and not complete
              else "READY_FOR_SIGNOFF" if green and deps_done and need_sign else "BLOCKED" if failing
              else "WAITING" if not deps_done else "NOT_STARTED")
    done[code] = completed_at
    projected = (close_day(completed_at) if completed_at else
                 max(t["due_offset_bd"], today_offset + 1, t["earliest_offset_bd"]) + (1 if failing else 0))
    rows.append({"period": active, "task_code": code, "task_name": t["name"], "workstream": t["workstream"],
                 "owner_role": t["owner_role"], "period_status": "ACTIVE", "due_offset_bd": t["due_offset_bd"],
                 "traditional_due_bd": t["traditional_due_bd"], "earliest_offset_bd": t["earliest_offset_bd"],
                 "pre_close": t["pre_close"], "signoff_role": t["signoff"], "controls": ctl, "depends_on": list(t["depends_on"] or []),
                 "controls_green": green, "failing_controls": failing, "ready_at": ready_at, "signed_off_by": signed_by,
                 "signed_off_at": signed_at, "completed_at": completed_at, "completed_close_day": close_day(completed_at),
                 "projected_close_day": projected, "status": status, "source": "control_run", "reopened_count": reopened,
                 "is_overdue": (not complete) and t["due_offset_bd"] < today_offset,
                 "target_days_to_close": t["target_days_to_close"], "traditional_days_to_close": t["traditional_days_to_close"],
                 "today_close_day": today_offset, "last_job_run_id": job_run_id, "updated_at": now})
# Dependencies push projections: a task cannot finish before what it depends on.
proj = {r["task_code"]: r["projected_close_day"] for r in rows}
for r in rows:
    deps = r["depends_on"] or []
    if deps and r["completed_at"] is None:
        r["projected_close_day"] = max([r["projected_close_day"]] + [proj[d] for d in deps])
        proj[r["task_code"]] = r["projected_close_day"]

CTS_DDL = """period STRING, task_code STRING, task_name STRING, workstream STRING, owner_role STRING, period_status STRING,
  due_offset_bd INT, traditional_due_bd INT, earliest_offset_bd INT, pre_close BOOLEAN, signoff_role STRING,
  controls ARRAY<STRING>, depends_on ARRAY<STRING>, controls_green BOOLEAN, failing_controls ARRAY<STRING>,
  ready_at TIMESTAMP, signed_off_by STRING, signed_off_at TIMESTAMP, completed_at TIMESTAMP, completed_close_day INT,
  projected_close_day INT, status STRING, source STRING, reopened_count INT, is_overdue BOOLEAN, target_days_to_close INT,
  traditional_days_to_close INT, today_close_day INT, last_job_run_id BIGINT, updated_at TIMESTAMP"""
spark.createDataFrame(rows, CTS_DDL).createOrReplaceTempView("live_tasks")
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW hist_tasks AS
SELECT h.period, h.task_code, h.task_name, h.workstream, c.owner_role, 'CLOSED' AS period_status, c.due_offset_bd,
       c.traditional_due_bd, c.earliest_offset_bd, c.pre_close, c.signoff AS signoff_role, c.controls, c.depends_on,
       true AS controls_green, CAST(array() AS ARRAY<STRING>) AS failing_controls, h.completed_at AS ready_at,
       h.signed_off_by, h.signed_off_at, h.completed_at, h.completed_close_day, h.completed_close_day AS projected_close_day,
       'COMPLETE' AS status, 'close_tool' AS source, 0 AS reopened_count, false AS is_overdue, c.target_days_to_close,
       c.traditional_days_to_close, CAST(NULL AS INT) AS today_close_day, {job_run_id} AS last_job_run_id, current_timestamp() AS updated_at
FROM {FQ}.silver_close_task_history h JOIN {FQ}.silver_close_calendar c USING (task_code)
WHERE h.period < '{active}'""")
spark.sql(f"""
MERGE INTO {FQ}.meta_close_task_status t
USING (SELECT * FROM live_tasks UNION ALL SELECT * FROM hist_tasks) s
ON t.period = s.period AND t.task_code = s.task_code
WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *""")
cls12 = next(r for r in rows if r["task_code"] == "CLS-12")
n_done = sum(1 for r in rows if r["status"] == "COMPLETE")
print(f"active close {active}: today T{today_offset:+d}, {n_done}/{len(rows)} tasks complete, "
      f"projected days to close T+{cls12['projected_close_day']}")

# COMMAND ----------
# MAGIC %md ## 6. Run ledger

# COMMAND ----------
spark.sql(f"""UPDATE {FQ}.meta_control_runs SET
  test_update_id = {f"'{test_update_id}'" if test_update_id else 'NULL'},
  test_update_task_run_id = {int(test_task_run_id) if test_task_run_id else 'NULL'},
  record_task_run_id = {task_run_id or 'NULL'},
  controls_executed = {int(res['controls'] or 0)}, controls_failed = {int(res['failed_controls'] or 0)},
  key_controls_failed = {int(res['failed_key'] or 0)}, exceptions_found = {int(res['exceptions'] or 0)},
  new_exceptions = {int(chg.get('NEW', 0))}, resolved_exceptions = {int(chg.get('RESOLVED', 0))}
WHERE job_run_id = {job_run_id}""")
out = {"test_update_id": test_update_id, "resolved_via": method, "datasets": len(ds_map), "results_rows": int(res["n"]),
       "failed_controls": int(res["failed_controls"] or 0), "exception_changes": chg, "today_offset": today_offset,
       "tasks_complete": n_done, "projected_days_to_close": cls12["projected_close_day"]}
dbutils.jobs.taskValues.set(key="test_update_id", value=test_update_id or "")
dbutils.notebook.exit(json.dumps(out, default=str))
