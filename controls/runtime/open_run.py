# Databricks notebook source
# MAGIC %md
# MAGIC # open_run (run_controls task 1)
# MAGIC
# MAGIC Opens the run ledger row for this control run in `meta_control_runs`
# MAGIC (status RUNNING) from the job's dynamic value references: job id, run id,
# MAGIC trigger type, start time, and the job parameters `trigger_source`,
# MAGIC `requested_by`, and `reason`.
# MAGIC
# MAGIC Every checklist status links back to this row. It is the "who ran what,
# MAGIC when, and why" of continuous monitoring. MERGE on job_run_id, so a
# MAGIC repaired run reuses its row.

# COMMAND ----------
import json

for w in ("catalog", "schema", "job_id", "job_run_id", "trigger_type", "started_at", "trigger_source", "requested_by",
          "reason", "pipeline_id"):
    dbutils.widgets.text(w, "")
g = {w: dbutils.widgets.get(w) for w in ("catalog", "schema", "job_id", "job_run_id", "trigger_type", "started_at",
                                         "trigger_source", "requested_by", "reason", "pipeline_id")}
assert g["catalog"] and g["schema"] and g["job_run_id"], "catalog / schema / job_run_id must be set"
FQ = f"`{g['catalog']}`.`{g['schema']}`"

# COMMAND ----------
spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.meta_control_runs (
  job_run_id BIGINT NOT NULL, job_id BIGINT, pipeline_id STRING, trigger_type STRING, trigger_source STRING,
  requested_by STRING, reason STRING, started_at TIMESTAMP, ended_at TIMESTAMP, status STRING,
  library_hash STRING, controls_published INT, test_update_id STRING, test_update_task_run_id BIGINT,
  record_task_run_id BIGINT, gate_task_run_id BIGINT, review_actions_synced INT,
  controls_executed INT, controls_failed INT, key_controls_failed INT, exceptions_found INT, new_exceptions INT,
  resolved_exceptions INT, triaged_exceptions INT, planted_recall DOUBLE, gate_result STRING, gate_detail STRING,
  data_cutoff DATE, active_period STRING)
  COMMENT 'Run ledger: one row per run_controls run (who triggered it, when, why, which pipeline update tested the controls, and the outcome). Append-only; writers: open_run, record_results, gate_controls.'""")

row = {
    "job_run_id": int(g["job_run_id"]), "job_id": int(g["job_id"]) if g["job_id"] else None,
    "pipeline_id": g["pipeline_id"] or None, "trigger_type": g["trigger_type"] or None,
    "trigger_source": g["trigger_source"] or "manual", "requested_by": g["requested_by"] or None,
    "reason": g["reason"] or None, "started_at": g["started_at"] or None,
}
spark.createDataFrame([row], "job_run_id BIGINT, job_id BIGINT, pipeline_id STRING, trigger_type STRING, trigger_source STRING, "
                             "requested_by STRING, reason STRING, started_at STRING").createOrReplaceTempView("new_run")
spark.sql(f"""MERGE INTO {FQ}.meta_control_runs t
USING (SELECT *, COALESCE(try_cast(started_at AS TIMESTAMP), current_timestamp()) AS started_ts,
              date_sub(current_date(), 1) AS cutoff, date_format(current_date(), 'yyyy-MM') AS active FROM new_run) s
ON t.job_run_id = s.job_run_id
WHEN MATCHED THEN UPDATE SET t.status = 'RUNNING', t.ended_at = NULL
WHEN NOT MATCHED THEN INSERT (job_run_id, job_id, pipeline_id, trigger_type, trigger_source, requested_by, reason, started_at,
                              status, data_cutoff, active_period)
  VALUES (s.job_run_id, s.job_id, s.pipeline_id, s.trigger_type, s.trigger_source, s.requested_by, s.reason, s.started_ts,
          'RUNNING', s.cutoff, s.active)""")
print(f"run {row['job_run_id']} opened: trigger={row['trigger_type']}/{row['trigger_source']} by {row['requested_by']}")
dbutils.notebook.exit(json.dumps({"job_run_id": row["job_run_id"], "status": "RUNNING"}))
