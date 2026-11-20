"""Genie space access as the caller (OBO genie scope). The space is resolved by title."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .auth import CallerIdentity
from .config import get_settings

log = logging.getLogger("audit-workbench.genie")
_space_cache: dict[str, str] = {}


def _req(caller: CallerIdentity, method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    s = get_settings()
    try:
        r = httpx.request(method, f"{s.workspace_url}{path}", json=body, timeout=30,
                          headers={"Authorization": f"Bearer {caller.access_token}"})
        if r.status_code >= 400:
            return {"error_code": f"HTTP_{r.status_code}", "message": r.text[:300]}
        return r.json() if r.content else {}
    except Exception as e:  # noqa: BLE001 - surfaced to the caller as a tool error
        return {"error_code": "GENIE_REQUEST_FAILED", "message": str(e)}


def resolve_space_id(caller: CallerIdentity) -> str | None:
    s = get_settings()
    if s.genie_space_id:
        return s.genie_space_id
    if s.genie_space_title in _space_cache:
        return _space_cache[s.genie_space_title]
    token = None
    for _ in range(20):
        res = _req(caller, "GET", "/api/2.0/genie/spaces?page_size=100" + (f"&page_token={token}" if token else ""))
        for sp in res.get("spaces", []) or []:
            if sp.get("title") == s.genie_space_title:
                _space_cache[s.genie_space_title] = sp["space_id"]
                return sp["space_id"]
        token = res.get("next_page_token")
        if not token:
            break
    return None


def _interval(attempt: int) -> float:
    return 0.5 if attempt < 4 else 1.0 if attempt < 8 else 2.0


def ask(caller: CallerIdentity, question: str) -> dict[str, Any]:
    space_id = resolve_space_id(caller)
    if not space_id:
        return {"ok": False, "error": f"No Genie space titled '{get_settings().genie_space_title}'.",
                "hint": "Run the setup job (provision_genie)."}
    start = _req(caller, "POST", f"/api/2.0/genie/spaces/{space_id}/start-conversation", {"content": question})
    conv, msg_id = start.get("conversation_id"), start.get("message_id")
    if not conv or not msg_id:
        return {"ok": False, "error": "Failed to start a Genie conversation", "detail": start.get("message")}
    for attempt in range(60):
        time.sleep(_interval(attempt))
        msg = _req(caller, "GET", f"/api/2.0/genie/spaces/{space_id}/conversations/{conv}/messages/{msg_id}")
        st = msg.get("status")
        if st == "COMPLETED":
            atts = msg.get("attachments", []) or []
            qa = next((a for a in atts if "query" in a), {})
            q = qa.get("query", {})
            t = next((a.get("text", {}) for a in atts if "text" in a), {})
            cols, rows, n = [], [], None
            if q.get("query"):
                # Rows come from the attachment endpoint; the message-level query-result
                # returns a protobuf manifest without data_array.
                qr = _req(caller, "GET", f"/api/2.0/genie/spaces/{space_id}/conversations/{conv}/messages/{msg_id}"
                                         f"/attachments/{qa.get('attachment_id')}/query-result")
                sr = qr.get("statement_response") or qr
                man = sr.get("manifest") or {}
                cols = [c.get("name") for c in (man.get("schema") or {}).get("columns", [])]
                data = (sr.get("result") or {}).get("data_array") or []
                rows = [dict(zip(cols, r)) for r in data[:20]]
                n = man.get("total_row_count") or len(data)
            return {"ok": True, "question": question, "answer": t.get("content") or q.get("description", ""),
                    "sql": q.get("query", ""), "columns": cols, "rows": rows, "row_count": n,
                    "conversation_id": conv, "message_id": msg_id, "space_id": space_id}
        if st in ("FAILED", "CANCELLED") or msg.get("error_code"):
            return {"ok": False, "error": f"Genie {st or msg.get('error_code')}", "detail": msg.get("error") or msg.get("message")}
    return {"ok": False, "error": "Genie timed out. Try a narrower question."}
