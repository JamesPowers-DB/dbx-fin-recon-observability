#!/usr/bin/env python3
"""Serve the app locally against the live schema for a browser pass (local dev only).

The real FastAPI app and the built frontend (frontend/dist), with warehouse calls
routed through the Databricks CLI profile. Lakebase, Jobs (service principal) and
model calls are unavailable locally and show their own error states.

  cd apps/audit-workbench && \\
    uv run --no-project --with-requirements requirements.txt --with pyarrow \\
    python ../../scripts/dev/serve_local.py --profile <profile> --warehouse <id> [--port 8765]

--driver connector (default) keeps the app's real fetch_all on databricks-sql-connector
with pyarrow, so complex column types arrive exactly as in the deployed app. The
workspace host is read from the profile unless --host is given.
"""
import argparse
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--profile", required=True)
ap.add_argument("--warehouse", required=True)
ap.add_argument("--host", default=None, help="workspace URL (default: the profile's host)")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--driver", choices=["connector", "statement-api"], default="connector")
x = ap.parse_args()
if not x.host:
    from databricks.sdk.core import Config
    x.host = Config(profile=x.profile).host
os.environ.update({"APP_DEV_ALLOW_ANONYMOUS": "1", "DATABRICKS_HOST": x.host, "DATABRICKS_WAREHOUSE_ID": x.warehouse,
                   "APP_DEV_USER_EMAIL": "presenter@corvane.example"})
sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cli_sql  # noqa: E402

if x.driver == "connector":
    import pyarrow  # noqa: F401,E402 - the Apps runtime has it; without it complex types arrive as JSON strings
    _cli_sql.install_connector(x.profile, x.warehouse)
else:
    _cli_sql.install(x.profile, x.warehouse)
import uvicorn  # noqa: E402

from backend.main import app  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=x.port, log_level="warning")
