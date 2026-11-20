# Databricks notebook source
# MAGIC %md
# MAGIC # triage_exceptions (run_controls task 6): AI investigation
# MAGIC
# MAGIC Runs `ai/triage_exceptions.sql`: one `ai_query` MERGE that triages every
# MAGIC exception not yet triaged at the current prompt version, capped per run,
# MAGIC writing `ml_exception_triage`. The table is keyed by exception_id and joined
# MAGIC into `gold_mv_exceptions` (no second pipeline update needed).
# MAGIC
# MAGIC Bump PROMPT_VERSION to re-triage everything after a prompt change.

# COMMAND ----------
import json
import os

PROMPT_VERSION = "v2"
for w in ("catalog", "schema", "job_run_id", "endpoint", "max_per_run"):
    dbutils.widgets.text(w, "")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
job_run_id = int(dbutils.widgets.get("job_run_id") or 0)
endpoint = dbutils.widgets.get("endpoint") or "databricks-claude-haiku-5-5"
max_per_run = int(dbutils.widgets.get("max_per_run") or 400)
FQ = f"`{catalog}`.`{schema}`"
nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
ROOT = os.path.dirname(os.path.dirname("/Workspace" + nb if not nb.startswith("/Workspace") else nb))

# COMMAND ----------
spark.sql(f"""CREATE TABLE IF NOT EXISTS {FQ}.ml_exception_triage (
  exception_id STRING NOT NULL, control_id STRING, entity_code STRING, period STRING, root_cause_category STRING,
  severity STRING, confidence DOUBLE, rationale STRING, recommended_action STRING, draft_finding STRING,
  needs_human BOOLEAN, error_message STRING, model STRING, prompt_version STRING, triaged_at TIMESTAMP, job_run_id BIGINT)
  COMMENT 'AI triage of control exceptions (ai_query on a Claude pay-per-token endpoint, structured JSON output). One row per exception_id. Labelled AI-generated in every surface; a human disposition is still required. Writer: run_controls.triage_exceptions.'""")
before = spark.sql(f"SELECT count(*) AS n FROM {FQ}.ml_exception_triage WHERE root_cause_category IS NOT NULL").collect()[0]["n"]
sql = open(os.path.join(ROOT, "ai", "triage_exceptions.sql")).read()
sql = (sql.replace("__FQ__", FQ).replace("__ENDPOINT__", endpoint).replace("__MAX__", str(max_per_run))
          .replace("__PROMPT_VERSION__", PROMPT_VERSION).replace("__JOB_RUN_ID__", str(job_run_id or "NULL")))
stmt = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
spark.sql(stmt)
after = spark.sql(f"SELECT count(*) AS n FROM {FQ}.ml_exception_triage WHERE root_cause_category IS NOT NULL").collect()[0]["n"]
errors = spark.sql(f"SELECT count(*) AS n FROM {FQ}.ml_exception_triage WHERE root_cause_category IS NULL").collect()[0]["n"]
total = spark.sql(f"SELECT count(*) AS n FROM {FQ}.gold_control_exceptions").collect()[0]["n"]
print(f"triaged this run: {after - before}; total triaged {after}/{total}; model errors pending retry: {errors}")
dbutils.jobs.taskValues.set(key="triaged", value=int(after - before))
dbutils.notebook.exit(json.dumps({"triaged_this_run": int(after - before), "triaged_total": int(after),
                                  "exceptions_total": int(total), "errors": int(errors), "endpoint": endpoint}))
