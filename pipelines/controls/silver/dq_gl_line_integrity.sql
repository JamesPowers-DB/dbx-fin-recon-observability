-- ============================================================================
-- SILVER (DQ): referential integrity of GL lines, expectation-bound control DQ-03
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_dq_gl_line_integrity (
  CONSTRAINT ctl_dq_03 EXPECT (ctl_dq_03_pass)
)
COMMENT "DQ-03 population: every GL journal line. ctl_dq_03_pass = the natural account exists in the chart of accounts and the entity is a known legal entity."
AS
SELECT l.je_header_id, l.je_line_num, l.code_combination_id, l.entity_code, l.account_code,
       date_format(l.accounting_date, 'yyyy-MM') AS period, l.accounting_date,
       CAST(l.accounted_dr + l.accounted_cr AS DOUBLE) AS amount_usd,
       a.account_code IS NOT NULL AND e.entity_code IS NOT NULL AS ctl_dq_03_pass
FROM ${schema}.silver_gl_line l
LEFT JOIN ${schema}.silver_account a ON a.account_code = l.account_code
LEFT JOIN ${schema}.silver_entity e ON e.entity_code = l.entity_code;
