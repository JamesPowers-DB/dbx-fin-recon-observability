"""Exceptions & Review: queue, drill-down to source records and evidence, four-eyes actions, working papers.

Exceptions, AI triage and evidence are read from Unity Catalog (OBO). Review
state is the UC snapshot (silver_review_status) merged with live Lakebase actions
taken since the last control run, so a reviewer sees their action immediately;
the next run applies it to the control results.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from .. import lakebase, review
from ..auth import CallerIdentity, caller_identity
from ..config import get_settings
from ..db import fetch_all, fetch_many, fetch_one
from ..sqlutil import fq, period_or_active, safe_code

log = logging.getLogger("audit-workbench.exceptions")
router = APIRouter(prefix="/exceptions", tags=["exceptions"])

LIST_COLS = """x.exception_id, x.module, x.control_id, x.control_title, x.key_control, x.lane, x.entity_code, x.region, x.period,
  x.record_key, x.record_type, x.amount_usd, x.detected_value, x.item_date, x.age_bd, x.is_info, x.rule_severity,
  x.disposition_status, x.disposition, x.proposed_by, x.approved_by, x.approved_at, x.review_comment, x.policy_ref,
  x.has_document_evidence, x.requires_evidence, x.lineage,
  t.severity AS ai_severity, t.root_cause_category AS ai_root_cause, t.confidence AS ai_confidence, t.needs_human,
  t.draft_finding AS ai_draft_finding, t.recommended_action AS ai_recommended_action, t.model AS ai_model"""


def _merge_live(rows: list[dict], live: list[dict], synced: set[str]) -> list[dict]:
    """Overlay review actions that are in Lakebase but not yet applied by a control run.

    The UC columns (disposition_status, proposed_by, ...) are what the last run
    applied. A live action is pending until snapshot_review_state has copied it
    (its action_id is in meta_review_actions); only then does UC reflect it.
    """
    by_key: dict[str, list[dict]] = {}
    for a in live:
        by_key.setdefault(a["item_key"], []).append(a)
    for r in rows:
        acts = by_key.get(r["exception_id"])
        if acts and any(a["action_id"] not in synced for a in acts):
            st = review.latest_state(acts)
            r["live_state"] = st
            r["disposition_status"] = st.get("disposition_status", r["disposition_status"])
            r["proposed_by"] = st.get("proposed_by") or r.get("proposed_by")
            r["disposition"] = st.get("disposition") or r.get("disposition")
            r["approved_by"] = st.get("approved_by") or (None if st.get("disposition_status") != "approved" else r.get("approved_by"))
            r["pending_sync"] = True
    return rows


@router.get("")
async def list_exceptions(period: str | None = None, module: str | None = None, control: str | None = None,
                          status: str | None = None, limit: int = 400,
                          caller: CallerIdentity = Depends(caller_identity)) -> dict:
    p = period_or_active(period)
    where, params = ["x.period = ?"], [p]
    if safe_code(module, "module"):
        where.append("x.module = ?")
        params.append(module)
    if safe_code(control, "control"):
        where.append("x.control_id = ?")
        params.append(control)
    rows = fetch_all(caller, f"""
        SELECT {LIST_COLS}
        FROM {fq('gold_control_exceptions')} x LEFT JOIN {fq('ml_exception_triage')} t ON t.exception_id = x.exception_id
        WHERE {' AND '.join(where)}
        ORDER BY x.is_info, CASE t.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, x.amount_usd DESC
        LIMIT {max(1, min(int(limit), 2000))}""", params)
    live = await review.live_actions("exception", [r["exception_id"] for r in rows])
    synced: set[str] = set()
    if live:
        synced = {x["action_id"] for x in fetch_all(caller, f"""SELECT action_id FROM {fq('meta_review_actions')}
                                                               WHERE item_type = 'exception' AND period = ?""", [p])}
    rows = _merge_live(rows, live, synced)
    if status:
        rows = [r for r in rows if (status == "open" and r["disposition_status"] != "approved") or r["disposition_status"] == status]
    return {"period": p, "rows": rows}


def _source_records(caller: CallerIdentity, x: dict) -> dict[str, Any]:
    """Follow the exception's lineage keys back to source rows (the audit trail)."""
    lin = x.get("lineage") or {}
    q: dict[str, tuple[str, list]] = {}
    if lin.get("je_header_id"):
        q["journal_lines"] = (f"""SELECT je_header_id, je_line_num, entity_code, account_code, account_name, je_source, je_category,
                                  journal_name, accounting_date, posted_at, created_by_user_name, approved_by_user_id, approved_at,
                                  entered_dr, entered_cr, accounted_dr, accounted_cr, reference_1, reference_2, line_description
                                  FROM {fq('gold_fact_gl_lines')} WHERE je_header_id = ? ORDER BY je_line_num""", [int(lin["je_header_id"])])
    if lin.get("bank_entry_ref"):
        q["bank_entry"] = (f"SELECT * FROM {fq('silver_bank_entry')} WHERE bank_entry_ref = ?", [lin["bank_entry_ref"]])
    if lin.get("invoice_id"):
        q["ap_invoice"] = (f"SELECT * FROM {fq('silver_ap_invoice')} WHERE invoice_id = ?", [int(lin["invoice_id"])])
    if lin.get("user_id"):
        q["user_access"] = (f"""SELECT user_id, user_name, legal_name, email, entity_code, job_profile, period, roles, sod_conflicts,
                                termination_date, access_end_date, removal_lag_bd, post_termination_journals
                                FROM {fq('gold_fact_user_access')} WHERE user_id = ? ORDER BY period DESC LIMIT 6""", [int(lin["user_id"])])
    if x["record_type"] == "subledger_tieout":
        q["tieout"] = (f"""SELECT * FROM {fq('gold_recon_summary')} WHERE entity_code = ? AND period = ? AND control_id = ?""",
                       [x["entity_code"], x["period"], x["control_id"]])
    if x["record_type"] == "bank_reconciliation":
        q["tieout"] = (f"SELECT * FROM {fq('gold_recon_summary')} WHERE recon_object = ? AND period = ?",
                       [lin.get("bank_account"), x["period"]])
    if x["record_type"] == "variance_line":
        q["variance"] = (f"""SELECT * FROM {fq('gold_fact_variance_lines')} WHERE variance_key = ?""", [x["record_key"]])
    if x["record_type"] in ("trial_balance", "balance_sheet", "cash_flow", "equity_rollforward"):
        q["integrity"] = (f"SELECT * FROM {fq('gold_m5_integrity')} WHERE entity_code = ? AND period = ?", [x["entity_code"], x["period"]])
    return fetch_many(caller, q) if q else {}


@router.get("/{exception_id}")
async def detail(exception_id: str, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    safe_code(exception_id, "exception id")
    r = fetch_many(caller, {
        "x": (f"""SELECT {LIST_COLS}, t.rationale AS ai_rationale, t.triaged_at AS ai_triaged_at, t.prompt_version AS ai_prompt_version
                  FROM {fq('gold_control_exceptions')} x LEFT JOIN {fq('ml_exception_triage')} t ON t.exception_id = x.exception_id
                  WHERE x.exception_id = ?""", [exception_id]),
        "evidence": (f"SELECT * FROM {fq('gold_exception_evidence')} WHERE exception_id = ?", [exception_id]),
        "history": (f"""SELECT action_id, action, disposition, comment, actor_email, actor_role, acted_at, source
                        FROM {fq('silver_review_actions')} WHERE item_type = 'exception' AND item_key = ? ORDER BY acted_at""", [exception_id]),
        "control": (f"""SELECT c.*, p.clause_text FROM {fq('gold_dim_control')} c
                        LEFT JOIN {fq('silver_policy_section')} p ON p.policy_ref = c.policy_ref
                        WHERE c.control_id = (SELECT control_id FROM {fq('gold_control_exceptions')} WHERE exception_id = ?)""", [exception_id]),
        "log": (f"""SELECT job_run_id, change, logged_at FROM {fq('meta_control_exception_log')}
                    WHERE exception_id = ? ORDER BY logged_at""", [exception_id]),
    })
    if not r["x"]:
        raise HTTPException(404, "Exception not found in the latest pipeline update.")
    x = r["x"][0]
    live = await review.live_actions("exception", [exception_id])
    synced_ids = {h.get("action_id") for h in r["history"]}
    timeline = [{**h, "pending_sync": False} for h in r["history"]] + [
        {"action": a["action"], "disposition": a.get("disposition"), "comment": a.get("comment"), "actor_email": a["actor_email"],
         "actor_role": a["actor_role"], "acted_at": a["created_at"], "source": "audit_workbench", "pending_sync": True}
        for a in live if a["action_id"] not in synced_ids]
    seen, merged = set(), []
    for t in sorted(timeline, key=lambda t: str(t["acted_at"])):
        k = (t["action"], t["actor_email"], str(t["acted_at"])[:19])
        if k not in seen:
            seen.add(k)
            merged.append(t)
    wp = None
    if lakebase.is_configured():
        try:
            rows = await review._fetch(f"SELECT * FROM {review.S}.working_papers WHERE exception_id = %s", (exception_id,))
            wp = rows[0] if rows else None
        except Exception as e:  # noqa: BLE001
            log.warning("working paper unavailable: %s", e)
    state = review.latest_state([{**t, "created_at": t["acted_at"]} for t in merged])
    return {"exception": x, "control": (r["control"] or [None])[0], "evidence": r["evidence"],
            "source_records": _source_records(caller, x), "timeline": merged, "state": state,
            "run_log": r["log"], "working_paper": wp}


class ActionIn(BaseModel):
    action: str                     # propose | approve | reject | reopen
    disposition: str | None = None  # explained | adjusted | remediated | false_positive | deficiency
    comment: str = ""
    role: str = "reviewer"


@router.post("/{exception_id}/actions")
async def act(exception_id: str, body: ActionIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    if body.action not in ("propose", "approve", "reject", "reopen"):
        raise HTTPException(400, "Unknown action")
    if body.action == "propose" and body.disposition not in ("explained", "adjusted", "remediated", "false_positive", "deficiency"):
        raise HTTPException(400, "A proposal needs a disposition")
    x = fetch_one(caller, f"SELECT period FROM {fq('gold_control_exceptions')} WHERE exception_id = ?", [exception_id])
    if not x:
        raise HTTPException(404, "Exception not found")
    hist = fetch_all(caller, f"""SELECT action, disposition, comment, actor_email, actor_role, acted_at AS created_at
                                 FROM {fq('silver_review_actions')} WHERE item_type = 'exception' AND item_key = ?""", [exception_id])
    run = fetch_one(caller, f"SELECT max_by(job_run_id, started_at) AS r FROM {fq('meta_control_runs')}") or {}
    rec = await review.record("exception", exception_id, x["period"], body.action, caller.email, body.role,
                              body.disposition, body.comment, attested_job_run_id=run.get("r"), history=hist)
    return {"status": "recorded", "action": rec, "note": "Applied to control results on the next control run."}


class WorkingPaperIn(BaseModel):
    title: str = ""
    body_md: str
    ai_draft_md: str | None = None
    agent_session_id: str | None = None


@router.put("/{exception_id}/working-paper")
async def save_working_paper(exception_id: str, body: WorkingPaperIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    if not lakebase.is_configured():
        raise HTTPException(503, "Review store (Lakebase) is not configured for this app.")
    async with lakebase.db_conn() as conn:
        await conn.execute(
            f"""INSERT INTO {review.S}.working_papers (exception_id, title, body_md, ai_draft_md, author_email, agent_session_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (exception_id) DO UPDATE SET title = EXCLUDED.title, body_md = EXCLUDED.body_md,
                  ai_draft_md = COALESCE(EXCLUDED.ai_draft_md, {review.S}.working_papers.ai_draft_md),
                  author_email = EXCLUDED.author_email, agent_session_id = EXCLUDED.agent_session_id, updated_at = now()""",
            (exception_id, body.title[:300], body.body_md[:20000], body.ai_draft_md, caller.email, body.agent_session_id))
        await conn.commit()
    return {"status": "saved", "exception_id": exception_id}


@router.get("/evidence/document")
def document(path: str, caller: CallerIdentity = Depends(caller_identity)) -> Response:
    """Stream an evidence PDF from the UC volume as the caller (OBO files scope)."""
    s = get_settings()
    prefix = f"/Volumes/{s.catalog}/{s.schema}/{s.raw_volume}/docs/"
    clean = path.replace("dbfs:", "")
    if not clean.startswith(prefix) or ".." in clean:
        raise HTTPException(400, "Only evidence documents in the demo volume can be opened.")
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.config import Config
    w = WorkspaceClient(config=Config(host=s.workspace_url, token=caller.access_token, auth_type="pat"))
    data = w.files.download(clean).contents.read()
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={clean.rsplit('/', 1)[-1]}"})
