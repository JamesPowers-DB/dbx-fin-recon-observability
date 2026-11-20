# Databricks notebook source
# MAGIC %md
# MAGIC # publish_controls (run_controls task 2; also setup step 2)
# MAGIC
# MAGIC Publishes the controls-as-code YAML to Unity Catalog:
# MAGIC
# MAGIC | Source | Table | Rule |
# MAGIC |---|---|---|
# MAGIC | `controls/library/*.yml` | `meta_control_library` | versioned: (control_id, version) is immutable. If a definition changes without a version bump, the task fails. `is_current` marks the latest version. |
# MAGIC | `controls/risk_register.yml` | `meta_risk_register` | overwritten |
# MAGIC | `controls/close_calendar.yml` | `meta_close_calendar` | overwritten |
# MAGIC
# MAGIC It runs the same validation as the CLI twin `controls/validate_controls.py`,
# MAGIC covering bindings, risks, and calendar references. It also creates the PII
# MAGIC column-mask function used by M4 (`mask_pii`). Idempotent: no-op when nothing
# MAGIC changed.

# COMMAND ----------
import json
import os
import sys

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("job_run_id", "")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
job_run_id = dbutils.widgets.get("job_run_id") or None
assert catalog and schema
FQ = f"`{catalog}`.`{schema}`"

nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ROOT = os.path.dirname(os.path.dirname(os.path.dirname("/Workspace" + nb if not nb.startswith("/Workspace") else nb)))
sys.path.insert(0, os.path.join(ROOT, "controls"))
import control_lib  # noqa: E402

controls, risks, cal = control_lib.load_all(os.path.join(ROOT, "controls"))
errors = control_lib.validate(controls, risks, cal, repo_root=ROOT)
if errors:
    raise AssertionError("Control library is invalid:\n  " + "\n  ".join(errors))
print(f"validated {len(controls)} controls, {len(risks['risks'])} risks, {len(cal['tasks'])} close tasks")

# COMMAND ----------
LIB_DDL = """control_id STRING, version INT, module STRING, module_name STRING, title STRING, objective STRING,
  risk_ids ARRAY<STRING>, key_control BOOLEAN, assertions ARRAY<STRING>, nature_type STRING, automation STRING,
  line_of_defense INT, lane STRING, frequency STRING, owner_role STRING, population_dataset STRING,
  population_unit STRING, population_description STRING, parameters MAP<STRING,STRING>, max_exceptions INT,
  max_amount_usd DOUBLE, executed_by_kind STRING, executed_by_job STRING, executed_by_task STRING,
  executed_by_dataset STRING, executed_by_expectation STRING, exceptions_dataset STRING, test_sql_file STRING,
  policy_ref STRING, evidence_documents ARRAY<STRING>, signoff_preparer_role STRING, signoff_reviewer_role STRING,
  four_eyes BOOLEAN, lifecycle_state STRING, effective_from DATE, traditional_sample_size INT,
  definition_hash STRING, definition_json STRING, source_file STRING"""
spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.meta_control_library ({LIB_DDL}, published_at TIMESTAMP,
  published_by_job_run_id BIGINT, is_current BOOLEAN)
  COMMENT 'Control library (controls as code) published from controls/library/*.yml by publish_controls. One row per control version; (control_id, version) is immutable and is_current marks the version every run executes. Writer: publish_controls only.'""")

existing = {(r["control_id"], r["version"]): r["definition_hash"]
            for r in spark.table(f"{FQ}.meta_control_library").select("control_id", "version", "definition_hash").collect()}
rows = control_lib.control_rows(controls)
changed_without_bump = [r["control_id"] for r in rows
                        if (r["control_id"], r["version"]) in existing and existing[(r["control_id"], r["version"])] != r["definition_hash"]]
if changed_without_bump:
    raise AssertionError(f"Definition changed without a version bump: {changed_without_bump}. Increment `version` in the YAML.")
new_rows = [r for r in rows if (r["control_id"], r["version"]) not in existing]
if new_rows:
    df = spark.createDataFrame(new_rows, schema=LIB_DDL)
    df.createOrReplaceTempView("new_controls")
    spark.sql(f"""INSERT INTO {FQ}.meta_control_library
                  SELECT *, current_timestamp(), CAST(NULLIF('{job_run_id or ''}', '') AS BIGINT), true FROM new_controls""")
    spark.sql(f"""UPDATE {FQ}.meta_control_library t SET is_current = false
                  WHERE is_current AND EXISTS (SELECT 1 FROM new_controls n WHERE n.control_id = t.control_id AND n.version > t.version)""")
print(f"control versions published: {len(new_rows)} new, {len(rows) - len(new_rows)} unchanged")

# COMMAND ----------
RISK_DDL = """risk_id STRING, title STRING, category STRING, owner_role STRING, inherent_likelihood INT, inherent_impact INT,
  inherent_score INT, appetite STRING, kri_metric_view STRING, kri_measure STRING, kri_threshold DOUBLE,
  kri_direction STRING, kri_label STRING, control_ids ARRAY<STRING>, register_version INT"""
(spark.createDataFrame(control_lib.risk_rows(risks), schema=RISK_DDL).write.format("delta").mode("overwrite")
 .option("overwriteSchema", "true").saveAsTable(f"{FQ}.meta_risk_register"))
CAL_DDL = """task_code STRING, name STRING, workstream STRING, owner_role STRING, controls ARRAY<STRING>,
  depends_on ARRAY<STRING>, signoff STRING, due_offset_bd INT, traditional_due_bd INT, earliest_offset_bd INT,
  pre_close BOOLEAN, calendar_version INT, target_days_to_close INT, north_star_days_to_close INT,
  traditional_days_to_close INT"""
(spark.createDataFrame(control_lib.calendar_rows(cal), schema=CAL_DDL).write.format("delta").mode("overwrite")
 .option("overwriteSchema", "true").saveAsTable(f"{FQ}.meta_close_calendar"))
spark.sql(f"COMMENT ON TABLE {FQ}.meta_risk_register IS 'Risk register from controls/risk_register.yml: risks, KRIs (metric-view measures with thresholds) and linked controls. Writer: publish_controls.'")
spark.sql(f"COMMENT ON TABLE {FQ}.meta_close_calendar IS 'Close calendar from controls/close_calendar.yml: 12 close tasks, the controls and sign-offs that complete them, and due offsets (T+n). Writer: publish_controls.'")

# COMMAND ----------
# Review-state landing table (written by snapshot_review_state). Created here,
# empty, so the pipeline can read it on a first install before any snapshot runs.
spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.meta_review_actions (
  action_id STRING NOT NULL, item_type STRING NOT NULL, item_key STRING NOT NULL, period STRING, action STRING NOT NULL,
  disposition STRING, comment STRING, payload STRING, actor_email STRING NOT NULL, actor_role STRING NOT NULL,
  attested_job_run_id BIGINT, created_at TIMESTAMP NOT NULL, synced_at TIMESTAMP, synced_by_job_run_id BIGINT)
  COMMENT 'Human review actions copied one-way from the Audit Workbench Lakebase store by run_controls.snapshot_review_state. Writer: snapshot_review_state only.'""")

# COMMAND ----------
# PII column mask for identity attributes (applied in M4 gold). Only members of
# the fin_recon_pii_readers account group see clear values.
spark.sql(f"""CREATE OR REPLACE FUNCTION {FQ}.mask_pii(v STRING)
  RETURNS STRING
  COMMENT 'Column mask for identity PII (names, emails). Clear text only for members of fin_recon_pii_readers.'
  RETURN CASE WHEN is_account_group_member('fin_recon_pii_readers') THEN v
              WHEN v IS NULL THEN NULL
              ELSE concat(left(v, 1), '***') END""")
summary = {"controls": len(rows), "new_versions": len(new_rows), "library_hash": control_lib.library_hash(controls),
           "risks": len(risks["risks"]), "close_tasks": len(cal["tasks"])}
dbutils.jobs.taskValues.set(key="library_hash", value=summary["library_hash"])
dbutils.notebook.exit(json.dumps(summary))
