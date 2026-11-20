-- ============================================================================
-- SILVER (M1 Cash): statement continuity, expectation-bound control CASH-01
-- ============================================================================
-- One row per expected statement (bank account x business day from the first
-- business day of 2025 to yesterday). The expectation name equals the control
-- id, so the pipeline event log reports CASH-01 pass and fail counts per update.
-- WARN: missing days stay in the population and become exceptions in gold.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_m1_statement_continuity (
  CONSTRAINT ctl_cash_01 EXPECT (ctl_cash_01_pass)
)
COMMENT "CASH-01 population: expected statement days per bank account. ctl_cash_01_pass = a statement was received for that business day."
AS
WITH accounts AS (
  SELECT e.entity_code, concat(e.entity_code, '-', k.kind, '-0001') AS bank_account, e.currency_code
  FROM ${schema}.silver_entity e CROSS JOIN (SELECT explode(array('OPS', 'PAY')) AS kind) k
), expected AS (
  SELECT a.entity_code, a.bank_account, d.cal_date AS statement_date, d.period
  FROM accounts a CROSS JOIN ${schema}.gold_dim_business_day d
  WHERE d.is_business_day AND d.cal_date >= DATE'2025-01-02' AND d.cal_date <= date_sub(current_date(), 1)
)
SELECT
  x.entity_code, x.bank_account, x.statement_date, x.period,
  s.statement_id,
  s.statement_id IS NOT NULL AS ctl_cash_01_pass
FROM expected x
LEFT JOIN ${schema}.silver_bank_statement s
  ON s.bank_account = x.bank_account AND s.statement_date = x.statement_date;
