"""Small helpers shared by routers: safe identifiers, period defaults, deep links."""

from __future__ import annotations

import re
from datetime import date, timedelta

from fastapi import HTTPException

from .config import get_settings

_PERIOD = re.compile(r"^\d{4}-\d{2}$")
_CODE = re.compile(r"^[A-Za-z0-9_\-|:.+ ]{1,120}$")


def fq(table: str) -> str:
    return f"{get_settings().fq}.{table}"


def active_period() -> str:
    return date.today().strftime("%Y-%m")


def prev_period(p: str) -> str:
    y, m = int(p[:4]), int(p[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def period_or_active(p: str | None) -> str:
    if not p:
        return active_period()
    if not _PERIOD.match(p):
        raise HTTPException(400, f"Invalid period '{p}' (expected yyyy-MM)")
    return p


def safe_code(v: str | None, what: str = "value") -> str | None:
    if v is None or v == "":
        return None
    if not _CODE.match(v):
        raise HTTPException(400, f"Invalid {what}")
    return v


def links() -> dict[str, str]:
    """Workspace deep-link templates the UI fills in (job/run/pipeline/table)."""
    s = get_settings()
    base = s.workspace_url
    return {
        "job_run": f"{base}/jobs/{{job_id}}/runs/{{run_id}}",
        "pipeline_update": f"{base}/pipelines/{s.pipeline_id}/updates/{{update_id}}",
        "pipeline": f"{base}/pipelines/{s.pipeline_id}",
        "table": f"{base}/explore/data/{s.catalog}/{s.schema}/{{table}}",
        "workspace_file": (f"{base}/#workspace{s.bundle_file_path}/{{path}}" if s.bundle_file_path
                           else f"{base}/#workspace/{{path}}"),
    }


def cutoff() -> date:
    return date.today() - timedelta(days=1)
