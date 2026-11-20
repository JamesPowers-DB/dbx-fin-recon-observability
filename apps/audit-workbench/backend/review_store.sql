-- Audit Workbench review store (Lakebase Postgres), schema `audit`.
-- One DDL for every writer: the app runs it lazily on first connection
-- (backend/lakebase.py) and the seed_review_activity job runs it before seeding
-- on a fresh install. Statements are idempotent and executed one at a time;
-- privilege errors on objects another role created are skipped.
CREATE SCHEMA IF NOT EXISTS audit;

-- Append-only ledger of human actions. Current state of an item = its latest
-- action. item_key formats:
--   exception        <exception_id>
--   variance         <period>|<entity_code>|<fsli_code>
--   control_signoff  <control_id>|<period>
--   close_task       <period>|<task_code>
CREATE TABLE IF NOT EXISTS audit.review_actions (
    action_id           TEXT PRIMARY KEY,
    item_type           TEXT NOT NULL CHECK (item_type IN ('exception','variance','control_signoff','close_task')),
    item_key            TEXT NOT NULL,
    period              TEXT,
    action              TEXT NOT NULL CHECK (action IN ('propose','approve','reject','explain','acknowledge','signoff','reopen')),
    disposition         TEXT,
    comment             TEXT,
    payload             JSONB,
    actor_email         TEXT NOT NULL,
    actor_role          TEXT NOT NULL,
    attested_job_run_id BIGINT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_review_actions_item ON audit.review_actions (item_type, item_key, created_at);
CREATE INDEX IF NOT EXISTS idx_review_actions_created ON audit.review_actions (created_at);

CREATE TABLE IF NOT EXISTS audit.working_papers (
    exception_id     TEXT PRIMARY KEY,
    title            TEXT,
    body_md          TEXT NOT NULL,
    ai_draft_md      TEXT,
    author_email     TEXT NOT NULL,
    agent_session_id TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit.chatbot_sessions (
    session_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    title      TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS audit.chatbot_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES audit.chatbot_sessions(session_id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content    TEXT NOT NULL,
    tool_calls JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_chatbot_messages_session ON audit.chatbot_messages (session_id, created_at);

-- The deployer (project owner, DATABRICKS_SUPERUSER) reads these tables from
-- the snapshot_review_state job task. PUBLIC read keeps that working even if
-- superuser semantics change; the tables hold no secrets.
GRANT USAGE ON SCHEMA audit TO PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA audit TO PUBLIC;
