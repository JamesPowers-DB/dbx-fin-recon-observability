"""Risk & Reporting: risk register with live KRIs, SOX status pack, AI-drafted summary.

KRI values are governed measures (the risk register names the metric view and
measure; this router only evaluates MEASURE() for the period). Residual status is
a display rule over two recorded facts: the latest results of the linked controls
and the KRI against its appetite threshold. The AI summary is drafted from the
same numbers, which are returned alongside it so a reviewer can check every one.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CallerIdentity, caller_identity
from ..config import get_settings
from ..db import fetch_all, fetch_many
from ..fmapi import call_model
from ..sqlutil import fq, period_or_active

router = APIRouter(prefix="/reporting", tags=["reporting"])
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
# Latest run by execution time (job run ids are not time-ordered).
LATEST = "job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {t})"


def _kri_sql(view: str, measure: str) -> str:
    if not (_IDENT.match(view) and _IDENT.match(measure) and view.startswith("gold_mv_")):
        raise HTTPException(500, f"Risk register KRI {view}.{measure} is not a metric-view measure")
    return f"SELECT MEASURE({measure}) AS v FROM {fq(view)} WHERE period = ?"


@router.get("/risks")
def risks(period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    reg = fetch_all(caller, f"SELECT * FROM {fq('gold_dim_risk')} ORDER BY risk_id")
    q = {f"kri_{r['risk_id']}": (_kri_sql(r["kri_metric_view"], r["kri_measure"]), [p]) for r in reg}
    q["ctl"] = (f"""SELECT control_id, collect_set(result) AS results, sum(open_exceptions) AS open_exceptions
                    FROM {fq('meta_control_results')} WHERE {LATEST.format(t=fq('meta_control_results'))} AND period = ?
                    GROUP BY control_id""", [p])
    r = fetch_many(caller, q)
    ctl = {c["control_id"]: c for c in r["ctl"]}
    out = []
    for x in reg:
        v = (r[f"kri_{x['risk_id']}"] or [{}])[0].get("v")
        thr = x["kri_threshold"]
        breached = None if v is None else (v > thr if x["kri_direction"] == "above_is_bad" else v < thr)
        linked = [{"control_id": c, "result": ("FAIL" if "FAIL" in (ctl.get(c, {}).get("results") or [])
                                               else "PASS" if ctl.get(c) else "NOT_RUN"),
                   "open_exceptions": ctl.get(c, {}).get("open_exceptions")} for c in x["control_ids"]]
        failing = sum(1 for c in linked if c["result"] == "FAIL")
        residual = "Elevated" if breached and failing else "Monitor" if (breached or failing) else "Within appetite"
        out.append({**x, "kri_value": v, "kri_breached": breached, "linked_controls": linked,
                    "failing_controls": failing, "residual": residual})
    return {"period": p, "risks": out}


@router.get("/sox-pack")
def sox_pack(period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    t = fq("meta_control_results")
    r = fetch_many(caller, {
        "by_module": (f"""SELECT res.module, c.module_name, count(DISTINCT res.control_id) AS controls,
                                 count(DISTINCT CASE WHEN res.result = 'FAIL' THEN res.control_id END) AS failed,
                                 count(DISTINCT CASE WHEN res.result = 'FAIL' AND res.key_control THEN res.control_id END) AS key_failed,
                                 sum(res.population_count) AS population, sum(res.exceptions) AS exceptions
                          FROM {t} res JOIN {fq('gold_dim_control')} c USING (control_id)
                          WHERE res.{LATEST.format(t=t)} AND res.period = ? AND NOT c.is_info GROUP BY res.module, c.module_name
                          ORDER BY res.module""", [p]),
        "by_assertion": (f"""SELECT a AS assertion, count(DISTINCT res.control_id) AS controls,
                                    count(DISTINCT CASE WHEN res.result = 'FAIL' THEN res.control_id END) AS failed
                             FROM {t} res JOIN {fq('gold_dim_control')} c USING (control_id) LATERAL VIEW explode(c.assertions) x AS a
                             WHERE res.{LATEST.format(t=t)} AND res.period = ? AND NOT c.is_info GROUP BY a ORDER BY a""", [p]),
        "by_lane": (f"""SELECT res.lane, count(DISTINCT res.control_id) AS controls,
                               count(DISTINCT CASE WHEN res.result = 'FAIL' THEN res.control_id END) AS failed
                        FROM {t} res WHERE res.{LATEST.format(t=t)} AND res.period = ? GROUP BY res.lane""", [p]),
        "deficiencies": (f"""SELECT x.exception_id, x.control_id, x.control_title, x.key_control, x.entity_code, x.amount_usd,
                                    x.detected_value, x.disposition, x.disposition_status, x.approved_by, x.review_comment
                             FROM {fq('gold_control_exceptions')} x
                             WHERE x.period = ? AND (x.disposition = 'deficiency' OR (x.key_control AND x.is_open AND NOT x.is_info))
                             ORDER BY x.key_control DESC, x.amount_usd DESC LIMIT 50""", [p]),
        "remediation": (f"""SELECT disposition, disposition_status, count(*) AS n, sum(amount_usd) AS amount_usd
                            FROM {fq('gold_control_exceptions')} WHERE period = ? GROUP BY disposition, disposition_status""", [p]),
        "health": (f"""SELECT MEASURE(control_pass_rate) AS pass_rate, MEASURE(controls_executed) AS executed,
                              MEASURE(controls_failed) AS failed, MEASURE(key_controls_failed) AS key_failed,
                              MEASURE(records_tested) AS records_tested, MEASURE(traditional_sample) AS traditional_sample
                       FROM {fq('gold_mv_control_health')} WHERE is_latest_run = true AND period = ?""", [p]),
        "run": f"SELECT * FROM {fq('meta_control_runs')} ORDER BY started_at DESC LIMIT 1",
    })
    return {"period": p, **{k: v for k, v in r.items() if k not in ("health", "run")},
            "health": (r["health"] or [{}])[0], "run": (r["run"] or [None])[0]}


def _numbers(caller: CallerIdentity, p: str) -> dict:
    r = fetch_many(caller, {
        "close": (f"""SELECT MEASURE(projected_days_to_close) AS projected_days_to_close, MEASURE(tasks_complete) AS tasks_complete,
                             MEASURE(tasks_total) AS tasks_total, MEASURE(pre_close_completion_pct) AS pre_close_completion_pct
                      FROM {fq('gold_mv_close')} WHERE period = ?""", [p]),
        "health": (f"""SELECT MEASURE(control_pass_rate) AS control_pass_rate, MEASURE(controls_failed) AS controls_failed,
                              MEASURE(key_controls_failed) AS key_controls_failed, MEASURE(records_tested) AS records_tested
                       FROM {fq('gold_mv_control_health')} WHERE is_latest_run = true AND period = ?""", [p]),
        "exc": (f"""SELECT MEASURE(open_exceptions) AS open_exceptions, MEASURE(critical_open_exceptions) AS critical_open_exceptions,
                           MEASURE(exception_amount_usd) AS exception_amount_usd, MEASURE(ai_triage_coverage_pct) AS ai_triage_coverage_pct
                    FROM {fq('gold_mv_exceptions')} WHERE period = ?""", [p]),
        "recon": (f"SELECT MEASURE(unreconciled_amount_usd) AS unreconciled_amount_usd FROM {fq('gold_mv_reconciliations')} WHERE period = ?", [p]),
        "fin": (f"""SELECT MEASURE(unexplained_material_variances) AS unexplained_material_variances,
                           MEASURE(material_variances) AS material_variances
                    FROM {fq('gold_mv_financials')} WHERE period = ? AND statement = 'IS'""", [p]),
        "failed": (f"""SELECT DISTINCT control_id, control_title, key_control FROM {fq('meta_control_results')}
                       WHERE job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {fq('meta_control_results')}) AND period = ? AND result = 'FAIL'
                       ORDER BY key_control DESC, control_id""", [p]),
    })
    nums: dict = {}
    for k in ("close", "health", "exc", "recon", "fin"):
        nums.update((r[k] or [{}])[0])
    nums["failed_controls"] = r["failed"]
    return nums


@router.post("/summary")
def summary(period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    nums = _numbers(caller, p)
    prompt = (f"Draft a one-page close and SOX status summary in Markdown for the audit committee pack of Corvane Technologies, "
              f"period {p}. Use ONLY the numbers in this JSON; do not invent figures, names or dates. Sections: Headline, "
              f"Close progress, Control results, Exceptions and remediation, Items for attention. Format USD with thousands "
              f"separators; percentages from fractions.\n\n{nums}")
    md = call_model(caller, prompt, max_tokens=3000,
                    system="You write concise, factual internal audit reporting. No speculation, no adjectives about performance.")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    footer = (f"\n\n---\n_AI-generated draft ({get_settings().serving_endpoint_name}, {stamp}) from governed metric views. "
              f"Reviewed by: ________ . Numbers: see the source table in the app._")
    return {"period": p, "markdown": md + footer, "numbers": nums, "model": get_settings().serving_endpoint_name}
