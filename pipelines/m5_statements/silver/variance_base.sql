-- ============================================================================
-- SILVER (M5): variance review base, expectation-bound control FPA-01
-- ============================================================================
-- Income-statement detail lines per entity x month. In scope for FPA-01 from
-- 2026 (when a prior year exists) where there is an actual or a budget.
-- ctl_fpa_01_pass: actual, budget, prior period and prior year are all present.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_m5_variance_base (
  CONSTRAINT ctl_fpa_01 EXPECT (ctl_fpa_01_pass)
)
COMMENT "FPA-01 population: P&L lines with their variance inputs. ctl_fpa_01_pass = actual, budget, prior period and prior year present (2026 onward)."
AS
SELECT
  l.line_code AS fsli_code, l.line_name, l.line_order, l.entity_code, l.region, l.period, l.period_status, l.fiscal_year,
  l.actual_usd, l.prior_period_usd, l.prior_year_usd, l.budget_usd, l.budget_mtd_usd, l.forecast_usd,
  COALESCE(l.mtd_flux_in_scope, true) AS mtd_flux_in_scope,
  l.period >= '2026-01' AND (l.actual_usd <> 0 OR l.budget_usd IS NOT NULL) AS in_review_scope,
  NOT (l.period >= '2026-01' AND (l.actual_usd <> 0 OR l.budget_usd IS NOT NULL))
    OR (l.actual_usd IS NOT NULL AND l.budget_usd IS NOT NULL AND l.prior_period_usd IS NOT NULL AND l.prior_year_usd IS NOT NULL) AS ctl_fpa_01_pass
FROM ${schema}.gold_fact_statement_lines l
WHERE l.statement = 'IS' AND l.line_type = 'detail';
