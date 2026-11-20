"""Financial Statements (the final artifact) and the variance review (FP&A management review control).

Statement amounts come from gold_mv_financials (the same governed definitions the
dashboard and Genie use). FINAL/DRAFT follows the close: FINAL once CLS-12
(controller GO) is complete for the period. Variance explanations and
acknowledgements are review actions (Lakebase, four-eyes), applied on the next
control run.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import review
from ..auth import CallerIdentity, caller_identity
from ..config import get_settings
from ..db import fetch_all, fetch_many, fetch_one
from ..fmapi import call_model
from ..sqlutil import fq, period_or_active, safe_code

log = logging.getLogger("audit-workbench.statements")
router = APIRouter(prefix="/statements", tags=["statements"])


@router.get("")
def statement(statement: str = "IS", entity: str = "ALL", period: str | None = None,
              caller: CallerIdentity = Depends(caller_identity)) -> dict:
    if statement not in ("IS", "BS", "CF"):
        raise HTTPException(400, "statement must be IS, BS or CF")
    p = period_or_active(period)
    ent = safe_code(entity, "entity") or "ALL"
    where, params = ["statement = ?", "period = ?"], [statement, p]
    if ent != "ALL":
        where.append("entity_code = ?")
        params.append(ent)
    r = fetch_many(caller, {
        "lines": (f"""SELECT line_code, line_name, line_order, line_type, MEASURE(amount_usd) AS actual, MEASURE(prior_period_usd) AS prior_period,
                             MEASURE(prior_year_usd) AS prior_year, MEASURE(budget_usd) AS budget, MEASURE(budget_mtd_usd) AS budget_mtd,
                             MEASURE(forecast_usd) AS forecast, MEASURE(material_variances) AS material_variances,
                             MEASURE(unexplained_material_variances) AS unexplained
                      FROM {fq('gold_mv_financials')} WHERE {' AND '.join(where)}
                      GROUP BY line_code, line_name, line_order, line_type ORDER BY line_order""", params),
        "close": (f"""SELECT status, completed_close_day, projected_close_day, period_status FROM {fq('meta_close_task_status')}
                      WHERE period = ? AND task_code = 'CLS-12'""", [p]),
        "entities": f"SELECT entity_code, entity_name, currency_code, region FROM {fq('gold_dim_entity')} ORDER BY entity_code",
        "data": (f"SELECT DISTINCT data_status FROM {fq('gold_fact_statement_lines')} WHERE period = ?", [p]),
    })
    if statement == "IS":
        _roll_up_is(r["lines"])
    c = (r["close"] or [{}])[0]
    final = c.get("status") == "COMPLETE"
    return {"statement": statement, "entity": ent, "period": p, "lines": r["lines"], "entities": r["entities"],
            "badge": "FINAL" if final else "DRAFT",
            "close_day": c.get("completed_close_day") if final else c.get("projected_close_day"),
            "data_status": (r["data"] or [{}])[0].get("data_status"),
            "basis_note": "Month to date against the phased MTD budget (continuous flux)" if (r["data"] or [{}])[0].get("data_status") == "MONTH_TO_DATE"
            else "Full month"}


# Income statement subtotals carry actuals only (gold_fact_statement_lines); plan
# figures for them follow the same arithmetic as the pipeline's subtotal lines.
_IS_SUBTOTALS = {
    "IS-T10": [("IS-100", 1), ("IS-110", 1), ("IS-120", 1)],
    "IS-T20": [("IS-T10", 1), ("IS-200", -1)],
    "IS-T30": [("IS-300", 1), ("IS-310", 1), ("IS-320", 1), ("IS-330", 1)],
    "IS-T40": [("IS-T20", 1), ("IS-T30", -1)],
    "IS-T50": [("IS-T40", 1), ("IS-400", -1)],
    "IS-T60": [("IS-T50", 1), ("IS-500", -1)],
}


def _roll_up_is(lines: list[dict]) -> None:
    by = {x["line_code"]: x for x in lines}
    for code, parts in _IS_SUBTOTALS.items():   # dict order = dependency order
        tgt = by.get(code)
        if not tgt:
            continue
        for col in ("budget", "budget_mtd", "forecast"):
            if tgt.get(col) is not None:
                continue
            vals = [(by.get(c) or {}).get(col) for c, _ in parts]
            if all(v is None for v in vals):
                continue
            tgt[col] = sum((v or 0) * sign for v, (_, sign) in zip(vals, parts))


@router.get("/integrity")
def integrity(period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    r = fetch_many(caller, {
        "checks": (f"""SELECT res.control_id, c.title, c.objective, res.entity_code, res.result, res.exceptions, res.job_run_id, res.executed_at
                       FROM {fq('meta_control_results')} res JOIN {fq('gold_dim_control')} c USING (control_id)
                       WHERE res.job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {fq('meta_control_results')})
                         AND res.period = ? AND res.control_id LIKE 'FSC-%' ORDER BY res.control_id, res.entity_code""", [p]),
        "diffs": (f"SELECT * FROM {fq('gold_m5_integrity')} WHERE period = ? ORDER BY entity_code", [p]),
    })
    return {"period": p, "checks": r["checks"], "differences": r["diffs"]}


@router.get("/variances")
async def variances(period: str | None = None, entity: str | None = None, material_only: bool = True,
                    caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    where, params = ["period = ?"], [p]
    if safe_code(entity, "entity") and entity != "ALL":
        where.append("entity_code = ?")
        params.append(entity)
    if material_only:
        where.append("is_material")
    rows = fetch_all(caller, f"""SELECT * FROM {fq('gold_fact_variance_lines')} WHERE {' AND '.join(where)}
                                 ORDER BY abs(variance_usd) DESC LIMIT 200""", params)
    live = await review.live_actions("variance", [r["variance_key"] for r in rows])
    by: dict[str, list] = {}
    for a in live:
        by.setdefault(a["item_key"], []).append(a)
    for r in rows:
        if r["variance_key"] in by:
            st = review.latest_state(by[r["variance_key"]])
            r["live_state"] = st
            r["explained_by"] = st.get("explained_by") or r.get("explained_by")
            r["explanation"] = st.get("explanation") or r.get("explanation")
            r["acknowledged_by"] = st.get("acknowledged_by") or r.get("acknowledged_by")
            r["pending_sync"] = True
    return {"period": p, "rows": rows}


class ExplainIn(BaseModel):
    variance_key: str
    explanation: str
    ai_draft: str | None = None


class AckIn(BaseModel):
    variance_key: str
    comment: str = ""


def _history(caller: CallerIdentity, key: str) -> list[dict]:
    return fetch_all(caller, f"""SELECT action, comment, actor_email, actor_role, acted_at AS created_at
                                 FROM {fq('silver_review_actions')} WHERE item_type = 'variance' AND item_key = ?""", [key])


@router.post("/variances/explain")
async def explain(body: ExplainIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    key = safe_code(body.variance_key, "variance key")
    if not body.explanation.strip():
        raise HTTPException(400, "An explanation is required")
    rec = await review.record("variance", key, key.split("|")[0], "explain", caller.email, "controller", comment=body.explanation,
                              payload={"ai_draft": body.ai_draft, "edited": bool(body.ai_draft) and body.ai_draft.strip() != body.explanation.strip()},
                              history=_history(caller, key))
    return {"status": "recorded", "action_id": rec["action_id"]}


@router.post("/variances/acknowledge")
async def acknowledge(body: AckIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    key = safe_code(body.variance_key, "variance key")
    rec = await review.record("variance", key, key.split("|")[0], "acknowledge", caller.email, "reviewer", comment=body.comment,
                              history=_history(caller, key))
    return {"status": "recorded", "action_id": rec["action_id"]}


@router.post("/variances/ai-draft")
def ai_draft(body: AckIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    """Draft a variance explanation with the FMAPI model from the actual drivers (top journals). AI-generated; the controller edits and owns it."""
    key = safe_code(body.variance_key, "variance key")
    period, ent, fsli = key.split("|")
    v = fetch_one(caller, f"SELECT * FROM {fq('gold_fact_variance_lines')} WHERE variance_key = ?", [key])
    if not v:
        raise HTTPException(404, "Variance line not found")
    drivers = fetch_all(caller, f"""SELECT je_source, je_category, journal_name, line_description, account_name,
                                           round(sum(accounted_net_usd), 0) AS amount_usd
                                    FROM {fq('gold_fact_gl_lines')} WHERE period = ? AND entity_code = ? AND fsli_code = ?
                                    GROUP BY ALL ORDER BY abs(amount_usd) DESC LIMIT 8""", [period, ent, fsli])
    prompt = (f"You are the controller of {ent} at Corvane Technologies. Write a 2-3 sentence explanation of this budget variance for the "
              f"management review. Cite the drivers below; do not invent facts.\n\nLine: {v['line_name']}  Period: {period}\n"
              f"Actual USD {v['actual_usd']:,.0f} vs {'budget' if v['period_status'] == 'CLOSED' else 'MTD-phased budget'} "
              f"USD {v['budget_compare_usd']:,.0f} (variance {v['variance_usd']:,.0f}, {100 * (v['variance_pct'] or 0):.1f}%).\n"
              f"Largest postings: {json.dumps(drivers, default=str)}")
    text = call_model(caller, prompt, max_tokens=1500)
    return {"variance_key": key, "draft": text, "drivers": drivers, "model": get_settings().serving_endpoint_name,
            "label": "AI-generated draft. The controller reviews, edits and owns the explanation."}


@router.get("/drill")
def drill(line: str, entity: str = "ALL", period: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    code = safe_code(line, "line")
    p = period_or_active(period)
    ent = safe_code(entity, "entity") or "ALL"
    where, params = ["period = ?", "fsli_code = ?"], [p, code]
    if ent != "ALL":
        where.append("entity_code = ?")
        params.append(ent)
    r = fetch_many(caller, {
        "accounts": (f"""SELECT account_code, account_name, round(sum(accounted_net_usd), 2) AS net_usd, count(DISTINCT je_header_id) AS journals
                         FROM {fq('gold_fact_gl_lines')} WHERE {' AND '.join(where)} GROUP BY account_code, account_name ORDER BY abs(net_usd) DESC""", params),
        "journals": (f"""SELECT je_header_id, entity_code, je_source, je_category, journal_name, accounting_date,
                                round(sum(accounted_net_usd), 2) AS net_usd, max(created_by_user_name) AS created_by
                         FROM {fq('gold_fact_gl_lines')} WHERE {' AND '.join(where)}
                         GROUP BY je_header_id, entity_code, je_source, je_category, journal_name, accounting_date
                         ORDER BY abs(net_usd) DESC LIMIT 25""", params),
    })
    return {"line": code, "entity": ent, "period": p, **r}
