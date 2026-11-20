"""Trigger and observe control runs.

There is no OBO user scope for Jobs, so the app service principal makes these
calls. It holds CAN_MANAGE_RUN on run_controls and simulate_activity through
app resource bindings. The caller is recorded as `requested_by` in the job
parameters, which land in the run ledger (meta_control_runs).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CallerIdentity, caller_identity
from ..config import get_settings
from ..models import RunStatusResponse, RunTask, RunTriggerRequest, RunTriggerResponse
from ..sp import sp_client

log = logging.getLogger("audit-workbench.runs")
router = APIRouter(tags=["runs"])

_ACTIVE = {"PENDING", "QUEUED", "RUNNING", "TERMINATING", "BLOCKED", "WAITING_FOR_RETRY"}


def _enum(v) -> str | None:
    return None if v is None else getattr(v, "value", str(v))


def _active_run_id(w, job_id: int) -> int | None:
    for r in w.jobs.list_runs(job_id=job_id, active_only=True, limit=5):
        return r.run_id
    return None


@router.post("/runs", response_model=RunTriggerResponse)
def trigger_run(body: RunTriggerRequest, caller: CallerIdentity = Depends(caller_identity)) -> RunTriggerResponse:
    s = get_settings()
    if body.kind == "run_controls":
        job_id = s.run_controls_job_id
        params = {"trigger_source": "app", "requested_by": caller.email,
                  "reason": (body.reason or "Re-run from Audit Workbench")[:200]}
    elif body.kind == "simulate":
        job_id = s.simulate_job_id
        params = {"requested_by": caller.email, "scenario": body.scenario or "auto"}
    else:
        raise HTTPException(400, f"Unknown run kind: {body.kind}")
    if not job_id:
        raise HTTPException(503, f"Job id for '{body.kind}' is not configured (app resource binding missing).")
    w = sp_client()
    # One run at a time: if the job is already running, hand back that run
    # instead of queueing a duplicate behind it.
    active = _active_run_id(w, int(job_id))
    if active:
        run = w.jobs.get_run(active)
        return RunTriggerResponse(job_id=str(job_id), run_id=active, run_page_url=run.run_page_url or "")
    waiter = w.jobs.run_now(job_id=int(job_id), job_parameters=params)
    run_id = waiter.response.run_id
    run = w.jobs.get_run(run_id)
    log.info("triggered %s run %s for %s", body.kind, run_id, caller.email)
    return RunTriggerResponse(job_id=str(job_id), run_id=run_id, run_page_url=run.run_page_url or "")


@router.get("/runs/active")
def active_runs(caller: CallerIdentity = Depends(caller_identity)) -> dict:
    """Runs in flight (started by anyone: app, schedule, setup) so every viewer sees the same stepper."""
    s = get_settings()
    try:
        w = sp_client()
    except Exception as e:  # noqa: BLE001 - no SP credentials (local dev): report no runs instead of failing the page
        log.warning("active run lookup unavailable: %s", e)
        return {"run_controls": None, "simulate": None}
    out = {}
    for kind, jid in (("run_controls", s.run_controls_job_id), ("simulate", s.simulate_job_id)):
        try:
            out[kind] = _active_run_id(w, int(jid)) if jid else None
        except Exception as e:  # noqa: BLE001
            log.warning("active run lookup failed for %s: %s", kind, e)
            out[kind] = None
    return out


@router.get("/runs/{run_id}", response_model=RunStatusResponse)
def run_status(run_id: int, caller: CallerIdentity = Depends(caller_identity)) -> RunStatusResponse:
    w = sp_client()
    try:
        r = w.jobs.get_run(run_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"Run {run_id} not readable by the app: {e}") from e
    st = r.state
    tasks = [RunTask(task_key=t.task_key, state=_enum(t.state.life_cycle_state) if t.state else "UNKNOWN",
                     result_state=_enum(t.state.result_state) if t.state else None,
                     start_time=t.start_time or None, end_time=t.end_time or None)
             for t in (r.tasks or [])]
    return RunStatusResponse(run_id=run_id, life_cycle_state=_enum(st.life_cycle_state) if st else "UNKNOWN",
                             result_state=_enum(st.result_state) if st else None,
                             state_message=st.state_message if st else None,
                             start_time=r.start_time or None, end_time=r.end_time or None,
                             run_page_url=r.run_page_url or "", tasks=tasks)
