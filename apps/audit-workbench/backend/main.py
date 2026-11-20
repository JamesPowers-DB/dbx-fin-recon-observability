"""FastAPI entrypoint for Audit Workbench (Fin Recon Observability).

Databricks Apps (resources/apps.yml config.command):
                             uvicorn backend.main:app --host 0.0.0.0 --port $DATABRICKS_APP_PORT
Local (from apps/audit-workbench):     APP_DEV_ALLOW_ANONYMOUS=1 DATABRICKS_HOST=<host> \
                             DATABRICKS_WAREHOUSE_ID=<id> uv run uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Stash runtime-injected SP credentials under private names, then clear the
# originals so the SDK/connector never sees two auth methods when an OBO
# access_token is passed explicitly. SP-path code reads APP_SP_* afterwards.
for _src, _dst in (("DATABRICKS_CLIENT_ID", "APP_SP_CLIENT_ID"),
                   ("DATABRICKS_CLIENT_SECRET", "APP_SP_CLIENT_SECRET")):
    if os.environ.get(_src):
        os.environ[_dst] = os.environ[_src]
    os.environ.pop(_src, None)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import asyncio

from .lakebase import close_pool, init_pool
from .selfcheck import run_selfcheck
from .routers import (architecture, assistant, checklist, close, exceptions, lineage, modules, reporting, runs,
                      statements, system)

log = logging.getLogger("audit-workbench")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()          # marks Lakebase configured; no connection at startup
    task = asyncio.create_task(run_selfcheck())   # logs SELFCHECK lines; never blocks startup
    yield
    task.cancel()
    await close_pool()


app = FastAPI(title="Audit Workbench", version="0.1.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# API routers first; the SPA mount below catches everything else.
app.include_router(system.router, prefix="/api")
for _r in (runs, close, checklist, exceptions, statements, lineage, modules, reporting, architecture, assistant):
    app.include_router(_r.router, prefix="/api")

_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
else:
    log.warning("Frontend bundle not found at %s; run apps/build_frontends.sh", _DIST)
