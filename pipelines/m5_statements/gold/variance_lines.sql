-- ============================================================================
-- GOLD (M5): variance lines, the management review (flux) population
-- ============================================================================
-- Closed months compare the full-month actual with the budget. The active
-- month compares the month-to-date actual with the phased MTD budget
-- (continuous flux); lines posted only at period end (D&A, tax) are out of
-- MTD scope. Material (FPA-02): |variance| > materiality_usd AND >
-- materiality_pct x |budget|. Explanations and acknowledgements come from
-- review state (close-tool history + Audit Workbench).
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_fact_variance_lines
COMMENT "Variance lines (P&L line x entity x month): actual vs budget (MTD-phased for the active close), favorable flag, materiality, z-score vs trailing 12 months, controller explanation and independent acknowledgement."
AS
WITH p AS (
  SELECT
    max(CASE WHEN control_id = 'FPA-02' THEN CAST(parameters['materiality_usd'] AS DOUBLE) END) AS mat_usd,
    max(CASE WHEN control_id = 'FPA-02' THEN CAST(parameters['materiality_pct'] AS DOUBLE) END) AS mat_pct,
    max(CASE WHEN control_id = 'FPA-02' THEN CAST(parameters['z_threshold'] AS DOUBLE) END)     AS z_thr,
    max(CASE WHEN control_id = 'FPA-03' THEN CAST(parameters['explain_within_bd'] AS INT) END)  AS explain_bd
  FROM ${schema}.silver_control_library
), b AS (
  SELECT v.*,
    CASE WHEN v.period_status = 'CLOSED' THEN v.budget_usd ELSE v.budget_mtd_usd END AS budget_compare_usd,
    v.fsli_code IN ('IS-100', 'IS-110', 'IS-120') AS is_revenue_line
  FROM ${schema}.silver_m5_variance_base v
), hist AS (
  SELECT b1.entity_code, b1.fsli_code, b1.period,
         avg(b2.actual_usd) AS trailing_avg, stddev_pop(b2.actual_usd) AS trailing_sd
  FROM b b1 JOIN b b2 ON b2.entity_code = b1.entity_code AND b2.fsli_code = b1.fsli_code
   AND b2.period_status = 'CLOSED' AND b2.period < b1.period
   AND b2.period >= date_format(add_months(to_date(concat(b1.period, '-01')), -12), 'yyyy-MM')
  GROUP BY ALL
), r AS (
  SELECT split_part(item_key, '|', 1) AS period, split_part(item_key, '|', 2) AS entity_code, split_part(item_key, '|', 3) AS fsli_code,
         explained_by, explained_at, acknowledged_by, acknowledged_at, last_comment
  FROM ${schema}.silver_review_status WHERE item_type = 'variance'
), d AS (
  SELECT period, last_business_day, bd_seq_at_period_end FROM ${schema}.gold_dim_period
)
SELECT
  b.fsli_code, b.line_name, b.line_order, b.entity_code, b.region, b.period, b.period_status, b.fiscal_year,
  b.actual_usd, b.budget_usd, b.budget_mtd_usd, b.budget_compare_usd, b.forecast_usd, b.prior_period_usd, b.prior_year_usd,
  b.actual_usd - b.budget_compare_usd                                                            AS variance_usd,
  (b.actual_usd - b.budget_compare_usd) / NULLIF(abs(b.budget_compare_usd), 0)                  AS variance_pct,
  CASE WHEN b.is_revenue_line THEN b.actual_usd >= b.budget_compare_usd ELSE b.actual_usd <= b.budget_compare_usd END AS is_favorable,
  b.period_status = 'CLOSED' OR b.mtd_flux_in_scope                                             AS in_flux_scope,
  (b.period_status = 'CLOSED' OR b.mtd_flux_in_scope) AND b.budget_compare_usd IS NOT NULL
    AND abs(b.actual_usd - b.budget_compare_usd) > p.mat_usd
    AND abs(b.actual_usd - b.budget_compare_usd) > p.mat_pct * abs(b.budget_compare_usd)        AS is_material,
  CASE WHEN b.period_status = 'CLOSED' AND h.trailing_sd > 0 THEN (b.actual_usd - h.trailing_avg) / h.trailing_sd END AS zscore,
  b.period_status = 'CLOSED' AND h.trailing_sd > 0 AND abs((b.actual_usd - h.trailing_avg) / h.trailing_sd) > p.z_thr AS is_statistical_outlier,
  concat_ws('|', b.period, b.entity_code, b.fsli_code)                                          AS variance_key,
  r.explained_by, r.explained_at, r.last_comment AS explanation, r.acknowledged_by, r.acknowledged_at,
  r.acknowledged_by IS NOT NULL AND lower(r.acknowledged_by) <> lower(COALESCE(r.explained_by, '')) AS independently_acknowledged,
  CASE WHEN b.period_status = 'CLOSED' THEN date_add(d.last_business_day, 0) END                AS identified_on,
  CASE WHEN b.period_status = 'CLOSED' THEN dd.cal_date END                                     AS explanation_due
FROM b
CROSS JOIN p
LEFT JOIN hist h ON h.entity_code = b.entity_code AND h.fsli_code = b.fsli_code AND h.period = b.period
LEFT JOIN r ON r.period = b.period AND r.entity_code = b.entity_code AND r.fsli_code = b.fsli_code
LEFT JOIN d ON d.period = b.period
LEFT JOIN ${schema}.gold_dim_business_day dd ON dd.is_business_day AND dd.bd_seq = d.bd_seq_at_period_end + 1 + p.explain_bd;
