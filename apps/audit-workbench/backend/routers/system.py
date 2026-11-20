"""System endpoints: health, identity, non-secret config, Lakebase probe."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import lakebase
from ..auth import CallerIdentity, caller_identity
from ..config import get_settings
from ..models import AppConfigResponse, HealthResponse, MeResponse

router = APIRouter(tags=["system"])


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/me", response_model=MeResponse)
def me(caller: CallerIdentity = Depends(caller_identity)) -> MeResponse:
    return MeResponse(email=caller.email, display_name=caller.display_name, initials=caller.initials)


@router.get("/config", response_model=AppConfigResponse)
def config(caller: CallerIdentity = Depends(caller_identity)) -> AppConfigResponse:
    """Non-secret settings the UI needs to build deep links into the workspace."""
    s = get_settings()
    return AppConfigResponse(catalog=s.catalog, schema=s.schema, workspace_url=s.workspace_url,
                             run_controls_job_id=s.run_controls_job_id, simulate_job_id=s.simulate_job_id,
                             pipeline_id=s.pipeline_id)


@router.get("/system/lakebase")
async def lakebase_probe(caller: CallerIdentity = Depends(caller_identity)) -> dict:
    """Connectivity probe for the review-state store (runs the lazy DDL)."""
    if not lakebase.is_configured():
        raise HTTPException(503, "Lakebase binding not configured for this app.")
    try:
        async with lakebase.db_conn() as conn:
            cur = await conn.execute(
                "SELECT current_user, current_database(), "
                "(SELECT COUNT(*) FROM audit.review_actions) AS review_actions")
            row = await cur.fetchone()
        return {"status": "ok", "role": row[0], "database": row[1], "review_actions": row[2]}
    except Exception as e:  # noqa: BLE001 - surface the reason to the probe caller
        raise HTTPException(503, f"Lakebase probe failed: {type(e).__name__}: {e}") from e
