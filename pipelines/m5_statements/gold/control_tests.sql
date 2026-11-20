-- ============================================================================
-- GOLD (M5): control populations and exceptions (FSC-01..04, FPA-01..04)
-- ============================================================================
-- GAAP integrity (the original repo's browser-side "GAAP checks", now tested in
-- the pipeline on every update):
--   FSC-01 trial balance: cumulative debits = credits (all lines, incl. unmapped)
--   FSC-02 balance sheet: total assets = total liabilities + equity
--   FSC-03 cash flow: ending cash = balance-sheet cash
--   FSC-04 equity roll-forward: change in retained earnings = net income
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m5_integrity
COMMENT "Statement integrity per entity x month: trial-balance difference, A - (L + E), CF ending cash - BS cash, RE roll-forward difference (USD)."
AS
WITH s AS (
  SELECT entity_code, period,
    max(CASE WHEN line_code = 'BS-T20' THEN actual_usd END) AS total_assets,
    max(CASE WHEN line_code = 'BS-T60' THEN actual_usd END) AS total_le,
    max(CASE WHEN line_code = 'CF-T60' THEN actual_usd END) AS cf_end_cash,
    max(CASE WHEN line_code = 'BS-100' THEN actual_usd END) AS bs_cash,
    max(CASE WHEN line_code = 'BS-510' THEN actual_usd END) AS retained_earnings,
    max(CASE WHEN line_code = 'BS-510' THEN prior_period_usd END) AS retained_earnings_pp,
    max(CASE WHEN line_code = 'IS-T60' THEN actual_usd END) AS net_income
  FROM ${schema}.gold_fact_statement_lines GROUP BY entity_code, period
), tb AS (
  SELECT l.entity_code, d.period, SUM(l.accounted_net_usd) AS tb_difference
  FROM ${schema}.gold_fact_gl_lines l JOIN ${schema}.gold_dim_period d ON l.accounting_date <= d.period_end
  WHERE d.status IN ('CLOSED', 'ACTIVE') AND d.period >= '2025-01'
  GROUP BY l.entity_code, d.period
)
SELECT s.entity_code, s.period,
  COALESCE(tb.tb_difference, 0)                                          AS tb_difference_usd,
  s.total_assets - s.total_le                                            AS bs_difference_usd,
  s.cf_end_cash - s.bs_cash                                              AS cf_difference_usd,
  (s.retained_earnings - s.retained_earnings_pp) - s.net_income          AS re_rollforward_difference_usd
FROM s LEFT JOIN tb ON tb.entity_code = s.entity_code AND tb.period = s.period;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m5_population
COMMENT "Populations tested by the statement and variance controls, per control x entity x month."
AS
SELECT c.control_id, i.entity_code, i.period, COUNT(*) AS population_count, CAST(0 AS DOUBLE) AS population_amount_usd
FROM ${schema}.gold_m5_integrity i CROSS JOIN (SELECT explode(array('FSC-01', 'FSC-02', 'FSC-03', 'FSC-04')) AS control_id) c
GROUP BY ALL
UNION ALL
SELECT 'FPA-01', entity_code, period, COUNT(*), SUM(abs(actual_usd)) FROM ${schema}.silver_m5_variance_base WHERE in_review_scope GROUP BY ALL
UNION ALL
SELECT 'FPA-02', entity_code, period, COUNT(*), SUM(abs(actual_usd)) FROM ${schema}.gold_fact_variance_lines WHERE in_flux_scope GROUP BY ALL
UNION ALL
SELECT c.control_id, v.entity_code, v.period, COUNT(*), SUM(abs(v.variance_usd))
FROM ${schema}.gold_fact_variance_lines v CROSS JOIN (SELECT explode(array('FPA-03', 'FPA-04')) AS control_id) c
WHERE v.is_material GROUP BY ALL;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m5_exceptions
COMMENT "Statement integrity and variance-review exceptions. record_key = entity|period (FSC) or period|entity|fsli (FPA)."
AS
WITH p AS (
  SELECT
    max(CASE WHEN control_id = 'FSC-01' THEN CAST(parameters['tolerance_usd'] AS DOUBLE) END) AS tol_tb,
    max(CASE WHEN control_id = 'FSC-02' THEN CAST(parameters['tolerance_usd'] AS DOUBLE) END) AS tol_bs,
    max(CASE WHEN control_id = 'FSC-03' THEN CAST(parameters['tolerance_usd'] AS DOUBLE) END) AS tol_cf,
    max(CASE WHEN control_id = 'FSC-04' THEN CAST(parameters['tolerance_usd'] AS DOUBLE) END) AS tol_re
  FROM ${schema}.silver_control_library
), i AS (SELECT * FROM ${schema}.gold_m5_integrity), v AS (SELECT * FROM ${schema}.gold_fact_variance_lines)
SELECT 'FSC-01' AS control_id, i.entity_code, i.period, concat(i.entity_code, '|', i.period) AS record_key, 'trial_balance' AS record_type,
       abs(i.tb_difference_usd) AS amount_usd, concat('Trial balance out of balance by USD ', format_number(i.tb_difference_usd, 2)) AS detected_value,
       last_day(to_date(concat(i.period, '-01'))) AS item_date, 'gold_m5_integrity' AS source_table,
       concat(i.entity_code, '|', i.period) AS source_primary_key, map('difference_usd', CAST(i.tb_difference_usd AS STRING)) AS lineage
FROM i CROSS JOIN p WHERE abs(i.tb_difference_usd) > p.tol_tb
UNION ALL
SELECT 'FSC-02', i.entity_code, i.period, concat(i.entity_code, '|', i.period), 'balance_sheet', abs(i.bs_difference_usd),
       concat('Assets differ from liabilities + equity by USD ', format_number(i.bs_difference_usd, 2)),
       last_day(to_date(concat(i.period, '-01'))), 'gold_m5_integrity', concat(i.entity_code, '|', i.period),
       map('difference_usd', CAST(i.bs_difference_usd AS STRING))
FROM i CROSS JOIN p WHERE abs(i.bs_difference_usd) > p.tol_bs
UNION ALL
SELECT 'FSC-03', i.entity_code, i.period, concat(i.entity_code, '|', i.period), 'cash_flow', abs(i.cf_difference_usd),
       concat('Cash flow ending cash differs from balance-sheet cash by USD ', format_number(i.cf_difference_usd, 2)),
       last_day(to_date(concat(i.period, '-01'))), 'gold_m5_integrity', concat(i.entity_code, '|', i.period),
       map('difference_usd', CAST(i.cf_difference_usd AS STRING))
FROM i CROSS JOIN p WHERE abs(i.cf_difference_usd) > p.tol_cf
UNION ALL
SELECT 'FSC-04', i.entity_code, i.period, concat(i.entity_code, '|', i.period), 'equity_rollforward', abs(i.re_rollforward_difference_usd),
       concat('Retained earnings movement differs from net income by USD ', format_number(i.re_rollforward_difference_usd, 2)),
       last_day(to_date(concat(i.period, '-01'))), 'gold_m5_integrity', concat(i.entity_code, '|', i.period),
       map('difference_usd', CAST(i.re_rollforward_difference_usd AS STRING))
FROM i CROSS JOIN p WHERE abs(i.re_rollforward_difference_usd) > p.tol_re
UNION ALL
SELECT 'FPA-01', b.entity_code, b.period, concat_ws('|', b.period, b.entity_code, b.fsli_code), 'variance_line', CAST(0 AS DOUBLE),
       concat('Missing variance inputs for ', b.line_name), last_day(to_date(concat(b.period, '-01'))), 'silver_m5_variance_base',
       concat_ws('|', b.period, b.entity_code, b.fsli_code), map('fsli_code', b.fsli_code)
FROM ${schema}.silver_m5_variance_base b WHERE NOT b.ctl_fpa_01_pass
UNION ALL
SELECT 'FPA-02', v.entity_code, v.period, v.variance_key, 'variance_line', abs(v.variance_usd),
       concat(v.line_name, ': actual ', format_number(v.actual_usd, 0), ' vs ', CASE WHEN v.period_status = 'CLOSED' THEN 'budget ' ELSE 'MTD budget ' END,
              format_number(v.budget_compare_usd, 0), ' (', format_number(100 * v.variance_pct, 1), '%, ', CASE WHEN v.is_favorable THEN 'favorable' ELSE 'unfavorable' END, ')'),
       last_day(to_date(concat(v.period, '-01'))), 'gold_fact_variance_lines', v.variance_key,
       map('fsli_code', v.fsli_code, 'variance_usd', CAST(v.variance_usd AS STRING))
FROM v WHERE v.is_material
UNION ALL
SELECT 'FPA-03', v.entity_code, v.period, v.variance_key, 'variance_line', abs(v.variance_usd),
       CASE WHEN v.explained_by IS NULL THEN concat('Material variance on ', v.line_name, ' has no controller explanation')
            ELSE concat('Explanation for ', v.line_name, ' recorded late (', v.explained_at, ', due ', v.explanation_due, ')') END,
       last_day(to_date(concat(v.period, '-01'))), 'gold_fact_variance_lines', v.variance_key,
       map('fsli_code', v.fsli_code, 'variance_usd', CAST(v.variance_usd AS STRING))
FROM v WHERE v.is_material AND (v.explained_by IS NULL OR (v.explanation_due IS NOT NULL AND to_date(v.explained_at) > v.explanation_due))
UNION ALL
SELECT 'FPA-04', v.entity_code, v.period, v.variance_key, 'variance_line', abs(v.variance_usd),
       CASE WHEN v.acknowledged_by IS NULL THEN concat('Explanation for ', v.line_name, ' not yet acknowledged by a reviewer')
            ELSE concat('Explanation for ', v.line_name, ' acknowledged by its own author (', v.acknowledged_by, ')') END,
       last_day(to_date(concat(v.period, '-01'))), 'gold_fact_variance_lines', v.variance_key,
       map('fsli_code', v.fsli_code, 'explained_by', COALESCE(v.explained_by, ''), 'acknowledged_by', COALESCE(v.acknowledged_by, ''))
FROM v WHERE v.is_material AND v.explained_by IS NOT NULL AND NOT v.independently_acknowledged;
