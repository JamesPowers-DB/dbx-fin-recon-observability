# Databricks notebook source
# MAGIC %md
# MAGIC # provision_genie_space_job: Genie space, idempotent by title
# MAGIC
# MAGIC Creates or refreshes the Genie space defined in `genie_space_def.py`, with the
# MAGIC seven metric views only. The space is matched by TITLE, so re-running keeps the
# MAGIC same space id. The app resolves the id by the same title at runtime.

# COMMAND ----------
dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("target", "prod")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
warehouse_id = dbutils.widgets.get("warehouse_id")
target = dbutils.widgets.get("target")
assert catalog and schema and warehouse_id

# COMMAND ----------
import json
import os
import sys

_nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
_dir = os.path.dirname(_nb if _nb.startswith("/Workspace") else "/Workspace" + _nb)
sys.path.insert(0, _dir)
from genie_space_def import DEFAULT_DESCRIPTION, build_serialized_space, space_title  # noqa: E402

from databricks.sdk import WorkspaceClient  # noqa: E402

w = WorkspaceClient()
title = space_title(target)
serialized = json.dumps(build_serialized_space(catalog, schema))

# COMMAND ----------
def find_space_id(t: str):
    token = None
    while True:
        q = {"page_size": 100, **({"page_token": token} if token else {})}
        res = w.api_client.do("GET", "/api/2.0/genie/spaces", query=q)
        for s in res.get("spaces", []):
            if s.get("title") == t:
                return s.get("space_id")
        token = res.get("next_page_token")
        if not token:
            return None


existing = find_space_id(title)
body = {"title": title, "description": DEFAULT_DESCRIPTION, "warehouse_id": warehouse_id, "serialized_space": serialized}
if existing:
    w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{existing}", body=body)
    space_id = existing
    print(f"Updated Genie space {space_id} ({title})")
else:
    body["parent_path"] = f"/Users/{w.current_user.me().user_name}"
    space_id = w.api_client.do("POST", "/api/2.0/genie/spaces", body=body).get("space_id")
    print(f"Created Genie space {space_id} ({title})")
dbutils.notebook.exit(json.dumps({"space_id": space_id, "title": title}))
