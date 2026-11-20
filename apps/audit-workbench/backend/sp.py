"""App service principal client.

Used only for platform calls that have no OBO user scope: triggering and
reading job runs (the app binds run_controls and simulate_activity with
CAN_MANAGE_RUN) and minting Lakebase credentials for the SP's Postgres role.
Every UC data read stays on the caller's OBO token.
"""

from __future__ import annotations

from functools import lru_cache

from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config

from .config import get_settings


@lru_cache
def sp_client() -> WorkspaceClient:
    s = get_settings()
    if not (s.sp_client_id and s.sp_client_secret):
        raise RuntimeError("App service principal credentials are not available (local mode).")
    return WorkspaceClient(config=Config(host=s.workspace_url, client_id=s.sp_client_id,
                                         client_secret=s.sp_client_secret))
