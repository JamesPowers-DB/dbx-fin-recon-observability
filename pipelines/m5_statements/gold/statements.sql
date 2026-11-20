-- ============================================================================
-- GOLD (M5): financial statements per entity x month (the final artifact)
-- ============================================================================
-- Built from the GL (accounted USD) with the chart's statement mapping. The
-- balance sheet's retained earnings include cumulative results (no year-end
-- close entries). The cash flow is the indirect method from balance-sheet
-- movements. Accounts missing from the chart are excluded, which is what
-- FSC-02 and FSC-03 then catch.
-- gold_m5_statement_actuals: long table of every line's actual.
-- gold_fact_statement_lines: + prior period, prior year, budget, phased MTD budget, forecast.
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m5_statement_actuals
COMMENT "Statement line actuals (USD) per entity and month: income statement (period), balance sheet (period end), cash flow (period). Subtotals included."
AS
WITH periods AS (
  SELECT period, prior_period FROM ${schema}.gold_dim_period WHERE status IN ('CLOSED', 'ACTIVE') AND period >= '2024-12'
), grid AS (
  SELECT e.entity_code, p.period, p.prior_period FROM ${schema}.gold_dim_entity e CROSS JOIN periods p
), mov AS (
  SELECT entity_code, period,
    SUM(CASE WHEN fsli_code = 'IS-100' THEN -accounted_net_usd ELSE 0 END) AS rev_sub,
    SUM(CASE WHEN fsli_code = 'IS-110' THEN -accounted_net_usd ELSE 0 END) AS rev_hw,
    SUM(CASE WHEN fsli_code = 'IS-120' THEN -accounted_net_usd ELSE 0 END) AS rev_svc,
    SUM(CASE WHEN fsli_code = 'IS-200' THEN accounted_net_usd ELSE 0 END)  AS cor,
    SUM(CASE WHEN fsli_code = 'IS-300' THEN accounted_net_usd ELSE 0 END)  AS rnd,
    SUM(CASE WHEN fsli_code = 'IS-310' THEN accounted_net_usd ELSE 0 END)  AS snm,
    SUM(CASE WHEN fsli_code = 'IS-320' THEN accounted_net_usd ELSE 0 END)  AS gna,
    SUM(CASE WHEN fsli_code = 'IS-330' THEN accounted_net_usd ELSE 0 END)  AS dna,
    SUM(CASE WHEN fsli_code = 'IS-400' THEN accounted_net_usd ELSE 0 END)  AS interest,
    SUM(CASE WHEN fsli_code = 'IS-500' THEN accounted_net_usd ELSE 0 END)  AS tax,
    SUM(CASE WHEN fsli_code = 'BS-100' THEN accounted_net_usd ELSE 0 END)  AS d_cash,
    SUM(CASE WHEN fsli_code = 'BS-110' THEN accounted_net_usd ELSE 0 END)  AS d_ar,
    SUM(CASE WHEN fsli_code = 'BS-120' THEN accounted_net_usd ELSE 0 END)  AS d_prepaid,
    SUM(CASE WHEN fsli_code = 'BS-130' THEN accounted_net_usd ELSE 0 END)  AS d_inventory,
    SUM(CASE WHEN fsli_code = 'BS-200' THEN accounted_net_usd ELSE 0 END)  AS d_ppe,
    SUM(CASE WHEN account_code = '15000' THEN accounted_net_usd ELSE 0 END) AS d_ppe_gross,
    SUM(CASE WHEN fsli_code = 'BS-210' THEN accounted_net_usd ELSE 0 END)  AS d_intangibles,
    SUM(CASE WHEN fsli_code = 'BS-300' THEN -accounted_net_usd ELSE 0 END) AS d_ap,
    SUM(CASE WHEN fsli_code = 'BS-310' THEN -accounted_net_usd ELSE 0 END) AS d_accrued,
    SUM(CASE WHEN fsli_code = 'BS-320' THEN -accounted_net_usd ELSE 0 END) AS d_payroll,
    SUM(CASE WHEN fsli_code = 'BS-330' THEN -accounted_net_usd ELSE 0 END) AS d_defrev,
    SUM(CASE WHEN fsli_code = 'BS-340' THEN -accounted_net_usd ELSE 0 END) AS d_taxpay,
    SUM(CASE WHEN fsli_code = 'BS-400' THEN -accounted_net_usd ELSE 0 END) AS d_ltd,
    SUM(CASE WHEN fsli_code = 'BS-500' THEN -accounted_net_usd ELSE 0 END) AS d_stock,
    SUM(CASE WHEN fsli_code = 'BS-510' THEN -accounted_net_usd ELSE 0 END) AS d_re_account
  FROM ${schema}.gold_fact_gl_lines WHERE is_mapped_account GROUP BY entity_code, period
), w0 AS (
  SELECT g.entity_code, g.period, g.prior_period,
    COALESCE(CAST(m.rev_sub AS DOUBLE), 0D) rev_sub, COALESCE(CAST(m.rev_hw AS DOUBLE), 0D) rev_hw, COALESCE(CAST(m.rev_svc AS DOUBLE), 0D) rev_svc, COALESCE(CAST(m.cor AS DOUBLE), 0D) cor,
    COALESCE(CAST(m.rnd AS DOUBLE), 0D) rnd, COALESCE(CAST(m.snm AS DOUBLE), 0D) snm, COALESCE(CAST(m.gna AS DOUBLE), 0D) gna, COALESCE(CAST(m.dna AS DOUBLE), 0D) dna,
    COALESCE(CAST(m.interest AS DOUBLE), 0D) interest, COALESCE(CAST(m.tax AS DOUBLE), 0D) tax,
    COALESCE(CAST(m.d_cash AS DOUBLE), 0D) d_cash, COALESCE(CAST(m.d_ar AS DOUBLE), 0D) d_ar, COALESCE(CAST(m.d_prepaid AS DOUBLE), 0D) d_prepaid, COALESCE(CAST(m.d_inventory AS DOUBLE), 0D) d_inventory,
    COALESCE(CAST(m.d_ppe AS DOUBLE), 0D) d_ppe, COALESCE(CAST(m.d_ppe_gross AS DOUBLE), 0D) d_ppe_gross, COALESCE(CAST(m.d_intangibles AS DOUBLE), 0D) d_intangibles,
    COALESCE(CAST(m.d_ap AS DOUBLE), 0D) d_ap, COALESCE(CAST(m.d_accrued AS DOUBLE), 0D) d_accrued, COALESCE(CAST(m.d_payroll AS DOUBLE), 0D) d_payroll, COALESCE(CAST(m.d_defrev AS DOUBLE), 0D) d_defrev,
    COALESCE(CAST(m.d_taxpay AS DOUBLE), 0D) d_taxpay, COALESCE(CAST(m.d_ltd AS DOUBLE), 0D) d_ltd, COALESCE(CAST(m.d_stock AS DOUBLE), 0D) d_stock, COALESCE(CAST(m.d_re_account AS DOUBLE), 0D) d_re_account
  FROM grid g LEFT JOIN mov m ON m.entity_code = g.entity_code AND m.period = g.period
), w AS (
  SELECT *,
    rev_sub + rev_hw + rev_svc - cor - rnd - snm - gna - dna - interest - tax AS net_income,
    SUM(d_cash) OVER win AS cash, SUM(d_ar) OVER win AS ar, SUM(d_prepaid) OVER win AS prepaid,
    SUM(d_inventory) OVER win AS inventory, SUM(d_ppe) OVER win AS ppe, SUM(d_ppe_gross) OVER win AS ppe_gross,
    SUM(d_intangibles) OVER win AS intangibles, SUM(d_ap) OVER win AS ap, SUM(d_accrued) OVER win AS accrued,
    SUM(d_payroll) OVER win AS payroll, SUM(d_defrev) OVER win AS defrev, SUM(d_taxpay) OVER win AS taxpay,
    SUM(d_ltd) OVER win AS ltd, SUM(d_stock) OVER win AS stock,
    SUM(d_re_account) OVER win
      + SUM(rev_sub + rev_hw + rev_svc - cor - rnd - snm - gna - dna - interest - tax) OVER win AS retained_earnings
  FROM w0 WINDOW win AS (PARTITION BY entity_code ORDER BY period)
), x AS (
  SELECT c.*,
    p.cash AS cash_pp, p.ar AS ar_pp, p.prepaid AS prepaid_pp, p.inventory AS inventory_pp, p.ppe_gross AS ppe_gross_pp,
    p.intangibles AS intangibles_pp, p.ap AS ap_pp, p.accrued AS accrued_pp, p.payroll AS payroll_pp, p.defrev AS defrev_pp,
    p.taxpay AS taxpay_pp, p.ltd AS ltd_pp, p.stock AS stock_pp, p.retained_earnings AS retained_earnings_pp
  FROM w c JOIN w p ON p.entity_code = c.entity_code AND p.period = c.prior_period
), y AS (
  SELECT *,
    cash + ar + prepaid + inventory                                         AS current_assets,
    cash + ar + prepaid + inventory + ppe + intangibles                     AS total_assets,
    ap + accrued + payroll + defrev + taxpay                                AS current_liabilities,
    ap + accrued + payroll + defrev + taxpay + ltd                          AS total_liabilities,
    stock + retained_earnings                                               AS total_equity,
    -(ar - ar_pp) AS cf_ar, -(prepaid - prepaid_pp) AS cf_prepaid, -(inventory - inventory_pp) AS cf_inventory,
    ap - ap_pp AS cf_ap, accrued - accrued_pp AS cf_accrued, payroll - payroll_pp AS cf_payroll,
    defrev - defrev_pp AS cf_defrev, taxpay - taxpay_pp AS cf_taxpay,
    -(ppe_gross - ppe_gross_pp) AS cf_capex, -(intangibles - intangibles_pp) AS cf_intangibles,
    ltd - ltd_pp AS cf_debt, stock - stock_pp AS cf_equity
  FROM x
), z AS (
  SELECT *,
    net_income + dna + cf_ar + cf_prepaid + cf_inventory + cf_ap + cf_accrued + cf_payroll + cf_defrev + cf_taxpay AS cfo,
    cf_capex + cf_intangibles AS cfi, cf_debt + cf_equity AS cff
  FROM y
)
SELECT entity_code, period, statement, line_code, line_name, line_order, line_type, CAST(actual_usd AS DECIMAL(20,2)) AS actual_usd
FROM z
LATERAL VIEW stack(16,
  'IS', 'IS-100', 'Subscription revenue', 10, 'detail', rev_sub,
  'IS', 'IS-110', 'Hardware revenue', 20, 'detail', rev_hw,
  'IS', 'IS-120', 'Services revenue', 30, 'detail', rev_svc,
  'IS', 'IS-T10', 'Total revenue', 40, 'subtotal', rev_sub + rev_hw + rev_svc,
  'IS', 'IS-200', 'Cost of revenue', 50, 'detail', cor,
  'IS', 'IS-T20', 'Gross profit', 60, 'subtotal', rev_sub + rev_hw + rev_svc - cor,
  'IS', 'IS-300', 'Research and development', 70, 'detail', rnd,
  'IS', 'IS-310', 'Sales and marketing', 80, 'detail', snm,
  'IS', 'IS-320', 'General and administrative', 90, 'detail', gna,
  'IS', 'IS-330', 'Depreciation and amortization', 100, 'detail', dna,
  'IS', 'IS-T30', 'Total operating expenses', 110, 'subtotal', rnd + snm + gna + dna,
  'IS', 'IS-T40', 'Operating income', 120, 'subtotal', rev_sub + rev_hw + rev_svc - cor - rnd - snm - gna - dna,
  'IS', 'IS-400', 'Interest expense', 130, 'detail', interest,
  'IS', 'IS-T50', 'Income before tax', 140, 'subtotal', rev_sub + rev_hw + rev_svc - cor - rnd - snm - gna - dna - interest,
  'IS', 'IS-500', 'Income tax expense', 150, 'detail', tax,
  'IS', 'IS-T60', 'Net income', 160, 'total', net_income
) s AS statement, line_code, line_name, line_order, line_type, actual_usd
WHERE period >= '2025-01'
UNION ALL
SELECT entity_code, period, statement, line_code, line_name, line_order, line_type, CAST(actual_usd AS DECIMAL(20,2))
FROM z
LATERAL VIEW stack(20,
  'BS', 'BS-100', 'Cash and cash equivalents', 10, 'detail', cash,
  'BS', 'BS-110', 'Accounts receivable, net', 20, 'detail', ar,
  'BS', 'BS-120', 'Prepaid expenses', 30, 'detail', prepaid,
  'BS', 'BS-130', 'Inventory', 40, 'detail', inventory,
  'BS', 'BS-T10', 'Total current assets', 50, 'subtotal', current_assets,
  'BS', 'BS-200', 'Property and equipment, net', 60, 'detail', ppe,
  'BS', 'BS-210', 'Intangible assets and goodwill', 70, 'detail', intangibles,
  'BS', 'BS-T20', 'Total assets', 80, 'total', total_assets,
  'BS', 'BS-300', 'Accounts payable', 90, 'detail', ap,
  'BS', 'BS-310', 'Accrued liabilities', 100, 'detail', accrued,
  'BS', 'BS-320', 'Payroll liabilities', 110, 'detail', payroll,
  'BS', 'BS-330', 'Deferred revenue', 120, 'detail', defrev,
  'BS', 'BS-340', 'Income taxes payable', 130, 'detail', taxpay,
  'BS', 'BS-T30', 'Total current liabilities', 140, 'subtotal', current_liabilities,
  'BS', 'BS-400', 'Long-term debt', 150, 'detail', ltd,
  'BS', 'BS-T40', 'Total liabilities', 160, 'subtotal', total_liabilities,
  'BS', 'BS-500', 'Common stock and APIC', 170, 'detail', stock,
  'BS', 'BS-510', 'Retained earnings', 180, 'detail', retained_earnings,
  'BS', 'BS-T50', 'Total equity', 190, 'subtotal', total_equity,
  'BS', 'BS-T60', 'Total liabilities and equity', 200, 'total', total_liabilities + total_equity
) s AS statement, line_code, line_name, line_order, line_type, actual_usd
WHERE period >= '2025-01'
UNION ALL
SELECT entity_code, period, statement, line_code, line_name, line_order, line_type, CAST(actual_usd AS DECIMAL(20,2))
FROM z
LATERAL VIEW stack(20,
  'CF', 'CF-100', 'Net income', 10, 'detail', net_income,
  'CF', 'CF-110', 'Depreciation and amortization', 20, 'detail', dna,
  'CF', 'CF-120', 'Change in accounts receivable', 30, 'detail', cf_ar,
  'CF', 'CF-130', 'Change in prepaid expenses', 40, 'detail', cf_prepaid,
  'CF', 'CF-140', 'Change in inventory', 50, 'detail', cf_inventory,
  'CF', 'CF-150', 'Change in accounts payable', 60, 'detail', cf_ap,
  'CF', 'CF-160', 'Change in accrued liabilities', 70, 'detail', cf_accrued,
  'CF', 'CF-170', 'Change in payroll liabilities', 80, 'detail', cf_payroll,
  'CF', 'CF-180', 'Change in deferred revenue', 90, 'detail', cf_defrev,
  'CF', 'CF-190', 'Change in income taxes payable', 100, 'detail', cf_taxpay,
  'CF', 'CF-T10', 'Net cash from operating activities', 110, 'subtotal', cfo,
  'CF', 'CF-200', 'Capital expenditures', 120, 'detail', cf_capex,
  'CF', 'CF-210', 'Intangible assets', 130, 'detail', cf_intangibles,
  'CF', 'CF-T20', 'Net cash from investing activities', 140, 'subtotal', cfi,
  'CF', 'CF-300', 'Debt', 150, 'detail', cf_debt,
  'CF', 'CF-310', 'Equity', 160, 'detail', cf_equity,
  'CF', 'CF-T30', 'Net cash from financing activities', 170, 'subtotal', cff,
  'CF', 'CF-T40', 'Net change in cash', 180, 'subtotal', cfo + cfi + cff,
  'CF', 'CF-T50', 'Beginning cash', 190, 'detail', cash_pp,
  'CF', 'CF-T60', 'Ending cash', 200, 'total', cash_pp + cfo + cfi + cff
) s AS statement, line_code, line_name, line_order, line_type, actual_usd
WHERE period >= '2025-01';

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m5_plan_by_line
COMMENT "Plan per income-statement line (USD): full-month budget, forecast, and the month-to-date phased budget (closed months: phased = full)."
AS
WITH a AS (SELECT account_code, fsli_code FROM ${schema}.gold_dim_account WHERE statement = 'IS'),
pl AS (
  SELECT p.entity_code, p.period, a.fsli_code, p.account_code, p.version_type, p.version, p.amount_usd
  FROM ${schema}.silver_plan p JOIN a ON a.account_code = p.account_code
), ph AS (
  SELECT pl.*, d.status, d.phase_linear, d.phase_payroll_runs, d.phase_period_end, d.phase_step_bd5,
         COALESCE(z.profile, 'linear') AS profile, COALESCE(z.payroll_share, 0) AS payroll_share, COALESCE(z.period_end_share, 0) AS period_end_share
  FROM pl JOIN ${schema}.gold_dim_period d ON d.period = pl.period
  LEFT JOIN ${schema}.silver_plan_phasing z ON z.account_code = pl.account_code
)
SELECT entity_code, period, fsli_code,
  SUM(CASE WHEN version_type = 'Budget' THEN amount_usd END)                                        AS budget_usd,
  SUM(CASE WHEN version_type = 'Forecast' THEN amount_usd END)                                      AS forecast_usd,
  SUM(CASE WHEN version_type = 'Budget' THEN amount_usd *
        CASE WHEN status = 'CLOSED' THEN 1.0
             WHEN profile = 'period_end' THEN phase_period_end
             WHEN profile = 'step_bd5' THEN phase_step_bd5
             ELSE payroll_share * phase_payroll_runs + period_end_share * phase_period_end
                  + (1 - payroll_share - period_end_share) * phase_linear END END)                  AS budget_mtd_usd,
  bool_and(profile <> 'period_end')                                                                 AS mtd_flux_in_scope
FROM ph GROUP BY entity_code, period, fsli_code;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_fact_statement_lines
COMMENT "Financial statement lines (IS, BS, CF) per entity x month with actual, prior period, prior year and (IS) budget, phased MTD budget and forecast, all USD. data_status COMPLETE (month elapsed) or MONTH_TO_DATE; the FINAL/DRAFT badge comes from the close (CLS-12 GO in gold_mv_close)."
AS
SELECT
  a.statement, a.line_code, a.line_name, a.line_order, a.line_type, a.entity_code, a.period,
  d.status                                                       AS period_status,
  CASE WHEN d.status = 'CLOSED' THEN 'COMPLETE' ELSE 'MONTH_TO_DATE' END AS data_status,
  d.fiscal_year, d.fiscal_quarter,
  e.region,
  a.actual_usd,
  pp.actual_usd                                                  AS prior_period_usd,
  py.actual_usd                                                  AS prior_year_usd,
  b.budget_usd, b.budget_mtd_usd, b.forecast_usd, b.mtd_flux_in_scope
FROM ${schema}.gold_m5_statement_actuals a
JOIN ${schema}.gold_dim_period d ON d.period = a.period
LEFT JOIN ${schema}.gold_dim_entity e ON e.entity_code = a.entity_code
LEFT JOIN ${schema}.gold_m5_statement_actuals pp
  ON pp.entity_code = a.entity_code AND pp.line_code = a.line_code AND pp.period = d.prior_period
LEFT JOIN ${schema}.gold_m5_statement_actuals py
  ON py.entity_code = a.entity_code AND py.line_code = a.line_code AND py.period = d.prior_year_period
LEFT JOIN ${schema}.gold_m5_plan_by_line b
  ON b.entity_code = a.entity_code AND b.fsli_code = a.line_code AND b.period = a.period;
