"""Close Cockpit: days to close (north star), burndown, task progress, lifecycle strip.

Task status comes from meta_close_task_status, written by run_controls.record_results
(no status is computed here). The burndown arithmetic below only turns task due
and completion days into a series for the chart.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import lakebase
from ..auth import CallerIdentity, caller_identity
from ..db import fetch_all, fetch_many
from ..sqlutil import active_period, fq, period_or_active, prev_period

router = APIRouter(prefix="/close", tags=["close"])


@router.get("/summary")
def summary(caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p, pp = active_period(), prev_period(active_period())
    r = fetch_many(caller, {
        "last": (f"SELECT MEASURE(days_to_close) AS v FROM {fq('gold_mv_close')} WHERE period = ?", [pp]),
        "active": (f"""SELECT MEASURE(projected_days_to_close) AS projected, MEASURE(pre_close_completion_pct) AS pre_close,
                       MEASURE(tasks_complete_pct) AS tasks_pct, MEASURE(tasks_complete) AS tasks_complete,
                       MEASURE(tasks_total) AS tasks_total, MEASURE(tasks_overdue) AS overdue, MEASURE(tasks_blocked) AS blocked,
                       MEASURE(target_days_to_close) AS target, MEASURE(traditional_days_to_close) AS traditional
                       FROM {fq('gold_mv_close')} WHERE period = ?""", [p]),
        "trad": (f"""SELECT MEASURE(days_to_close) AS v FROM {fq('gold_mv_close')}
                     WHERE period_status = 'CLOSED' AND fiscal_year = 2025""", None),
        "controls": (f"""SELECT MEASURE(control_pass_rate) AS pass_rate, MEASURE(controls_failed) AS failed,
                         MEASURE(key_controls_failed) AS key_failed, MEASURE(records_tested) AS records_tested,
                         MEASURE(traditional_sample) AS traditional_sample, MEASURE(controls_executed) AS executed
                         FROM {fq('gold_mv_control_health')} WHERE is_latest_run = true AND period = ?""", [p]),
        "exceptions": (f"""SELECT MEASURE(open_exceptions) AS open, MEASURE(exceptions) AS total,
                           MEASURE(ai_triage_coverage_pct) AS triage_pct, MEASURE(critical_open_exceptions) AS critical,
                           MEASURE(dispositioned_pct) AS dispositioned_pct, MEASURE(evidence_attached_pct) AS evidence_pct
                           FROM {fq('gold_mv_exceptions')} WHERE period = ?""", [p]),
        "recon": (f"""SELECT MEASURE(unreconciled_amount_usd) AS unreconciled, MEASURE(breaks) AS breaks
                      FROM {fq('gold_mv_reconciliations')} WHERE period = ?""", [p]),
        "feeds": (f"""SELECT count(*) AS feeds, sum(CASE WHEN within_sla THEN 1 ELSE 0 END) AS fresh
                      FROM {fq('gold_dq_feed_status')}""", None),
        # Last completed run (the stepper shows a run in flight).
        "run": (f"""SELECT * FROM {fq('meta_control_runs')} WHERE status IS NOT NULL AND status <> 'RUNNING'
                    ORDER BY started_at DESC LIMIT 1""", None),
        "today": (f"""SELECT max(today_close_day) AS today_t FROM {fq('meta_close_task_status')} WHERE period = ?""", [p]),
    })
    a = (r["active"] or [{}])[0]
    c = (r["controls"] or [{}])[0]
    e = (r["exceptions"] or [{}])[0]
    run = (r["run"] or [None])[0]
    triaged = round((e.get("triage_pct") or 0) * (e.get("total") or 0))
    dispositioned = round((e.get("dispositioned_pct") or 0) * (e.get("total") or 0))
    feeds = (r["feeds"] or [{}])[0]
    lifecycle = [
        {"stage": "Enterprise data", "value": f"{int(feeds.get('fresh') or 0)}/{int(feeds.get('feeds') or 0)}", "caption": "feeds within SLA", "page": "lineage"},
        {"stage": "Automated monitoring", "value": int(c.get("executed") or 0), "caption": "controls run", "page": "checklist"},
        {"stage": "Exception detection", "value": int(e.get("total") or 0), "caption": "exceptions found", "page": "exceptions"},
        {"stage": "AI investigation", "value": triaged, "caption": "AI-triaged", "page": "exceptions"},
        {"stage": "Evidence capture", "value": f"{round(100 * (e.get('evidence_pct') or 0))}%", "caption": "evidence on file", "page": "exceptions"},
        {"stage": "Human review", "value": dispositioned, "caption": "dispositioned", "page": "exceptions"},
        {"stage": "Reporting", "value": f"{int(a.get('tasks_complete') or 0)}/{int(a.get('tasks_total') or 0)}", "caption": "close tasks done", "page": "reporting"},
    ]
    return {
        "active_period": p, "last_closed_period": pp,
        "today_close_day": (r["today"] or [{}])[0].get("today_t"),
        "days_to_close_last": (r["last"] or [{}])[0].get("v"),
        "days_to_close_traditional": (r["trad"] or [{}])[0].get("v"),
        "projected_days_to_close": a.get("projected"), "target_days_to_close": a.get("target") or 3,
        "north_star_days_to_close": 1, "pre_close_completion_pct": a.get("pre_close"),
        "tasks_complete_pct": a.get("tasks_pct"), "tasks_complete": a.get("tasks_complete"), "tasks_total": a.get("tasks_total"),
        "tasks_overdue": a.get("overdue"), "tasks_blocked": a.get("blocked"),
        "control_pass_rate": c.get("pass_rate"), "controls_failed": c.get("failed"), "key_controls_failed": c.get("key_failed"),
        "records_tested": c.get("records_tested"), "traditional_sample": c.get("traditional_sample"),
        "open_exceptions": e.get("open"), "critical_open_exceptions": e.get("critical"), "ai_triage_coverage_pct": e.get("triage_pct"),
        "unreconciled_amount_usd": (r["recon"] or [{}])[0].get("unreconciled"),
        "lifecycle": lifecycle, "latest_run": run,
    }


@router.get("/trend")
def trend(caller: CallerIdentity = Depends(caller_identity)) -> list[dict]:
    return fetch_all(caller, f"""
        SELECT period, period_status, MEASURE(projected_days_to_close) AS days_to_close,
               MEASURE(pre_close_completion_pct) AS pre_close_completion_pct, MEASURE(target_days_to_close) AS target
        FROM {fq('gold_mv_close')} GROUP BY period, period_status ORDER BY period""")


@router.get("/tasks")
def tasks(period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> list[dict]:
    p = period_or_active(period)
    return fetch_all(caller, f"""SELECT * FROM {fq('meta_close_task_status')} WHERE period = ?
                                 ORDER BY due_offset_bd, task_code""", [p])


@router.get("/burndown")
def burndown(period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    r = fetch_many(caller, {
        "tasks": (f"SELECT * FROM {fq('meta_close_task_status')} WHERE period = ?", [p]),
        "trad": (f"""SELECT task_code, avg(completed_close_day) AS d FROM {fq('meta_close_task_status')}
                     WHERE period_status = 'CLOSED' AND period LIKE '2025-%' GROUP BY task_code""", None),
        "per": (f"SELECT * FROM {fq('gold_dim_period')} WHERE period = ?", [p]),
    })
    t = r["tasks"]
    if not t:
        raise HTTPException(404, f"No close tasks for {p}. Run run_controls to derive the close status.")
    per = r["per"][0]
    end_seq = int(per["bd_seq_at_period_end"])
    days = fetch_all(caller, f"""SELECT cal_date, bd_seq FROM {fq('gold_dim_business_day')}
                                 WHERE is_business_day AND bd_seq BETWEEN ? AND ? ORDER BY cal_date""", [end_seq - 12, end_seq + 9])
    is_active = per["status"] == "ACTIVE"
    today_t = t[0].get("today_close_day") if is_active else None
    total = len(t)
    target_t = int(t[0].get("target_days_to_close") or 3)
    trad = {x["task_code"]: x["d"] for x in r["trad"]}
    points = []
    for d in days:
        k = int(d["bd_seq"]) - end_seq
        planned = sum(1 for x in t if int(x["due_offset_bd"]) > k)
        traditional = sum(1 for x in t if (trad.get(x["task_code"]) or x["traditional_due_bd"]) > k)
        done = sum(1 for x in t if x["completed_close_day"] is not None and int(x["completed_close_day"]) <= k)
        actual = (total - done) if (not is_active or (today_t is not None and k <= today_t)) else None
        projected = None
        if is_active and today_t is not None and k >= today_t:
            projected = sum(1 for x in t if x["completed_close_day"] is None
                            and (x["projected_close_day"] is None or int(x["projected_close_day"]) > k))
        points.append({"date": str(d["cal_date"]), "t": k, "planned": planned, "traditional": traditional,
                       "actual": actual, "projected": projected})
    completed = sum(1 for x in t if x["status"] == "COMPLETE")
    cls12 = next((x for x in t if x["task_code"] == "CLS-12"), {})
    projected_t = cls12.get("completed_close_day") if cls12.get("completed_close_day") is not None else cls12.get("projected_close_day")
    return {"period": p, "status": per["status"], "points": points, "total": total, "completed": completed,
            "remaining": total - completed, "pct_complete": completed / total if total else 0, "today_t": today_t,
            "target_t": target_t, "projected_t": projected_t, "on_track": projected_t is not None and projected_t <= target_t,
            "traditional_t": round(max(trad.values())) if trad else 8}


class SignoffIn(BaseModel):
    period: str
    role: str = "reviewer"
    comment: str = ""


@router.post("/tasks/{task_code}/signoff")
async def signoff(task_code: str, body: SignoffIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(body.period)
    if not lakebase.is_configured():
        raise HTTPException(503, "Review store (Lakebase) is not configured for this app.")
    async with lakebase.db_conn() as conn:
        await conn.execute(
            f"""INSERT INTO {lakebase.SCHEMA}.review_actions (action_id, item_type, item_key, period, action, comment,
                  actor_email, actor_role, created_at) VALUES (%s, 'close_task', %s, %s, 'signoff', %s, %s, %s, now())""",
            (uuid.uuid4().hex, f"{p}|{task_code}", p, body.comment[:2000], caller.email, body.role))
        await conn.commit()
    return {"status": "recorded", "task_code": task_code, "period": p,
            "note": "Sign-off recorded. The next control run (Re-run controls) applies it to the close status."}


@router.get("/today")
def today() -> dict:
    return {"date": date.today().isoformat(), "active_period": active_period()}
