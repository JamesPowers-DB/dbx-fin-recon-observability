"""Audit Checklist: every control, bound to the run that executed it.

A checklist row is a control from the published library (gold_dim_control)
joined to its results in the latest run_controls run (meta_control_results).
Nothing here decides pass or fail: the status is the ledger's result (FAIL if any
entity failed), STALE when the latest execution is older than the control's
frequency allows. Sign-offs are bound to the run they attest; a newer run
supersedes them.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import review
from ..auth import CallerIdentity, caller_identity
from ..db import fetch_all, fetch_many
from ..sqlutil import fq, links, period_or_active, safe_code

router = APIRouter(prefix="/checklist", tags=["checklist"])
SNAPSHOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "repo_snapshot")
SLA_HOURS = {"continuous": 30, "daily": 30, "monthly": 24 * 35, "quarterly": 24 * 100}
RANK = {"FAIL": 0, "STALE": 1, "RESOLVED": 2, "PASS": 3, "INFO": 4, "NO_POPULATION": 5}


def _rollup(results: list[str]) -> str:
    if not results:
        return "NOT_RUN"
    for r in ("FAIL", "RESOLVED", "PASS", "INFO"):
        if r in results:
            return r
    return "NO_POPULATION"


@router.get("")
async def checklist(period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    r = fetch_many(caller, {
        "controls": f"SELECT * FROM {fq('gold_dim_control')} ORDER BY module, control_id",
        # The run whose results the checklist shows: the latest run that recorded results
        # (job run ids are not time-ordered, so "latest" is by execution time).
        "run": f"""SELECT * FROM {fq('meta_control_runs')}
                   WHERE job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {fq('meta_control_results')})""",
        "res": (f"""SELECT control_id, collect_set(result) AS results, sum(population_count) AS population,
                           sum(exceptions) AS exceptions, sum(exception_amount_usd) AS amount, sum(open_exceptions) AS open_exceptions,
                           count(*) AS instances, sum(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END) AS failed_instances,
                           max(executed_at) AS executed_at, max(job_run_id) AS job_run_id, max(task_run_id) AS task_run_id,
                           max(test_update_id) AS test_update_id, max(job_id) AS job_id, max(control_version) AS control_version
                    FROM {fq('meta_control_results')}
                    WHERE job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {fq('meta_control_results')}) AND period = ?
                    GROUP BY control_id""", [p]),
        "spark": (f"""SELECT control_id, job_run_id, max(executed_at) AS at, min(CASE result WHEN 'FAIL' THEN 0 WHEN 'RESOLVED' THEN 1 WHEN 'PASS' THEN 2
                                                   WHEN 'INFO' THEN 3 ELSE 4 END) AS r, sum(exceptions) AS exceptions
                      FROM {fq('meta_control_results')} WHERE period = ?
                        AND job_run_id IN (SELECT job_run_id FROM {fq('meta_control_results')} GROUP BY job_run_id
                                           ORDER BY max(executed_at) DESC LIMIT 30)
                      GROUP BY control_id, job_run_id""", [p]),
        "exc": (f"""SELECT control_id, MEASURE(exceptions) AS exceptions, MEASURE(ai_triage_coverage_pct) AS triage_pct,
                           MEASURE(evidence_attached_pct) AS evidence_pct, MEASURE(dispositioned_pct) AS dispositioned_pct,
                           MEASURE(ai_high_risk_exceptions) AS ai_high_risk
                    FROM {fq('gold_mv_exceptions')} WHERE period = ? GROUP BY control_id""", [p]),
        "exp": f"""SELECT e.name, e.passed, e.failed, m.dataset FROM {fq('meta_pipeline_update_metrics')} m
                   LATERAL VIEW explode(m.expectations) x AS e
                   WHERE m.update_id = (SELECT test_update_id FROM {fq('meta_control_runs')} WHERE test_update_id IS NOT NULL
                                        ORDER BY started_at DESC LIMIT 1)""",
        "signoffs": (f"""SELECT item_key, signed_off_by, signed_off_at FROM {fq('silver_review_status')}
                         WHERE item_type = 'control_signoff' AND period = ?""", [p]),
        "cal": f"SELECT task_code, name, controls FROM {fq('silver_close_calendar')}",
    })
    run = (r["run"] or [None])[0]
    res = {x["control_id"]: x for x in r["res"]}
    exc = {x["control_id"]: x for x in r["exc"]}
    exp = {x["name"]: x for x in r["exp"]}
    spark: dict[str, list] = {}
    for x in sorted(r["spark"], key=lambda x: str(x["at"])):
        spark.setdefault(x["control_id"], []).append({"run": x["job_run_id"], "r": x["r"], "exceptions": x["exceptions"]})
    tasks_by_ctl: dict[str, list] = {}
    for t in r["cal"]:
        for c in t["controls"] or []:
            tasks_by_ctl.setdefault(c, []).append({"task_code": t["task_code"], "name": t["name"]})
    uc_sign = {x["item_key"]: x for x in r["signoffs"]}
    live = await review.live_actions("control_signoff", period=p)
    live_sign: dict[str, dict] = {}
    for a in live:
        live_sign[a["item_key"]] = a
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for c in r["controls"]:
        cid = c["control_id"]
        x = res.get(cid) or {}
        status = _rollup(x.get("results") or [])
        executed = x.get("executed_at")
        if executed and status not in ("NOT_RUN",):
            age_h = (now - executed.replace(tzinfo=None)).total_seconds() / 3600 if hasattr(executed, "replace") else 0
            if age_h > SLA_HOURS.get(c["frequency"], 30) and c["frequency"] in ("continuous", "daily"):
                status = "STALE"
        key = f"{cid}|{p}"
        so = live_sign.get(key)
        signoff = None
        if so:
            signoff = {"by": so["actor_email"], "at": so["created_at"], "attested_job_run_id": so.get("attested_job_run_id"),
                       "pending_sync": True}
        elif key in uc_sign and uc_sign[key].get("signed_off_by"):
            signoff = {"by": uc_sign[key]["signed_off_by"], "at": uc_sign[key]["signed_off_at"], "attested_job_run_id": None,
                       "pending_sync": False}
        if signoff and run and signoff.get("attested_job_run_id") and int(signoff["attested_job_run_id"]) != int(run["job_run_id"]):
            signoff["superseded"] = True
        e = exc.get(cid) or {}
        ex = exp.get(c.get("executed_by_expectation") or "")
        rows.append({
            "control_id": cid, "version": c["version"], "title": c["title"], "objective": c["objective"], "module": c["module"],
            "module_name": c["module_name"], "lane": c["lane"], "key_control": c["key_control"], "assertions": c["assertions"],
            "nature_type": c["nature_type"], "automation": c["automation"], "line_of_defense": c["line_of_defense"],
            "frequency": c["frequency"], "owner_role": c["owner_role"], "risk_ids": c["risk_ids"], "policy_ref": c["policy_ref"],
            "executed_by_kind": c["executed_by_kind"], "executed_by_task": c["executed_by_task"],
            "executed_by_dataset": c["executed_by_dataset"], "executed_by_expectation": c["executed_by_expectation"],
            "is_info": c["is_info"], "traditional_sample_size": c["traditional_sample_size"],
            "status": status, "population": x.get("population"), "exceptions": x.get("exceptions"), "amount_usd": x.get("amount"),
            "open_exceptions": x.get("open_exceptions"), "instances": x.get("instances"), "failed_instances": x.get("failed_instances"),
            "executed_at": executed, "job_run_id": x.get("job_run_id"), "task_run_id": x.get("task_run_id"),
            "test_update_id": x.get("test_update_id"), "job_id": x.get("job_id"),
            "triage_pct": e.get("triage_pct"), "evidence_pct": e.get("evidence_pct"), "dispositioned_pct": e.get("dispositioned_pct"),
            "ai_high_risk": e.get("ai_high_risk"),
            "expectation": {"passed": ex["passed"], "failed": ex["failed"], "dataset": ex["dataset"]} if ex else None,
            "sparkline": spark.get(cid, []), "close_tasks": tasks_by_ctl.get(cid, []), "signoff": signoff,
        })
    rows.sort(key=lambda z: (z["lane"] != "management", RANK.get(z["status"], 9), z["module"], z["control_id"]))
    summary = {s: sum(1 for z in rows if z["status"] == s) for s in ("FAIL", "RESOLVED", "PASS", "INFO", "STALE", "NOT_RUN", "NO_POPULATION")}
    return {"period": p, "run": run, "controls": rows, "summary": summary, "links": links()}


def _snapshot(rel: str | None) -> str | None:
    if not rel:
        return None
    path = os.path.normpath(os.path.join(SNAPSHOT, rel))
    if not path.startswith(SNAPSHOT) or not os.path.exists(path):
        return None
    with open(path) as f:
        return f.read()


@router.get("/{control_id}")
def control_detail(control_id: str, period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    cid = safe_code(control_id, "control id")
    p = period_or_active(period)
    r = fetch_many(caller, {
        "c": (f"SELECT * FROM {fq('gold_dim_control')} WHERE control_id = ?", [cid]),
        "entities": (f"""SELECT entity_code, result, population_count, exceptions, exception_amount_usd, open_exceptions
                         FROM {fq('meta_control_results')}
                         WHERE job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {fq('meta_control_results')}) AND control_id = ? AND period = ?
                         ORDER BY entity_code""", [cid, p]),
        "history": (f"""SELECT r.job_run_id, r.started_at, r.test_update_id, r.job_id,
                               min(CASE res.result WHEN 'FAIL' THEN 'FAIL' END) AS any_fail, sum(res.exceptions) AS exceptions,
                               max(r.trigger_source) AS trigger_source, max(r.requested_by) AS requested_by
                        FROM {fq('meta_control_results')} res JOIN {fq('meta_control_runs')} r USING (job_run_id)
                        WHERE res.control_id = ? AND res.period = ?
                        GROUP BY r.job_run_id, r.started_at, r.test_update_id, r.job_id ORDER BY r.started_at DESC LIMIT 30""", [cid, p]),
        "periods": (f"""SELECT period, collect_set(result) AS results, sum(exceptions) AS exceptions
                        FROM {fq('meta_control_results')}
                        WHERE job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {fq('meta_control_results')}) AND control_id = ?
                        GROUP BY period ORDER BY period DESC LIMIT 12""", [cid]),
        "risks": (f"""SELECT risk_id, title, category FROM {fq('gold_dim_risk')} WHERE array_contains(control_ids, ?)""", [cid]),
        "policy": (f"""SELECT p.policy_ref, p.clause_text FROM {fq('silver_policy_section')} p
                       JOIN {fq('gold_dim_control')} c ON c.policy_ref = p.policy_ref WHERE c.control_id = ?""", [cid]),
    })
    if not r["c"]:
        raise HTTPException(404, f"Control {cid} is not in the published library.")
    c = r["c"][0]
    for h in r["periods"]:
        h["result"] = _rollup(h.pop("results") or [])
    return {"control": c, "period": p, "entities": r["entities"], "run_history": r["history"], "periods": r["periods"],
            "risks": r["risks"], "policy": (r["policy"] or [None])[0],
            "definition_yaml": _snapshot(c["source_file"]), "test_sql": _snapshot(c["test_sql_file"]),
            "test_sql_file": c["test_sql_file"], "links": links()}


class ControlSignoffIn(BaseModel):
    period: str
    comment: str = ""


@router.post("/{control_id}/signoff")
async def control_signoff(control_id: str, body: ControlSignoffIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    cid = safe_code(control_id, "control id")
    p = period_or_active(body.period)
    run = fetch_all(caller, f"SELECT max_by(job_run_id, executed_at) AS r FROM {fq('meta_control_results')}")
    rid = run[0]["r"] if run else None
    rec = await review.record("control_signoff", f"{cid}|{p}", p, "signoff", caller.email, "reviewer", comment=body.comment,
                              attested_job_run_id=rid, payload={"attested_job_run_id": rid})
    return {"status": "recorded", "attested_job_run_id": rid, "action_id": rec["action_id"],
            "note": f"Sign-off attests run {rid}. A newer run marks it superseded until re-attested."}
