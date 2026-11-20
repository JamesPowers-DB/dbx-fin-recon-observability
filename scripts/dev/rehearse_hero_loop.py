# Databricks notebook source
# MAGIC %md
# MAGIC # Rehearse the hero loop (dev only)
# MAGIC
# MAGIC Plays the presenter's review clicks for a dry run without a browser: approves
# MAGIC every pending JET-01 proposal in the active close as an independent reviewer
# MAGIC and signs off CLS-01 (journal entry review), writing to the same Lakebase
# MAGIC table the app writes. Then run `simulate_activity`; its control run applies
# MAGIC the actions. Reset afterwards with the `refresh` job.
# MAGIC
# MAGIC Submit as a one-time notebook run (`databricks jobs submit`) on serverless.

# COMMAND ----------
import json
import uuid
from datetime import datetime, timezone

import psycopg
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("lakebase_project", "fin-recon-observability")
dbutils.widgets.text("reviewer", "rehearsal.reviewer@corvane.example")
project, reviewer = dbutils.widgets.get("lakebase_project"), dbutils.widgets.get("reviewer")
period = datetime.now(timezone.utc).strftime("%Y-%m")

w = WorkspaceClient()
ep = f"projects/{project}/branches/production/endpoints/primary"
host = w.postgres.get_endpoint(name=ep).status.hosts.host
conninfo = (f"host={host} port=5432 dbname=databricks_postgres user={w.current_user.me().user_name} "
            f"password={w.postgres.generate_database_credential(endpoint=ep).token} sslmode=require")

with psycopg.connect(conninfo) as conn:
    pending = conn.execute("""
        SELECT DISTINCT ON (item_key) item_key, actor_email, disposition, action
        FROM audit.review_actions
        WHERE item_type = 'exception' AND period = %s AND payload->>'control_id' = 'JET-01'
        ORDER BY item_key, created_at DESC""", (period,)).fetchall()
    todo = [(k, who, disp) for k, who, disp, act in pending if act == "propose" and who.lower() != reviewer.lower()]
    with conn.cursor() as cur:
        for k, who, disp in todo:
            cur.execute("""INSERT INTO audit.review_actions (action_id, item_type, item_key, period, action, disposition, comment,
                             payload, actor_email, actor_role, created_at)
                           VALUES (%s, 'exception', %s, %s, 'approve', %s, 'Rehearsal: evidence reviewed; approved.', %s::jsonb, %s, 'reviewer', now())""",
                        (uuid.uuid4().hex, k, period, disp, json.dumps({"rehearsal": True, "control_id": "JET-01", "counterpart_email": who}), reviewer))
        cur.execute("""INSERT INTO audit.review_actions (action_id, item_type, item_key, period, action, comment, payload,
                         actor_email, actor_role, created_at)
                       VALUES (%s, 'close_task', %s, %s, 'signoff', 'Rehearsal: journal entry review signed off.', %s::jsonb, %s, 'reviewer', now())""",
                    (uuid.uuid4().hex, f"{period}|CLS-01", period, json.dumps({"rehearsal": True}), reviewer))
    conn.commit()
print(f"approved {len(todo)} JET-01 proposals and signed off CLS-01 as {reviewer}")
dbutils.notebook.exit(json.dumps({"approved": len(todo), "period": period}))
