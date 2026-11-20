"""Startup self-check: proves the app service principal's platform access.

Runs once in the background after startup and logs one line per probe, so
`databricks apps logs` shows whether the deployment is wired correctly:
  jobs.get / jobs.list_runs on run_controls   (CAN_MANAGE_RUN binding)
  jobs.run_now on run_controls                 (only when APP_SELF_CHECK=trigger)
  Lakebase connect + lazy DDL + SELECT          (postgres binding)
Mode from APP_SELF_CHECK: off | read (default) | trigger.
"""

from __future__ import annotations

import asyncio
import logging
import os

from . import lakebase
from .config import get_settings
from .sp import sp_client

log = logging.getLogger("audit-workbench.selfcheck")


def _jobs_probe(trigger: bool) -> None:
    s = get_settings()
    w = sp_client()
    for label, jid in (("run_controls", s.run_controls_job_id), ("simulate_activity", s.simulate_job_id)):
        if not jid:
            log.warning("SELFCHECK jobs.%s: job id env missing", label)
            continue
        try:
            j = w.jobs.get(int(jid))
            runs = list(w.jobs.list_runs(job_id=int(jid), limit=1))
            log.info("SELFCHECK jobs.%s: OK get name=%s, list_runs=%d", label, j.settings.name, len(runs))
        except Exception as e:  # noqa: BLE001
            log.error("SELFCHECK jobs.%s: FAIL %s: %s", label, type(e).__name__, e)
    if trigger and s.run_controls_job_id:
        try:
            r = w.jobs.run_now(job_id=int(s.run_controls_job_id),
                               job_parameters={"trigger_source": "app", "requested_by": "app-selfcheck",
                                               "reason": "App self-check (run_now)"})
            log.info("SELFCHECK jobs.run_now: OK run_id=%s", r.response.run_id)
        except Exception as e:  # noqa: BLE001
            log.error("SELFCHECK jobs.run_now: FAIL %s: %s", type(e).__name__, e)


async def _lakebase_probe() -> None:
    if not lakebase.is_configured():
        log.warning("SELFCHECK lakebase: not configured (binding env missing)")
        return
    try:
        async with lakebase.db_conn() as conn:
            cur = await conn.execute("SELECT current_user, current_database(), "
                                     "(SELECT COUNT(*) FROM audit.review_actions)")
            row = await cur.fetchone()
        log.info("SELFCHECK lakebase: OK role=%s db=%s review_actions=%s", row[0], row[1], row[2])
    except Exception as e:  # noqa: BLE001
        log.error("SELFCHECK lakebase: FAIL %s: %s", type(e).__name__, e)


async def run_selfcheck() -> None:
    mode = os.environ.get("APP_SELF_CHECK", "read").lower()
    if mode == "off":
        return
    await asyncio.sleep(2)
    try:
        await asyncio.to_thread(_jobs_probe, mode == "trigger")
    except Exception as e:  # noqa: BLE001
        log.error("SELFCHECK jobs: FAIL %s: %s", type(e).__name__, e)
    await _lakebase_probe()
