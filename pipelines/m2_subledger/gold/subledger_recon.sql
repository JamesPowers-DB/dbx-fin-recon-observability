-- ============================================================================
-- GOLD (M2): subledger-to-GL tie-outs per entity x month end (SLR-01/02/03 population)
-- ============================================================================
-- Cumulative (inception-to-date) comparison, in functional currency:
--   AR      open Salesforce invoices (invoices - receipts)  vs GL 11000 balance
--   AP      open Oracle AP invoices (invoices - payments)    vs -(GL 20000 balance)
--   PAYROLL Workday payroll cost (gross + employer taxes)    vs GL payroll costing (expense lines)
-- Tolerance (POL-FC-01 3.1): greater of tolerance_pct x basis and tolerance_usd
-- converted at the month's rate. Basis = |subledger balance| for AR and AP, and
-- |the month's payroll cost| for PAYROLL (a cumulative basis would swamp breaks). The active month uses data
-- through yesterday.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m2_subledger_recon
COMMENT "Subledger-to-GL tie-out per recon_type (AR, AP, PAYROLL) x entity x month end: subledger balance, GL balance, difference (functional and USD), tolerance, in_tolerance."
AS
WITH params AS (
  SELECT control_id, CAST(parameters['tolerance_pct'] AS DOUBLE) AS tol_pct, CAST(parameters['tolerance_usd'] AS DOUBLE) AS tol_usd
  FROM ${schema}.silver_control_library WHERE control_id IN ('SLR-01', 'SLR-02', 'SLR-03')
), mv AS (
  SELECT 'AR' AS recon_type, entity_code, date_format(invoice_date, 'yyyy-MM') AS period, SUM(amount) AS sub_delta, 0 AS gl_delta
  FROM ${schema}.silver_ar_invoice GROUP BY ALL
  UNION ALL SELECT 'AR', entity_code, date_format(payment_date, 'yyyy-MM'), -SUM(amount), 0 FROM ${schema}.silver_ar_payment GROUP BY ALL
  UNION ALL SELECT 'AP', entity_code, date_format(gl_date, 'yyyy-MM'), SUM(invoice_amount), 0 FROM ${schema}.silver_ap_invoice GROUP BY ALL
  UNION ALL SELECT 'AP', entity_code, date_format(check_date, 'yyyy-MM'), -SUM(amount), 0 FROM ${schema}.silver_ap_payment GROUP BY ALL
  UNION ALL SELECT 'PAYROLL', entity_code, date_format(payment_date, 'yyyy-MM'), SUM(payroll_cost), 0 FROM ${schema}.silver_payroll_result GROUP BY ALL
  UNION ALL SELECT CASE account_code WHEN '11000' THEN 'AR' ELSE 'AP' END, entity_code, period, 0,
                   SUM(CASE account_code WHEN '11000' THEN entered_net ELSE -entered_net END)
            FROM ${schema}.gold_fact_gl_lines WHERE account_code IN ('11000', '20000') GROUP BY ALL
  UNION ALL SELECT 'PAYROLL', entity_code, period, 0, SUM(entered_net)
            FROM ${schema}.gold_fact_gl_lines
            WHERE je_source = 'Payroll' AND je_category = 'Payroll Costing' AND account_code <> '22000' GROUP BY ALL
), grid AS (
  SELECT t.recon_type, e.entity_code, e.currency_code, p.period, p.status
  FROM (SELECT explode(array('AR', 'AP', 'PAYROLL')) AS recon_type) t
  CROSS JOIN ${schema}.gold_dim_entity e
  CROSS JOIN ${schema}.gold_dim_period p
  WHERE p.status IN ('CLOSED', 'ACTIVE') AND p.period >= '2024-12'
), monthly AS (
  SELECT g.recon_type, g.entity_code, g.currency_code, g.period, g.status,
         COALESCE(SUM(mv.sub_delta), 0) AS sub_delta, COALESCE(SUM(mv.gl_delta), 0) AS gl_delta
  FROM grid g LEFT JOIN mv ON mv.recon_type = g.recon_type AND mv.entity_code = g.entity_code AND mv.period = g.period
  GROUP BY ALL
), cum AS (
  SELECT *,
    SUM(sub_delta) OVER (PARTITION BY recon_type, entity_code ORDER BY period) AS subledger_balance,
    SUM(gl_delta)  OVER (PARTITION BY recon_type, entity_code ORDER BY period) AS gl_balance
  FROM monthly
)
SELECT
  c.recon_type,
  concat(c.recon_type, ' ', c.entity_code)                                         AS recon_object,
  c.entity_code, c.period, c.status AS period_status, c.currency_code,
  c.gl_balance                                                                     AS book_balance,
  c.subledger_balance                                                              AS external_balance,
  c.subledger_balance - c.gl_balance                                               AS difference,
  (c.subledger_balance - c.gl_balance) * COALESCE(fx.usd_rate, 1.0)                AS difference_usd,
  greatest(p.tol_pct * CASE c.recon_type WHEN 'PAYROLL' THEN abs(c.sub_delta) ELSE abs(c.subledger_balance) END,
           p.tol_usd / COALESCE(fx.usd_rate, 1.0))                                 AS tolerance_amount,
  abs(c.subledger_balance - c.gl_balance)
    <= greatest(p.tol_pct * CASE c.recon_type WHEN 'PAYROLL' THEN abs(c.sub_delta) ELSE abs(c.subledger_balance) END,
                p.tol_usd / COALESCE(fx.usd_rate, 1.0))                            AS in_tolerance,
  CASE c.recon_type WHEN 'AP' THEN 'SLR-01' WHEN 'AR' THEN 'SLR-02' ELSE 'SLR-03' END AS control_id,
  COALESCE(fx.usd_rate, 1.0)                                                       AS usd_rate
FROM cum c
JOIN params p ON p.control_id = CASE c.recon_type WHEN 'AP' THEN 'SLR-01' WHEN 'AR' THEN 'SLR-02' ELSE 'SLR-03' END
LEFT JOIN ${schema}.gold_dim_fx_rate fx ON fx.period = c.period AND fx.currency_code = c.currency_code
WHERE c.period >= '2025-01';
