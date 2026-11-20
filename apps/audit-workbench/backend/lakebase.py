"""Lakebase Postgres for app-owned operational state.

Holds only human actions and conversation state: review actions (append-only),
working papers, chat sessions. Analytics stay in Unity Catalog. The
`snapshot_review_state` task of run_controls copies review actions into
`meta_review_actions` (one-way); the app never writes UC.

Connection: the app's `postgres` resource binding (resources/apps.yml) gives
the service principal a Postgres role (PGUSER = SP client id) with CONNECT +
CREATE on the database and injects PGHOST/PGDATABASE/PGPORT/PGSSLMODE. A
short-lived OAuth credential is minted per connection. Human attribution
(actor_email) is recorded from the OBO caller, never from the connecting role.
DDL runs once, lazily, on the first request.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import psycopg

from .config import get_settings
from .sp import sp_client

log = logging.getLogger("audit-workbench.lakebase")
_configured = False
_ddl_done = False
_ddl_lock = asyncio.Lock()

SCHEMA = "audit"

DDL_FILE = Path(__file__).with_name("review_store.sql")


def ddl_statements(text: str | None = None) -> list[str]:
    """Split the shared DDL into statements (comment lines dropped)."""
    text = text if text is not None else DDL_FILE.read_text()
    body = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    return [x.strip() for x in body.split(";") if x.strip()]


def _conninfo() -> str:
    s = get_settings()
    cred = sp_client().postgres.generate_database_credential(endpoint=s.lakebase_endpoint)
    return (f"host={s.pg_host} port={s.pg_port} dbname={s.pg_database} "
            f"user={s.pg_user} password={cred.token} sslmode={s.pg_sslmode}")


async def init_pool() -> None:
    global _configured
    s = get_settings()
    if not (s.pg_host and s.pg_user and s.lakebase_endpoint):
        log.warning("Lakebase binding not present (PGHOST/PGUSER/LAKEBASE_ENDPOINT); review state unavailable.")
        return
    _configured = True
    log.info("Lakebase configured (%s, db=%s); DDL runs on first request.", s.pg_host, s.pg_database)


async def close_pool() -> None:
    global _configured, _ddl_done
    _configured = _ddl_done = False


def is_configured() -> bool:
    return _configured


async def _ensure_ddl() -> None:
    global _ddl_done
    if _ddl_done:
        return
    async with _ddl_lock:
        if _ddl_done:
            return
        conninfo = await asyncio.to_thread(_conninfo)
        async with await psycopg.AsyncConnection.connect(conninfo, autocommit=True) as conn:
            for stmt in ddl_statements():
                try:
                    await conn.execute(stmt)
                except psycopg.errors.InsufficientPrivilege as e:
                    # Created by another role (the setup job on a fresh install); usable via its grants.
                    log.info("DDL skipped (%s): %s", type(e).__name__, stmt.split("(")[0][:80])
        _ddl_done = True


@asynccontextmanager
async def db_conn() -> AsyncIterator[psycopg.AsyncConnection]:
    if not _configured:
        raise RuntimeError("Lakebase is not configured for this app (missing postgres resource binding).")
    await _ensure_ddl()
    conninfo = await asyncio.to_thread(_conninfo)
    async with await psycopg.AsyncConnection.connect(conninfo) as conn:
        yield conn
