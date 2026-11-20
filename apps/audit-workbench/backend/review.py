"""Human review actions (Lakebase): append-only, one direction to UC.

Every human action (proposing or approving a disposition, explaining or
acknowledging a variance, signing off a control or close task) is an INSERT into
audit.review_actions. Nothing is updated or deleted. run_controls'
snapshot_review_state copies the rows to UC (meta_review_actions) so the next run
applies them to control results and close status.

Four-eyes is enforced here, server-side:
  * an exception disposition cannot be approved or rejected by its proposer
  * a variance explanation cannot be acknowledged by its author
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import HTTPException

from . import lakebase

log = logging.getLogger("audit-workbench.review")
S = lakebase.SCHEMA

async def _fetch(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    async with lakebase.db_conn() as conn:
        cur = await conn.execute(sql, params)
        cols = [d.name for d in cur.description] if cur.description else []
        return [dict(zip(cols, r)) for r in await cur.fetchall()]


async def live_actions(item_type: str, item_keys: list[str] | None = None, period: str | None = None) -> list[dict]:
    if not lakebase.is_configured():
        return []
    where, params = ["item_type = %s"], [item_type]
    if item_keys is not None:
        if not item_keys:
            return []
        where.append("item_key = ANY(%s)")
        params.append(item_keys)
    if period:
        where.append("period = %s")
        params.append(period)
    try:
        return await _fetch(f"SELECT * FROM {S}.review_actions WHERE {' AND '.join(where)} ORDER BY created_at", tuple(params))
    except Exception as e:  # noqa: BLE001 - review store outage must not break read pages
        log.warning("live review actions unavailable: %s", e)
        return []


def latest_state(actions: list[dict]) -> dict:
    """Fold an item's action timeline into its current state."""
    st: dict[str, Any] = {"disposition_status": "open"}
    for a in sorted(actions, key=lambda x: str(x.get("created_at") or x.get("acted_at"))):
        act = a.get("action")
        who = a.get("actor_email")
        when = a.get("created_at") or a.get("acted_at")
        if act == "propose":
            st.update(disposition_status="proposed", disposition=a.get("disposition"), proposed_by=who, proposed_at=when,
                      comment=a.get("comment"))
        elif act == "approve":
            st.update(disposition_status="approved", approved_by=who, approved_at=when)
        elif act == "reject":
            st.update(disposition_status="rejected", rejected_by=who, rejected_at=when, comment=a.get("comment"))
        elif act == "reopen":
            st.update(disposition_status="open")
        elif act == "explain":
            st.update(explained_by=who, explained_at=when, explanation=a.get("comment"))
        elif act == "acknowledge":
            st.update(acknowledged_by=who, acknowledged_at=when)
        elif act == "signoff":
            st.update(signed_off_by=who, signed_off_at=when)
    return st


async def record(item_type: str, item_key: str, period: str | None, action: str, actor_email: str, actor_role: str,
                 disposition: str | None = None, comment: str = "", payload: dict | None = None,
                 attested_job_run_id: int | None = None, history: list[dict] | None = None) -> dict:
    if not lakebase.is_configured():
        raise HTTPException(503, "Review store (Lakebase) is not configured for this app.")
    timeline = (history or []) + await live_actions(item_type, [item_key])
    state = latest_state(timeline)
    me = actor_email.lower()
    if action in ("approve", "reject"):
        if state.get("disposition_status") != "proposed":
            raise HTTPException(409, "Nothing to approve: no disposition is awaiting review.")
        if (state.get("proposed_by") or "").lower() == me:
            raise HTTPException(403, "Four-eyes rule: you proposed this disposition, so another reviewer must approve it.")
    if action == "acknowledge":
        if not state.get("explained_by"):
            raise HTTPException(409, "Nothing to acknowledge: the variance has no explanation yet.")
        if (state.get("explained_by") or "").lower() == me:
            raise HTTPException(403, "Four-eyes rule: you wrote this explanation, so an independent reviewer must acknowledge it.")
    row = {"action_id": uuid.uuid4().hex, "item_type": item_type, "item_key": item_key, "period": period, "action": action,
           "disposition": disposition, "comment": (comment or "")[:4000], "payload": json.dumps(payload or {}),
           "actor_email": actor_email, "actor_role": actor_role, "attested_job_run_id": attested_job_run_id}
    async with lakebase.db_conn() as conn:
        await conn.execute(
            f"""INSERT INTO {S}.review_actions (action_id, item_type, item_key, period, action, disposition, comment, payload,
                  actor_email, actor_role, attested_job_run_id, created_at)
                VALUES (%(action_id)s, %(item_type)s, %(item_key)s, %(period)s, %(action)s, %(disposition)s, %(comment)s,
                        %(payload)s::jsonb, %(actor_email)s, %(actor_role)s, %(attested_job_run_id)s, now())""", row)
        await conn.commit()
    return {**row, "state_before": state.get("disposition_status")}
