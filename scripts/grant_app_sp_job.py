# Databricks notebook source
# ============================================================================
# grant_app_sp_job: grant the app's auto-created service principal what it needs.
#   1. Resolve the SP from the deployed app (service_principal_client_id).
#   2. Schema-level UC grants: every current and future table and metric view, the
#      mask function (EXECUTE), and READ VOLUME for the evidence PDFs.
#   3. CAN_RUN on the Genie space, resolved by title (workspace ACL, not a UC grant).
# catalog/schema/app_name arrive as job parameters. Runs as the job's run_as.
# ============================================================================

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("raw_volume", "files")
dbutils.widgets.text("app_name", "audit-workbench-prod")
dbutils.widgets.text("target", "prod")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
raw_volume = dbutils.widgets.get("raw_volume")
app_name = dbutils.widgets.get("app_name")
target = dbutils.widgets.get("target")

# COMMAND ----------
import os, sys
_nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
sys.path.insert(0, "/Workspace" + os.path.dirname(os.path.dirname(_nb)) + "/genie")
from genie_space_def import space_title

from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

app = w.api_client.do("GET", f"/api/2.0/apps/{app_name}")
sp = app.get("service_principal_client_id")
if not sp:
    raise SystemExit(f"App '{app_name}' has no service_principal_client_id; deploy the app first.")
print(f"App SP: {sp} ({app.get('service_principal_name')})")

# COMMAND ----------
for stmt in (f"GRANT USE CATALOG ON CATALOG `{catalog}` TO `{sp}`",
             f"GRANT USE SCHEMA, SELECT, EXECUTE ON SCHEMA `{catalog}`.`{schema}` TO `{sp}`",
             f"GRANT READ VOLUME ON VOLUME `{catalog}`.`{schema}`.`{raw_volume}` TO `{sp}`"):
    spark.sql(stmt)
    print("OK", stmt)

# COMMAND ----------
def find_space_id(title: str) -> str | None:
    token = None
    while True:
        q = {"page_size": 100, **({"page_token": token} if token else {})}
        res = w.api_client.do("GET", "/api/2.0/genie/spaces", query=q)
        for s in res.get("spaces", []):
            if s.get("title") == title:
                return s.get("space_id")
        token = res.get("next_page_token")
        if not token:
            return None

title = space_title(target)
space_id = find_space_id(title)
if space_id:
    w.api_client.do("PATCH", f"/api/2.0/permissions/genie/{space_id}", body={
        "access_control_list": [{"service_principal_name": sp, "permission_level": "CAN_RUN"}]})
    print(f"OK Genie CAN_RUN on {space_id} ({title})")
else:
    print(f"WARN Genie space '{title}' not found; run provision_genie first.")
