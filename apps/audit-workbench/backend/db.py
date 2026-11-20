"""Per-request SQL warehouse access as the calling user (OBO). No pool."""

from __future__ import annotations

import json
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterator
from urllib.parse import urlparse

from databricks import sql as dbsql

from .auth import CallerIdentity
from .config import get_settings

# Shared SQL fragments live in sql_fragments.py. Headline numbers come from
# the gold_mv_* metric views with MEASURE(); detail tables may read gold.


@contextmanager
def warehouse_connection(caller: CallerIdentity) -> Iterator[Any]:
    if caller.is_anonymous:
        raise RuntimeError("Warehouse access needs an OBO token; deploy the app or set a token locally.")
    s = get_settings()
    if not s.warehouse_id or not s.databricks_host:
        raise RuntimeError("DATABRICKS_WAREHOUSE_ID / DATABRICKS_HOST not configured.")
    conn = dbsql.connect(
        server_hostname=urlparse(s.workspace_url).hostname or s.databricks_host,
        http_path=f"/sql/1.0/warehouses/{s.warehouse_id}",
        access_token=caller.access_token,
    )
    try:
        yield conn
    finally:
        conn.close()


_COMPLEX = {"array", "map", "struct"}


def _plain(v: Any) -> Any:
    """Connector value -> plain JSON-ready Python, recursively.

    With pyarrow installed (the Apps runtime has it), databricks-sql-connector returns
    ARRAY as numpy.ndarray (`x or []` raises "truth value ... is ambiguous", and
    pydantic cannot serialize it), MAP as a list of (key, value) tuples, and STRUCT as
    a dict that may hold both. DECIMAL -> float: pydantic v2 serializes Decimal as a
    JSON string, which breaks numeric math in the frontend.
    """
    if v is None or isinstance(v, (str, bool, int, float)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "tolist"):  # numpy.ndarray or numpy scalar
        return _plain(v.tolist())
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        if v and all(isinstance(x, tuple) and len(x) == 2 for x in v):  # nested MAP
            return {k: _plain(x) for k, x in v}
        return [_plain(x) for x in v]
    if isinstance(v, tuple):
        return [_plain(x) for x in v]
    return v  # date, datetime, bytes


def _column(v: Any, type_code: Any) -> Any:
    t = str(type_code or "").lower()
    if t in _COMPLEX and isinstance(v, str):  # connector without pyarrow: JSON text
        v = json.loads(v)
    v = _plain(v)
    if t == "map" and v == []:  # an empty MAP arrives as an empty list
        return {}
    return v


def fetch_all(caller: CallerIdentity, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    # Bind only str/int params (qmark). Dates bind unreliably: compute them in SQL.
    # Every value is normalized by _column(): ARRAY -> list, MAP/STRUCT -> dict,
    # DECIMAL -> float, whichever way the connector delivered it.
    with warehouse_connection(caller) as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])
        desc = cur.description or []
        cols = [d[0] for d in desc]
        types = [d[1] for d in desc]
        return [{c: _column(v, t) for c, t, v in zip(cols, types, row)} for row in cur.fetchall()]


def fetch_one(caller: CallerIdentity, sql: str, params: list[Any] | None = None) -> dict[str, Any] | None:
    rows = fetch_all(caller, sql, params)
    return rows[0] if rows else None


def execute(caller: CallerIdentity, sql: str, params: list[Any] | None = None) -> None:
    with warehouse_connection(caller) as conn, conn.cursor() as cur:
        cur.execute(sql, params or [])


def fetch_many(caller: CallerIdentity, queries: dict[str, tuple[str, list[Any] | None] | str],
               max_workers: int = 6) -> dict[str, list[dict[str, Any]]]:
    """Run a page's independent queries in parallel (one OBO connection each)."""
    from concurrent.futures import ThreadPoolExecutor

    def run(item):
        name, q = item
        sql, params = (q, None) if isinstance(q, str) else q
        return name, fetch_all(caller, sql, params)

    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(queries)))) as ex:
        return dict(ex.map(run, queries.items()))
