"""Route the app's warehouse calls through the Statement Execution API via the Databricks
CLI profile (local dev only; no token in this process). Used by smoke_api.py and serve_local.py."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import time
from datetime import date, datetime

PROFILE = WAREHOUSE = ""


class _A:
    profile = ""
    warehouse = ""


a = _A()

STATS = {"queries": 0, "seconds": 0.0}


def _conv(v, t):
    if v is None:
        return None
    t = (t or "").upper()
    if t in ("INT", "LONG", "SHORT", "BYTE", "BIGINT", "SMALLINT", "TINYINT"):
        return int(v)
    if t in ("DOUBLE", "FLOAT", "DECIMAL"):
        return float(v)
    if t == "BOOLEAN":
        return v in (True, "true")
    if t in ("ARRAY", "MAP", "STRUCT"):
        return json.loads(v)
    if t == "TIMESTAMP":
        return datetime.fromisoformat(v.replace("Z", "").split("+")[0])
    if t == "DATE":
        return date.fromisoformat(v)
    return v


def fetch_all(caller, sql, params=None):
    params = list(params or [])
    i = iter(range(len(params)))
    stmt = re.sub(r"\?", lambda m: f":p{next(i)}", sql)
    body = {"warehouse_id": a.warehouse, "statement": stmt, "wait_timeout": "50s", "on_wait_timeout": "CONTINUE",
            "format": "JSON_ARRAY", "disposition": "INLINE",
            "parameters": [{"name": f"p{k}", "value": str(v), "type": "INT" if isinstance(v, int) else "STRING"}
                           for k, v in enumerate(params)]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(body, f)
    t0 = time.time()
    out = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements", "--json", f"@{f.name}", "--profile", a.profile],
                         capture_output=True, text=True)
    r = json.loads(out.stdout or "{}")
    while r.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(1)
        r = json.loads(subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{r['statement_id']}",
                                       "--profile", a.profile], capture_output=True, text=True).stdout)
    STATS["queries"] += 1
    STATS["seconds"] += time.time() - t0
    if r.get("status", {}).get("state") != "SUCCEEDED":
        msg = (r.get("status", {}).get("error") or {}).get("message") or out.stderr or str(r)[:300]
        raise RuntimeError(f"SQL failed: {msg[:600]}\n--- statement ---\n{stmt[:1500]}")
    cols = r.get("manifest", {}).get("schema", {}).get("columns", [])
    rows = r.get("result", {}).get("data_array") or []
    return [{c["name"]: _conv(v, c.get("type_name")) for c, v in zip(cols, row)} for row in rows]





def install_connector(profile: str, warehouse: str) -> None:
    """Keep the app's real fetch_all and run it on databricks-sql-connector, as deployed.

    Only the connection is swapped: auth comes from the CLI profile through the SDK
    (no token in this process). Install the connector with pyarrow, which the Apps
    runtime has: ARRAY then arrives as numpy.ndarray and MAP as a list of tuples,
    the types the Statement Execution shim above never produces."""
    from contextlib import contextmanager

    from databricks import sql as dbsql
    from databricks.sdk.core import Config

    cfg = Config(profile=profile)
    host = cfg.host.replace("https://", "").rstrip("/")

    @contextmanager
    def warehouse_connection(caller):  # noqa: ARG001 - local identity, profile auth
        conn = dbsql.connect(server_hostname=host, http_path=f"/sql/1.0/warehouses/{warehouse}",
                             credentials_provider=lambda: cfg.authenticate)
        t0 = time.time()
        try:
            yield conn
        finally:
            conn.close()
            STATS["queries"] += 1
            STATS["seconds"] += time.time() - t0

    from backend import db
    db.warehouse_connection = warehouse_connection


def install(profile: str, warehouse: str) -> None:
    """Patch backend.db and every router's imported fetch_all/fetch_one."""
    a.profile, a.warehouse = profile, warehouse
    from backend import db
    db.fetch_all = fetch_all
    db.fetch_one = lambda c, s, p=None: (fetch_all(c, s, p) or [None])[0]
    from backend.routers import (architecture, assistant, checklist, close, exceptions, lineage, modules,
                                 reporting, statements)
    for mod in (architecture, assistant, checklist, close, exceptions, lineage, modules, reporting, statements):
        if hasattr(mod, "fetch_all"):
            mod.fetch_all = fetch_all
        if hasattr(mod, "fetch_one"):
            mod.fetch_one = db.fetch_one
