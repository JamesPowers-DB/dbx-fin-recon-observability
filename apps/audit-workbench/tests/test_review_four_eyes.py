"""Four-eyes rules in backend/review.py, enforced server-side (no Lakebase needed).

  cd apps/audit-workbench && uv run --no-project --with-requirements requirements.txt --with pytest pytest -q tests
"""
import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException

from backend import lakebase, review


class _Conn:
    def __init__(self, sink):
        self.sink = sink

    async def execute(self, sql, params=None):
        self.sink.append(params)

    async def commit(self):
        pass


@pytest.fixture
def store(monkeypatch):
    rows: list = []
    monkeypatch.setattr(lakebase, "is_configured", lambda: True)

    @asynccontextmanager
    async def fake_conn():
        yield _Conn(rows)

    monkeypatch.setattr(lakebase, "db_conn", fake_conn)

    async def no_live(*a, **k):
        return []

    monkeypatch.setattr(review, "live_actions", no_live)
    return rows


def run(coro):
    return asyncio.run(coro)


PROPOSED = [{"action": "propose", "disposition": "adjusted", "actor_email": "preparer@corvane.example", "created_at": "2026-11-18T10:00:00"}]


def test_proposer_cannot_approve(store):
    with pytest.raises(HTTPException) as e:
        run(review.record("exception", "x1", "2026-11", "approve", "Preparer@corvane.example", "reviewer", history=PROPOSED))
    assert e.value.status_code == 403 and "Four-eyes" in e.value.detail
    assert store == []


def test_other_reviewer_can_approve(store):
    rec = run(review.record("exception", "x1", "2026-11", "approve", "reviewer@corvane.example", "reviewer", history=PROPOSED))
    assert rec["state_before"] == "proposed" and len(store) == 1


def test_nothing_to_approve(store):
    with pytest.raises(HTTPException) as e:
        run(review.record("exception", "x2", "2026-11", "approve", "reviewer@corvane.example", "reviewer", history=[]))
    assert e.value.status_code == 409


def test_author_cannot_acknowledge_own_explanation(store):
    hist = [{"action": "explain", "comment": "driver", "actor_email": "controller@corvane.example", "created_at": "2026-11-18T10:00:00"}]
    with pytest.raises(HTTPException) as e:
        run(review.record("variance", "2026-11|US01|IS-310", "2026-11", "acknowledge", "controller@corvane.example", "reviewer", history=hist))
    assert e.value.status_code == 403
    rec = run(review.record("variance", "2026-11|US01|IS-310", "2026-11", "acknowledge", "auditor@corvane.example", "reviewer", history=hist))
    assert rec["action"] == "acknowledge"


def test_latest_state_folds_timeline():
    st = review.latest_state(PROPOSED + [{"action": "approve", "actor_email": "r@corvane.example", "created_at": "2026-11-18T12:00:00"}])
    assert st["disposition_status"] == "approved" and st["proposed_by"] == "preparer@corvane.example"
