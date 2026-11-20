-- ============================================================================
-- SILVER (M3 Journals): journal-level features, expectation-bound control JET-01
-- ============================================================================
-- One row per journal (all sources). Expectation ctl_jet_01 = control JET-01
-- (preparer is not the approver), WARN: every journal stays in the population
-- and failures become exceptions in gold. The pipeline event log records
-- JET-01 pass and fail counts per update.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_m3_journal_flags (
  CONSTRAINT ctl_jet_01 EXPECT (ctl_jet_01_pass)
)
COMMENT "Journal-level test features (grain: je_header_id). amount_usd = journal total (sum of accounted debits). debit_accounts = sorted debit-side natural accounts (duplicate signature). ctl_jet_01_pass = preparer is not the approver (non-manual journals pass)."
AS
SELECT
  j.*,
  NOT j.is_manual OR j.approved_by_user_id IS NULL OR j.created_by_user_id <> j.approved_by_user_id AS ctl_jet_01_pass
FROM ${schema}.gold_fact_journals j;
