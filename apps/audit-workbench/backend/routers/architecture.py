"""Architecture: live status for every node of the platform map.

The map itself (business lifecycle -> deployed assets -> Databricks features,
feasibility tiers, GRC workflow parity, briefing coverage) is static content in
the frontend. This router answers "is that asset deployed and what did it last
do", node by node, so every box on the map links to something real. Each probe
is independent; one failing probe returns an error for that node only.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from fastapi import APIRouter, Depends

from .. import genie, lakebase
from ..auth import CallerIdentity, caller_identity
from ..config import get_settings
from ..db import fetch_all
from ..sp import sp_client
from ..sqlutil import fq, links

router = APIRouter(prefix="/architecture", tags=["architecture"])


def _job(job_id: str) -> dict:
    """Latest run of a job the app SP can see. Raises when the binding is missing,
    so the probe reports ok=false for that node only."""
    if not job_id:
        raise RuntimeError("job resource binding missing (no job id in the app environment)")
    w = sp_client()
    runs = list(w.jobs.list_runs(job_id=int(job_id), limit=1))
    if not runs:
        return {"job_id": job_id, "last_run": None}
    r = runs[0]
    st = r.state
    return {"job_id": job_id, "last_run": {
        "run_id": r.run_id, "start_time": r.start_time, "end_time": r.end_time or None, "run_page_url": r.run_page_url,
        "state": getattr(st.life_cycle_state, "value", None) if st else None,
        "result": getattr(st.result_state, "value", None) if st and st.result_state else None}}


def _sql(caller: CallerIdentity, sql: str, params: list | None = None) -> Callable[[], Any]:
    return lambda: fetch_all(caller, sql, params)


@router.get("/status")
async def status(caller: CallerIdentity = Depends(caller_identity)) -> dict:
    s = get_settings()
    probes: dict[str, Callable[[], Any]] = {
        "sources": _sql(caller, f"""SELECT dataset, rows_in_table FROM {fq('meta_pipeline_update_metrics')}
                                   WHERE layer = 'bronze' AND update_id = (SELECT max_by(update_id, recorded_at)
                                                                          FROM {fq('meta_pipeline_update_metrics')})"""),
        "pipeline": _sql(caller, f"""SELECT update_id, max_by(job_run_id, recorded_at) AS job_run_id, max(recorded_at) AS recorded_at, count(*) AS datasets,
                                            sum(rows_written) AS rows_written, sum(failed_records) AS failed_records
                                     FROM {fq('meta_pipeline_update_metrics')} GROUP BY update_id ORDER BY recorded_at DESC LIMIT 1"""),
        "library": _sql(caller, f"""SELECT count(*) AS controls, count(DISTINCT module) AS modules, max(published_at) AS published_at,
                                           sum(CASE WHEN key_control THEN 1 ELSE 0 END) AS key_controls
                                    FROM {fq('gold_dim_control')}"""),
        "ledger": _sql(caller, f"SELECT * FROM {fq('meta_control_runs')} ORDER BY started_at DESC LIMIT 1"),
        "tables": _sql(caller, f"""SELECT CASE WHEN table_name LIKE 'gold_mv_%' THEN 'metric_view' ELSE split(table_name, '_')[0] END AS layer,
                                          count(*) AS n
                                   FROM {s.catalog}.information_schema.tables
                                   WHERE table_schema = ? AND left(table_name, 1) <> '_' GROUP BY 1""", [s.schema]),
        "triage": _sql(caller, f"""SELECT count(*) AS triaged, max(triaged_at) AS last_triaged_at, max(model) AS model
                                   FROM {fq('ml_exception_triage')}"""),
        "documents": _sql(caller, f"""SELECT count(*) AS parsed FROM {fq('silver_document_parsed')}"""),
        "tags": _sql(caller, f"""SELECT count(*) AS tagged FROM {s.catalog}.information_schema.table_tags WHERE schema_name = ?""", [s.schema]),
        "run_controls": lambda: _job(s.run_controls_job_id),
        "simulate": lambda: _job(s.simulate_job_id),
        "refresh": lambda: _job(s.refresh_job_id),
        "genie": lambda: {"space_id": genie.resolve_space_id(caller), "title": s.genie_space_title},
    }

    def run(item):
        name, fn = item
        try:
            return name, {"ok": True, "data": fn()}
        except Exception as e:  # noqa: BLE001 - one probe must not hide the rest
            return name, {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = dict(await asyncio.gather(*[loop.run_in_executor(ex, run, it) for it in probes.items()]))

    lb: dict[str, Any] = {"ok": False, "error": "not configured"}
    if lakebase.is_configured():
        try:
            async with lakebase.db_conn() as conn:
                cur = await conn.execute(f"""SELECT (SELECT count(*) FROM {lakebase.SCHEMA}.review_actions),
                                                    (SELECT count(*) FROM {lakebase.SCHEMA}.working_papers),
                                                    (SELECT count(*) FROM {lakebase.SCHEMA}.chatbot_sessions)""")
                a, b, c = await cur.fetchone()
            lb = {"ok": True, "data": {"review_actions": a, "working_papers": b, "chat_sessions": c,
                                       "endpoint": s.lakebase_endpoint}}
        except Exception as e:  # noqa: BLE001
            lb = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
    results["lakebase"] = lb
    base = s.workspace_url
    results["assets"] = {"ok": True, "data": {
        "dashboard_url": f"{base}/dashboardsv3/{s.dashboard_id}/published" if s.dashboard_id else None,
        "genie_url": f"{base}/genie/rooms/{results['genie'].get('data', {}).get('space_id')}"
        if results["genie"].get("ok") and results["genie"]["data"].get("space_id") else None,
        "pipeline_url": f"{base}/pipelines/{s.pipeline_id}" if s.pipeline_id else None,
        "schema_url": f"{base}/explore/data/{s.catalog}/{s.schema}",
        "alerts_url": f"{base}/sql/alerts",
        "lakebase_project": s.lakebase_endpoint.split("/")[1] if s.lakebase_endpoint.count("/") >= 1 else None,
        "run_controls_url": f"{base}/jobs/{s.run_controls_job_id}" if s.run_controls_job_id else None,
        "refresh_url": f"{base}/jobs/{s.refresh_job_id}" if s.refresh_job_id else None,
        "agent_endpoint": s.serving_endpoint_name, "triage_endpoint": s.triage_endpoint_name,
        "agent_endpoint_url": f"{base}/ml/endpoints/{s.serving_endpoint_name}",
        "catalog": s.catalog, "schema": s.schema}}
    results["links"] = links()
    return results
