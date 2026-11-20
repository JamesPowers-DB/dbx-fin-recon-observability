# Databricks notebook source
# MAGIC %md
# MAGIC # snapshot_review_state (run_controls task 3)
# MAGIC
# MAGIC One-way sync of human review actions from Lakebase (app-owned, append-only
# MAGIC `audit.review_actions`) into Unity Catalog `meta_review_actions`, so the
# MAGIC pipeline can apply dispositions and sign-offs in the same update that
# MAGIC tests the controls. The app never writes UC; nothing flows back.
# MAGIC
# MAGIC Runs as the job's run_as identity (the deployer, owner of the Lakebase
# MAGIC project with DATABRICKS_SUPERUSER). MERGE on action_id: idempotent. UC mirrors
# MAGIC Lakebase: actions removed there (the demo reset) are removed here, but only when
# MAGIC the Lakebase table was read; an unreachable or empty project never deletes.
# MAGIC Tolerates a project with no app tables yet (first install): writes zero rows.

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("lakebase_project", "fin-recon-observability")
dbutils.widgets.text("job_run_id", "")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
project = dbutils.widgets.get("lakebase_project")
job_run_id = dbutils.widgets.get("job_run_id")
assert catalog and schema and project, "catalog / schema / lakebase_project must be set"
FQ = f"`{catalog}`.`{schema}`"

# COMMAND ----------
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {FQ}.meta_review_actions (
  action_id           STRING NOT NULL,
  item_type           STRING NOT NULL,
  item_key            STRING NOT NULL,
  period              STRING,
  action              STRING NOT NULL,
  disposition         STRING,
  comment             STRING,
  payload             STRING,
  actor_email         STRING NOT NULL,
  actor_role          STRING NOT NULL,
  attested_job_run_id BIGINT,
  created_at          TIMESTAMP NOT NULL,
  synced_at           TIMESTAMP,
  synced_by_job_run_id BIGINT
)
COMMENT 'Human review actions (exception dispositions, variance explanations and acknowledgements, control and close-task sign-offs) copied one-way from the Audit Workbench Lakebase store by run_controls.snapshot_review_state. Append-only by action_id. Writer: snapshot_review_state only.'
""")

# COMMAND ----------
import psycopg
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
endpoint = f"projects/{project}/branches/production/endpoints/primary"
host = w.postgres.get_endpoint(name=endpoint).status.hosts.host
user = w.current_user.me().user_name
token = w.postgres.generate_database_credential(endpoint=endpoint).token
conninfo = f"host={host} port=5432 dbname=databricks_postgres user={user} password={token} sslmode=require"

rows = []
with psycopg.connect(conninfo) as conn:
    exists = conn.execute("SELECT to_regclass('audit.review_actions') IS NOT NULL").fetchone()[0]
    if exists:
        cur = conn.execute("""
            SELECT action_id, item_type, item_key, period, action, disposition, comment,
                   CAST(payload AS TEXT), actor_email, actor_role, attested_job_run_id, created_at
            FROM audit.review_actions ORDER BY created_at""")
        rows = cur.fetchall()
print(f"Lakebase audit.review_actions: table_exists={exists}, rows={len(rows)} (read as {user})")

# COMMAND ----------
from pyspark.sql import types as T

schema_ = T.StructType([
    T.StructField("action_id", T.StringType(), False), T.StructField("item_type", T.StringType(), False),
    T.StructField("item_key", T.StringType(), False), T.StructField("period", T.StringType()),
    T.StructField("action", T.StringType(), False), T.StructField("disposition", T.StringType()),
    T.StructField("comment", T.StringType()), T.StructField("payload", T.StringType()),
    T.StructField("actor_email", T.StringType(), False), T.StructField("actor_role", T.StringType(), False),
    T.StructField("attested_job_run_id", T.LongType()), T.StructField("created_at", T.TimestampType(), False),
])
src = spark.createDataFrame([tuple(r) for r in rows], schema_)
src.createOrReplaceTempView("lakebase_review_actions")
spark.sql(f"""
MERGE INTO {FQ}.meta_review_actions t
USING (SELECT *, current_timestamp() AS synced_at, CAST(NULLIF('{job_run_id}', '') AS BIGINT) AS synced_by_job_run_id
       FROM lakebase_review_actions) s
ON t.action_id = s.action_id
WHEN NOT MATCHED THEN INSERT *
{"WHEN NOT MATCHED BY SOURCE THEN DELETE" if exists else ""}
""")
total = spark.table(f"{FQ}.meta_review_actions").count()
print(f"meta_review_actions rows after sync: {total}")
dbutils.jobs.taskValues.set(key="review_actions_synced", value=len(rows))

# COMMAND ----------
import json
dbutils.notebook.exit(json.dumps({"lakebase_table_exists": bool(exists), "rows_read": len(rows),
                                  "meta_rows": total, "read_as": user}))
