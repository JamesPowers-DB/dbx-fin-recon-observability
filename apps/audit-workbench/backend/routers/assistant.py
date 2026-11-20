"""Audit Assistant: an investigator agent (FMAPI tool calling) over the same governed data.

Every tool is a parameterized read of the gold tables / metric views the pages
use (and returns the SQL it ran, so the UI shows it), plus two actions:
save_working_paper (Lakebase, attributed to the caller) and escalate_to_owner
(simulated; requires the user's explicit confirmation). The agent never
dispositions exceptions: approvals are human, four-eyes, on the review page.
Sessions and messages persist in Lakebase best-effort; an outage never breaks chat.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import genie, lakebase
from ..auth import CallerIdentity, caller_identity
from ..config import get_settings
from ..db import fetch_all, fetch_many
from ..fmapi import chat
from ..sqlutil import active_period, fq, safe_code
from . import modules as modules_router
from .exceptions import _source_records

log = logging.getLogger("audit-workbench.assistant")
router = APIRouter(prefix="/assistant", tags=["assistant"])
S = lakebase.SCHEMA
MAX_STEPS = 8

SYSTEM = """You are the Audit Investigator for Corvane Technologies (fictional), working inside the Audit Workbench on Databricks.
Users are SOX testers, internal audit managers and controllers working the continuous close for the active period ({period}).

How to work:
- Answer from tools only. Every number you state must come from a tool result in this conversation. Cite the control id,
  exception id (first 10 characters) and the run (job_run_id) where relevant.
- Prefer the dedicated tools. Use ask_genie only for open-ended analytics they do not cover (trends, rankings, breakdowns).
- To investigate an exception: get_exception, then get_source_records and get_evidence, then state the likely root cause,
  what evidence supports or contradicts it, and what a reviewer should request.
- You never approve, reject or disposition anything. Dispositions are human decisions with four-eyes review on the
  Exceptions & Review page. Say so if asked to approve.
- save_working_paper only when the user asks you to save or draft a working paper. Mark it as an AI draft.
- request_control_run starts the run_controls job (real). Use it only when the user explicitly asks to re-run the
  controls in their latest message, and say that results update when the run finishes (several minutes).
- escalate_to_owner is a simulated action. Call it only after the user explicitly confirms the recipient and message
  in their latest message. Otherwise propose the escalation text and ask for confirmation.
- Be concise: short paragraphs or bullets, amounts in USD with thousands separators. Your output is AI-generated and
  labelled as such in the UI."""


def _tool(name: str, desc: str, props: dict | None = None, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props or {}, "required": required or []}}}


TOOLS = [
    _tool("close_status", "Days to close (last close and active projection), close tasks complete/blocked/overdue, control "
          "pass rate, open exceptions and unreconciled amount for the active period. Use for 'where are we in the close'."),
    _tool("checklist_status", "Latest control results per control (status, exceptions, amount) from the latest run_controls run. "
          "Optional filters: module (M1..M5, DQ, PLT) and status (FAIL, PASS, RESOLVED, INFO).",
          {"module": {"type": "string"}, "status": {"type": "string"}}),
    _tool("list_exceptions", "Exceptions for the active period with AI triage severity, largest first. Filters: control_id, "
          "module, open_only (default true). Returns exception ids to investigate.",
          {"control_id": {"type": "string"}, "module": {"type": "string"}, "open_only": {"type": "boolean"},
           "limit": {"type": "integer"}}),
    _tool("get_exception", "One exception with its control definition, policy clause, AI triage and review history.",
          {"exception_id": {"type": "string"}}, ["exception_id"]),
    _tool("get_source_records", "Follow an exception's lineage keys back to source rows (GL journal lines, bank entries, "
          "AP invoices, user access, tie-outs).", {"exception_id": {"type": "string"}}, ["exception_id"]),
    _tool("get_evidence", "Evidence documents linked to an exception (parsed PDF fields from ai_parse_document) and the "
          "policy excerpt for its control.", {"exception_id": {"type": "string"}}, ["exception_id"]),
    _tool("module_summary", "KPIs for one module tab: cash, subledger, journals or access.",
          {"module": {"type": "string", "enum": ["cash", "subledger", "journals", "access"]}}, ["module"]),
    _tool("save_working_paper", "Save a working paper (Markdown) on an exception as an AI draft attributed to the user.",
          {"exception_id": {"type": "string"}, "title": {"type": "string"}, "body_md": {"type": "string"}},
          ["exception_id", "title", "body_md"]),
    _tool("request_control_run", "Start the run_controls job now (re-test every control, apply review actions, refresh the "
          "close status). Only when the user explicitly asks for a re-run.", {"reason": {"type": "string"}}),
    _tool("escalate_to_owner", "SIMULATED: send an escalation to the control owner. Only after explicit user confirmation.",
          {"exception_id": {"type": "string"}, "owner_role": {"type": "string"}, "message": {"type": "string"}},
          ["exception_id", "owner_role", "message"]),
    _tool("ask_genie", "Open-ended analytics question over the governed metric views (Genie space). Returns the SQL Genie "
          "generated and the first rows.", {"question": {"type": "string"}}, ["question"]),
]


# --------------------------------------------------------------------------- tools
def _close_status(caller: CallerIdentity, _: dict) -> dict:
    from .close import summary
    s = summary(caller)
    keep = ("active_period", "today_close_day", "days_to_close_last", "days_to_close_traditional", "projected_days_to_close",
            "target_days_to_close", "pre_close_completion_pct", "tasks_complete", "tasks_total", "tasks_overdue",
            "tasks_blocked", "control_pass_rate", "controls_failed", "key_controls_failed", "open_exceptions",
            "critical_open_exceptions", "unreconciled_amount_usd")
    return {**{k: s.get(k) for k in keep}, "latest_run": {k: (s.get("latest_run") or {}).get(k) for k in
                                                          ("job_run_id", "started_at", "status", "gate_result")},
            "sql": ["SELECT MEASURE(projected_days_to_close) ... FROM gold_mv_close WHERE period = :active",
                    "SELECT MEASURE(control_pass_rate) ... FROM gold_mv_control_health WHERE is_latest_run"]}


def _checklist(caller: CallerIdentity, a: dict) -> dict:
    p = active_period()
    where, params = ["period = ?", f"job_run_id = (SELECT max_by(job_run_id, executed_at) FROM {fq('meta_control_results')})"], [p]
    if a.get("module"):
        where.append("module = ?")
        params.append(safe_code(a["module"], "module"))
    sql = f"""SELECT control_id, control_title, module, key_control, lane,
                     CASE WHEN array_contains(collect_set(result), 'FAIL') THEN 'FAIL'
                          WHEN array_contains(collect_set(result), 'RESOLVED') THEN 'RESOLVED'
                          WHEN array_contains(collect_set(result), 'PASS') THEN 'PASS'
                          WHEN array_contains(collect_set(result), 'INFO') THEN 'INFO' ELSE 'NO_POPULATION' END AS status,
                     sum(population_count) AS population, sum(exceptions) AS exceptions,
                     round(sum(exception_amount_usd), 0) AS exception_amount_usd, max(job_run_id) AS job_run_id
              FROM {fq('meta_control_results')} WHERE {' AND '.join(where)}
              GROUP BY control_id, control_title, module, key_control, lane ORDER BY control_id"""
    rows = fetch_all(caller, sql, params)
    if a.get("status"):
        rows = [r for r in rows if r["status"] == a["status"].upper()]
    return {"rows": rows, "sql": [sql.replace(fq(''), '')]}


def _list_exceptions(caller: CallerIdentity, a: dict) -> dict:
    where, params = ["x.period = ?"], [active_period()]
    if a.get("control_id"):
        where.append("x.control_id = ?")
        params.append(safe_code(a["control_id"], "control"))
    if a.get("module"):
        where.append("x.module = ?")
        params.append(safe_code(a["module"], "module"))
    if a.get("open_only", True):
        where.append("x.is_open")
    lim = max(1, min(int(a.get("limit") or 15), 50))
    sql = f"""SELECT x.exception_id, x.control_id, x.entity_code, x.record_key, round(x.amount_usd, 2) AS amount_usd, x.detected_value,
                     x.age_bd, x.disposition_status, t.severity AS ai_severity, t.root_cause_category AS ai_root_cause
              FROM {fq('gold_control_exceptions')} x LEFT JOIN {fq('ml_exception_triage')} t USING (exception_id)
              WHERE {' AND '.join(where)}
              ORDER BY CASE t.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, x.amount_usd DESC
              LIMIT {lim}"""
    return {"rows": fetch_all(caller, sql, params), "sql": [sql]}


def _exception_row(caller: CallerIdentity, eid: str) -> dict:
    rows = fetch_all(caller, f"""SELECT x.*, t.severity AS ai_severity, t.root_cause_category AS ai_root_cause, t.rationale AS ai_rationale,
                                        t.recommended_action AS ai_recommended_action, t.confidence AS ai_confidence
                                 FROM {fq('gold_control_exceptions')} x LEFT JOIN {fq('ml_exception_triage')} t USING (exception_id)
                                 WHERE x.exception_id = ? OR x.exception_id LIKE concat(?, '%') LIMIT 2""", [eid, eid])
    if not rows:
        raise ValueError(f"No exception {eid} in the latest pipeline update")
    if len(rows) > 1 and rows[0]["exception_id"] != eid:
        raise ValueError(f"Exception id prefix {eid} is ambiguous; use more characters")
    return rows[0]


def _get_exception(caller: CallerIdentity, a: dict) -> dict:
    x = _exception_row(caller, safe_code(a["exception_id"], "exception id"))
    r = fetch_many(caller, {
        "control": (f"""SELECT c.control_id, c.version, c.title, c.objective, c.parameters, c.max_exceptions, c.max_amount_usd,
                               c.owner_role, c.key_control, c.policy_ref, p.clause_text
                        FROM {fq('gold_dim_control')} c LEFT JOIN {fq('silver_policy_section')} p ON p.policy_ref = c.policy_ref
                        WHERE c.control_id = ?""", [x["control_id"]]),
        "history": (f"""SELECT action, disposition, comment, actor_email, acted_at FROM {fq('silver_review_actions')}
                        WHERE item_type = 'exception' AND item_key = ? ORDER BY acted_at""", [x["exception_id"]]),
        "log": (f"SELECT job_run_id, change FROM {fq('meta_control_exception_log')} WHERE exception_id = ? ORDER BY logged_at",
                [x["exception_id"]]),
    })
    x.pop("lineage", None)
    return {"exception": x, "control": (r["control"] or [None])[0], "review_history": r["history"], "run_log": r["log"],
            "sql": ["SELECT ... FROM gold_control_exceptions LEFT JOIN ml_exception_triage WHERE exception_id = :id"]}


def _get_source(caller: CallerIdentity, a: dict) -> dict:
    full = fetch_all(caller, f"SELECT * FROM {fq('gold_control_exceptions')} WHERE exception_id = ?",
                     [_exception_row(caller, safe_code(a["exception_id"], "exception id"))["exception_id"]])[0]
    recs = _source_records(caller, full)
    return {"lineage": full.get("lineage"), "records": {k: v[:15] for k, v in recs.items()},
            "sql": [f"lineage keys {list((full.get('lineage') or {}).keys())} -> source tables {list(recs.keys())}"]}


def _get_evidence(caller: CallerIdentity, a: dict) -> dict:
    x = _exception_row(caller, safe_code(a["exception_id"], "exception id"))
    sql = f"SELECT * FROM {fq('gold_exception_evidence')} WHERE exception_id = ?"
    ev = fetch_all(caller, sql, [x["exception_id"]])
    pol = fetch_all(caller, f"""SELECT p.policy_ref, p.clause_text FROM {fq('silver_policy_section')} p
                               JOIN {fq('gold_dim_control')} c ON c.policy_ref = p.policy_ref WHERE c.control_id = ?""", [x["control_id"]])
    return {"documents": ev, "policy": pol[:1], "requires_evidence": x.get("requires_evidence"),
            "has_document_evidence": x.get("has_document_evidence"), "sql": [sql]}


def _module_summary(caller: CallerIdentity, a: dict) -> dict:
    out = modules_router.module(a["module"], None, caller)
    vis = out.get("visual", {})
    small = {k: (v[:12] if isinstance(v, list) else v) for k, v in vis.items()}
    return {"module": out["module"], "period": out["period"], "kpis": out["kpis"], "visual": small,
            "sql": [f"SELECT MEASURE(...) FROM the {a['module']} metric view WHERE period = :active"]}


async def _save_wp(caller: CallerIdentity, a: dict, session_id: str) -> dict:
    if not lakebase.is_configured():
        return {"ok": False, "error": "Review store not configured"}
    x = await asyncio.to_thread(_exception_row, caller, safe_code(a["exception_id"], "exception id"))
    async with lakebase.db_conn() as conn:
        await conn.execute(
            f"""INSERT INTO {S}.working_papers (exception_id, title, body_md, ai_draft_md, author_email, agent_session_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (exception_id) DO UPDATE SET title = EXCLUDED.title, ai_draft_md = EXCLUDED.ai_draft_md,
                  body_md = CASE WHEN {S}.working_papers.body_md IS NULL OR {S}.working_papers.body_md = '' THEN EXCLUDED.body_md
                                 ELSE {S}.working_papers.body_md END,
                  agent_session_id = EXCLUDED.agent_session_id, updated_at = now()""",
            (x["exception_id"], a["title"][:300], a["body_md"][:20000], a["body_md"][:20000], caller.email, session_id))
        await conn.commit()
    return {"ok": True, "exception_id": x["exception_id"], "saved_as": "AI draft (editable on the Exceptions & Review page)"}


def _escalate(caller: CallerIdentity, a: dict) -> dict:
    x = _exception_row(caller, safe_code(a["exception_id"], "exception id"))
    routed_to = a["owner_role"]
    note = None
    if x.get("key_control") and (x.get("amount_usd") or 0) >= 1_000_000:
        routed_to = f"{a['owner_role']} + Internal Audit manager"
        note = "Key control exception of USD 1M or more: Internal Audit is copied by policy."
    ticket = "ESC-" + hashlib.sha1(f"{x['exception_id']}{a['message']}".encode()).hexdigest()[:8].upper()
    return {"ok": True, "simulated": True, "ticket": ticket, "routed_to": routed_to, "exception_id": x["exception_id"],
            "control_id": x["control_id"], "note": note,
            "message": "Simulated escalation recorded in this conversation only. In production this would call the ticketing or email system."}


def _request_run(caller: CallerIdentity, a: dict) -> dict:
    from ..models import RunTriggerRequest
    from .runs import trigger_run
    r = trigger_run(RunTriggerRequest(kind="run_controls", reason=(a.get("reason") or "Requested via the Audit Assistant")[:200]), caller)
    return {"ok": True, "job_id": r.job_id, "run_id": r.run_id, "run_page_url": r.run_page_url,
            "message": "run_controls started (or already running). The checklist and close status update when it finishes."}


def _ask_genie(caller: CallerIdentity, a: dict) -> dict:
    return genie.ask(caller, a["question"])


SYNC_TOOLS = {"close_status": _close_status, "checklist_status": _checklist, "list_exceptions": _list_exceptions,
              "get_exception": _get_exception, "get_source_records": _get_source, "get_evidence": _get_evidence,
              "module_summary": _module_summary, "escalate_to_owner": _escalate, "ask_genie": _ask_genie,
              "request_control_run": _request_run}


async def run_tool(caller: CallerIdentity, name: str, args: dict, session_id: str) -> dict:
    try:
        if name == "save_working_paper":
            return await _save_wp(caller, args, session_id)
        fn = SYNC_TOOLS.get(name)
        if not fn:
            return {"ok": False, "error": f"Unknown tool {name}"}
        return await asyncio.to_thread(fn, caller, args)
    except HTTPException as e:
        return {"ok": False, "error": str(e.detail)}
    except Exception as e:  # noqa: BLE001 - tool errors go back to the model
        log.warning("tool %s failed: %s", name, e)
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}


def _summarize(name: str, result: dict) -> str:
    if not result.get("ok", True) and result.get("error"):
        return f"error: {result['error'][:120]}"
    if "rows" in result:
        return f"{len(result['rows'])} rows"
    if name == "get_source_records":
        return ", ".join(f"{k}: {len(v)}" for k, v in (result.get("records") or {}).items()) or "no linked source rows"
    if name == "get_evidence":
        return f"{len(result.get('documents') or [])} documents"
    if name == "request_control_run":
        return f"run {result.get('run_id')} started"
    if name == "escalate_to_owner":
        return f"simulated {result.get('ticket')} to {result.get('routed_to')}"
    if name == "close_status":
        return f"projected T+{result.get('projected_days_to_close')}, {result.get('tasks_complete')}/{result.get('tasks_total')} tasks"
    return "ok"


# --------------------------------------------------------------------------- persistence (best effort)
async def _pg(sql: str, params: tuple = (), fetch: bool = False) -> list[dict]:
    if not lakebase.is_configured():
        return []
    try:
        async with lakebase.db_conn() as conn:
            cur = await conn.execute(sql, params)
            rows = []
            if fetch and cur.description:
                cols = [d.name for d in cur.description]
                rows = [dict(zip(cols, r)) for r in await cur.fetchall()]
            await conn.commit()
            return rows
    except Exception as e:  # noqa: BLE001
        log.warning("chat persistence unavailable: %s", e)
        return []


class SessionIn(BaseModel):
    title: str | None = None


@router.post("/sessions")
async def create_session(body: SessionIn, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    sid = uuid.uuid4().hex
    await _pg(f"INSERT INTO {S}.chatbot_sessions (session_id, user_email, title) VALUES (%s, %s, %s)",
              (sid, caller.email, (body.title or "New investigation")[:200]))
    return {"session_id": sid, "title": body.title or "New investigation"}


@router.get("/sessions")
async def list_sessions(caller: CallerIdentity = Depends(caller_identity)) -> list[dict]:
    return await _pg(f"""SELECT session_id, title, created_at, updated_at FROM {S}.chatbot_sessions
                         WHERE user_email = %s ORDER BY updated_at DESC LIMIT 30""", (caller.email,), fetch=True)


@router.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str, caller: CallerIdentity = Depends(caller_identity)) -> list[dict]:
    return await _pg(f"""SELECT m.message_id, m.role, m.content, m.tool_calls, m.created_at FROM {S}.chatbot_messages m
                         JOIN {S}.chatbot_sessions s USING (session_id)
                         WHERE m.session_id = %s AND s.user_email = %s ORDER BY m.created_at""",
                     (safe_code(session_id, "session"), caller.email), fetch=True)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    await _pg(f"DELETE FROM {S}.chatbot_sessions WHERE session_id = %s AND user_email = %s",
              (safe_code(session_id, "session"), caller.email))
    return {"deleted": session_id}


class MessageIn(BaseModel):
    content: str
    context: dict[str, Any] | None = None   # e.g. {"exception_id": "..."} from the Investigate handoff


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


@router.post("/sessions/{session_id}/messages")
async def send_message(session_id: str, body: MessageIn, caller: CallerIdentity = Depends(caller_identity)) -> StreamingResponse:
    sid = safe_code(session_id, "session")
    text = body.content.strip()
    if not text:
        raise HTTPException(400, "Empty message")
    if body.context and body.context.get("exception_id"):
        text = f"[Context: investigating exception {body.context['exception_id']}]\n{text}"

    async def stream() -> AsyncIterator[str]:
        try:
            history = await _pg(f"""SELECT role, content, tool_calls FROM {S}.chatbot_messages
                                    WHERE session_id = %s AND role IN ('user', 'assistant') ORDER BY created_at DESC LIMIT 20""",
                                (sid,), fetch=True)
            await _pg(f"""INSERT INTO {S}.chatbot_sessions (session_id, user_email, title) VALUES (%s, %s, %s)
                          ON CONFLICT (session_id) DO UPDATE SET updated_at = now()""", (sid, caller.email, text[:80]))
            await _pg(f"INSERT INTO {S}.chatbot_messages (message_id, session_id, role, content) VALUES (%s, %s, 'user', %s)",
                      (uuid.uuid4().hex, sid, text))
            msgs: list[dict] = [{"role": "system", "content": SYSTEM.format(period=active_period())}]
            turns: list[dict] = []
            for h in reversed(history):   # oldest first; alternate roles, start with the user
                if not h["content"] or h["content"] == "(no text)" or (not turns and h["role"] != "user"):
                    continue
                if turns and turns[-1]["role"] == h["role"]:
                    turns[-1]["content"] += "\n\n" + h["content"]
                else:
                    turns.append({"role": h["role"], "content": h["content"]})
            if turns and turns[-1]["role"] == "user":
                turns[-1]["content"] += "\n\n" + text
            else:
                turns.append({"role": "user", "content": text})
            msgs += turns
            log.info("assistant turn sig=%s", hashlib.sha1(text.encode()).hexdigest()[:10])
            tool_log: list[dict] = []
            final = ""
            for _ in range(MAX_STEPS):
                m = await asyncio.to_thread(chat, caller, msgs, TOOLS, 4000)
                content = m.get("content")
                if isinstance(content, list):
                    content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
                calls = m.get("tool_calls") or []
                if content:
                    final += content
                    yield _sse({"type": "content", "text": content})
                if not calls:
                    break
                # Omit empty content on tool-call turns (Claude rejects empty text blocks).
                msgs.append({"role": "assistant", "tool_calls": calls, **({"content": content} if content else {})})
                for c in calls:
                    name = c["function"]["name"]
                    try:
                        args = json.loads(c["function"].get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield _sse({"type": "tool_start", "id": c["id"], "name": name, "args": args})
                    result = await run_tool(caller, name, args, sid)
                    summary = _summarize(name, result)
                    tool_log.append({"name": name, "args": args, "summary": summary, "sql": result.get("sql"),
                                     "ok": result.get("ok", True)})
                    yield _sse({"type": "tool_result", "id": c["id"], "name": name, "summary": summary, "ok": result.get("ok", True),
                                "sql": result.get("sql"), "preview": (result.get("rows") or [])[:5],
                                "extra": {k: result.get(k) for k in ("ticket", "routed_to", "answer", "exception_id") if result.get(k)}})
                    msgs.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result, default=str)[:24000]})
            else:
                yield _sse({"type": "content", "text": "\n\n_Stopped after the maximum number of tool steps._"})
            await _pg(f"""INSERT INTO {S}.chatbot_messages (message_id, session_id, role, content, tool_calls)
                          VALUES (%s, %s, 'assistant', %s, %s::jsonb)""",
                      (uuid.uuid4().hex, sid, final or "(no text)", json.dumps(tool_log, default=str)))
            await _pg(f"UPDATE {S}.chatbot_sessions SET updated_at = now() WHERE session_id = %s", (sid,))
            yield _sse({"type": "done", "model": get_settings().serving_endpoint_name})
        except HTTPException as e:
            yield _sse({"type": "error", "message": str(e.detail)})
        except Exception as e:  # noqa: BLE001 - never let an exception escape the SSE generator
            log.exception("assistant stream failed")
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"})

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
