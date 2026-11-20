#!/usr/bin/env python3
"""Smoke-test the app's read endpoints against the live schema (local dev only).

Runs the FastAPI app in-process (TestClient, anonymous dev identity). By default
(--driver connector) the app's own fetch_all runs on databricks-sql-connector,
authenticated through the Databricks CLI profile, so every router's SQL runs
against the real tables with the deployed value types and no token in this
process. Lakebase, Jobs (SP) and model calls are not available locally; those
parts report their own errors and are skipped.

  cd apps/audit-workbench && \
    uv run --no-project --with-requirements requirements.txt --with pyarrow \
    python ../../scripts/dev/smoke_api.py --profile <profile> --warehouse <id> [--only close,checklist]

The workspace host is read from the profile unless --host is given.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime

ap = argparse.ArgumentParser()
ap.add_argument("--profile", required=True)
ap.add_argument("--warehouse", required=True)
ap.add_argument("--host", default=None, help="workspace URL (default: the profile's host)")
ap.add_argument("--only", default="")
ap.add_argument("--verbose", action="store_true")
ap.add_argument("--driver", choices=["connector", "statement-api"], default="connector",
                help="connector: the app's real fetch_all on databricks-sql-connector (deployed types; "
                     "needs databricks-sql-connector[pyarrow]). statement-api: the JSON shim.")
a = ap.parse_args()
if not a.host:
    from databricks.sdk.core import Config  # noqa: E402
    a.host = Config(profile=a.profile).host

os.environ.update({"APP_DEV_ALLOW_ANONYMOUS": "1", "DATABRICKS_HOST": a.host, "DATABRICKS_WAREHOUSE_ID": a.warehouse})
sys.path.insert(0, os.getcwd())

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cli_sql  # noqa: E402

if a.driver == "connector":
    import pyarrow  # noqa: F401,E402 - the Apps runtime has it; without it complex types arrive as JSON strings
    _cli_sql.install_connector(a.profile, a.warehouse)
else:
    _cli_sql.install(a.profile, a.warehouse)
STATS = _cli_sql.STATS

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)
GETS = [
    ("close", "/api/close/summary"), ("close", "/api/close/trend"), ("close", "/api/close/tasks"),
    ("close", "/api/close/burndown"), ("close", "/api/close/burndown?period=2026-10"),
    ("checklist", "/api/checklist"), ("checklist", "/api/checklist/CASH-02"), ("checklist", "/api/checklist/SLR-03"),
    ("checklist", "/api/checklist/DQ-02"), ("checklist", "/api/checklist/JET-01"), ("checklist", "/api/checklist/FSC-01"),
    ("exceptions", "/api/exceptions"), ("exceptions", "/api/exceptions?module=M3"),
    ("statements", "/api/statements?statement=IS"), ("statements", "/api/statements?statement=BS&period=2026-10"),
    ("statements", "/api/statements?statement=CF&period=2026-10"), ("statements", "/api/statements/integrity"),
    ("statements", "/api/statements/variances"), ("statements", "/api/statements/drill?line=IS-310&period=2026-10"),
    ("lineage", "/api/lineage/sankey"), ("lineage", "/api/lineage/sankey?level=dataset"), ("lineage", "/api/lineage/datasets"),
    ("lineage", "/api/lineage/feeds"), ("lineage", "/api/lineage/expectations"), ("lineage", "/api/lineage/timeline"),
    ("lineage", "/api/lineage/failing-records?dataset=silver_m3_journal_flags&expectation=ctl_jet_01"),
    ("modules", "/api/modules/cash"), ("modules", "/api/modules/subledger"), ("modules", "/api/modules/journals"),
    ("modules", "/api/modules/access"),
    ("reporting", "/api/reporting/risks"), ("reporting", "/api/reporting/sox-pack"),
    ("architecture", "/api/architecture/status"),
]
only = {x for x in a.only.split(",") if x}
fails = 0
for group, path in GETS:
    if only and group not in only:
        continue
    t0 = time.time()
    try:
        r = client.get(path)
        ok = r.status_code == 200
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text
    except Exception as e:  # noqa: BLE001
        import traceback
        tb = traceback.extract_tb(e.__traceback__)[-1]
        ok, body = False, f"{type(e).__name__}: {e} [at {os.path.basename(tb.filename)}:{tb.lineno} {tb.line}]"
        r = None
    dt = time.time() - t0
    if not ok:
        fails += 1
    size = len(json.dumps(body, default=str))
    print(f"{'PASS' if ok else 'FAIL'} {r.status_code if r is not None else '---'} {path} ({dt:.1f}s, {size} bytes)")
    if not ok or a.verbose:
        print("   ", (json.dumps(body, default=str) if not isinstance(body, str) else body)[:1500])
    if ok and group == "exceptions" and path == "/api/exceptions" and body.get("rows"):
        # One exception per module: each follows different lineage keys to its source rows.
        picks: dict[str, str] = {}
        for row in body["rows"]:
            picks.setdefault(str(row.get("module")), row["exception_id"])
        for mod, eid in sorted(picks.items()):
            try:
                d = client.get(f"/api/exceptions/{eid}")
                dok, dtext = d.status_code == 200, d.text
                if dok and not isinstance(d.json().get("exception", {}).get("lineage", {}), dict):
                    dok, dtext = False, "lineage is not an object"
                code = d.status_code
            except Exception as e:  # noqa: BLE001
                import traceback
                tb = traceback.extract_tb(e.__traceback__)[-1]
                dok, code, dtext = False, "---", f"{type(e).__name__}: {e} [at {os.path.basename(tb.filename)}:{tb.lineno} {tb.line}]"
            print(f"{'PASS' if dok else 'FAIL'} {code} /api/exceptions/{{id}} ({mod} {eid[:10]})")
            if not dok:
                fails += 1
                print("   ", dtext[:1500])
    if ok and path == "/api/lineage/timeline" and isinstance(body, dict):
        upd = next((u.get("test_update_id") for u in body.get("runs", []) if u.get("test_update_id")), None)
        if upd:
            for p2 in (f"/api/lineage/sankey?level=dataset&update_id={upd}", f"/api/lineage/datasets?update_id={upd}"):
                try:
                    d = client.get(p2)
                    dok, code, dtext = d.status_code == 200, d.status_code, d.text
                except Exception as e:  # noqa: BLE001
                    dok, code, dtext = False, "---", f"{type(e).__name__}: {e}"
                print(f"{'PASS' if dok else 'FAIL'} {code} {p2}")
                if not dok:
                    fails += 1
                    print("   ", dtext[:1500])
print(f"\n{fails} failing endpoints; {STATS['queries']} queries, {STATS['seconds']:.0f}s in SQL")
sys.exit(1 if fails else 0)
