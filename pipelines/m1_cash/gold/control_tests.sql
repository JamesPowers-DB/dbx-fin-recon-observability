-- ============================================================================
-- GOLD (M1 Cash): control populations and exceptions (CASH-01 .. CASH-04)
-- ============================================================================
-- Standard contract shared by every module (unioned by the controls spine):
--   gold_<m>_population: control_id, entity_code, period, population_count, population_amount_usd
--   gold_<m>_exceptions: control_id, entity_code, period, record_key, record_type, amount_usd,
--                        detected_value, item_date, source_table, source_primary_key, lineage
-- record_key formats match meta_planted_exceptions (the monitoring-integrity gate joins on them).
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m1_population
COMMENT "Populations tested by the cash controls, per control x entity x month."
AS
SELECT 'CASH-01' AS control_id, entity_code, period, COUNT(*) AS population_count, CAST(0 AS DOUBLE) AS population_amount_usd
FROM ${schema}.silver_m1_statement_continuity GROUP BY ALL
UNION ALL
SELECT 'CASH-02', m.entity_code, m.period, COUNT(*), SUM(abs(m.amount) * COALESCE(fx.usd_rate, 1.0))
FROM ${schema}.gold_m1_cash_match m
JOIN ${schema}.gold_dim_entity e ON e.entity_code = m.entity_code
LEFT JOIN ${schema}.gold_dim_fx_rate fx ON fx.period = m.period AND fx.currency_code = e.currency_code
GROUP BY ALL
UNION ALL
SELECT 'CASH-03', entity_code, period, COUNT(*), SUM(abs(book_balance) * usd_rate)
FROM ${schema}.gold_m1_cash_recon GROUP BY ALL
UNION ALL
SELECT 'CASH-04', m.entity_code, m.period, COUNT(*), SUM(abs(m.amount))
FROM ${schema}.gold_m1_cash_match m
CROSS JOIN (SELECT CAST(parameters['aging_bd'] AS INT) AS aging_bd FROM ${schema}.silver_control_library WHERE control_id = 'CASH-04') p
WHERE m.match_status = 'BANK_ONLY' AND m.age_bd > p.aging_bd
GROUP BY ALL;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m1_exceptions
COMMENT "Cash control exceptions: missing statements (CASH-01), unmatched aged items (CASH-02), unexplained differences (CASH-03), aged bank items without a matching advice (CASH-04)."
AS
WITH p AS (
  SELECT
    max(CASE WHEN control_id = 'CASH-02' THEN CAST(parameters['aging_bd'] AS INT) END)           AS aging_bd_02,
    max(CASE WHEN control_id = 'CASH-03' THEN CAST(parameters['max_unexplained_usd'] AS DOUBLE) END) AS max_unexplained,
    max(CASE WHEN control_id = 'CASH-04' THEN CAST(parameters['aging_bd'] AS INT) END)           AS aging_bd_04
  FROM ${schema}.silver_control_library
), m AS (
  SELECT m.*, COALESCE(fx.usd_rate, 1.0) AS usd_rate
  FROM ${schema}.gold_m1_cash_match m
  JOIN ${schema}.gold_dim_entity e ON e.entity_code = m.entity_code
  LEFT JOIN ${schema}.gold_dim_fx_rate fx ON fx.period = m.period AND fx.currency_code = e.currency_code
), advices AS (
  SELECT advice_reference, amount FROM ${schema}.silver_document_fields WHERE doc_type = 'bank_advices'
)
SELECT 'CASH-01' AS control_id, c.entity_code, c.period, concat(c.bank_account, '|', c.statement_date) AS record_key,
       'bank_statement' AS record_type, CAST(0 AS DOUBLE) AS amount_usd,
       concat('No statement received for ', c.bank_account, ' on ', c.statement_date) AS detected_value,
       c.statement_date AS item_date, 'silver_m1_statement_continuity' AS source_table,
       concat(c.bank_account, '|', c.statement_date) AS source_primary_key,
       map('bank_account', c.bank_account, 'statement_date', CAST(c.statement_date AS STRING)) AS lineage
FROM ${schema}.silver_m1_statement_continuity c WHERE NOT c.ctl_cash_01_pass
UNION ALL
SELECT 'CASH-02', m.entity_code, m.period, m.record_key, lower(m.match_status), abs(m.amount) * m.usd_rate,
       concat(CASE m.match_status WHEN 'BANK_ONLY' THEN 'Bank entry with no book entry: ' ELSE 'Book entry with no bank entry: ' END,
              COALESCE(m.remittance_info, m.journal_name, ''), ' (', format_number(m.amount, 2), ' ', COALESCE(m.currency_code, ''), ', ', m.age_bd, ' business days)'),
       m.item_date, CASE m.match_status WHEN 'BANK_ONLY' THEN 'silver_bank_entry' ELSE 'gold_m1_book_cash_lines' END,
       COALESCE(m.bank_entry_ref, m.line_key),
       map('bank_account', m.bank_account, 'bank_entry_ref', COALESCE(m.bank_entry_ref, ''), 'je_header_id', COALESCE(CAST(m.je_header_id AS STRING), ''),
           'end_to_end_id', COALESCE(m.end_to_end_id, ''), 'age_bd', CAST(m.age_bd AS STRING))
FROM m CROSS JOIN p WHERE m.match_status <> 'MATCHED' AND m.age_bd > p.aging_bd_02
UNION ALL
SELECT 'CASH-03', r.entity_code, r.period, concat(r.recon_object, '|', r.period), 'bank_reconciliation', abs(r.unexplained_amount_usd),
       concat('Unexplained difference ', format_number(r.unexplained_amount, 2), ' ', r.currency_code, ' on ', r.recon_object),
       last_day(to_date(concat(r.period, '-01'))), 'gold_m1_cash_recon', concat(r.recon_object, '|', r.period),
       map('bank_account', r.recon_object, 'book_balance', CAST(r.book_balance AS STRING), 'bank_balance', CAST(r.external_balance AS STRING))
FROM ${schema}.gold_m1_cash_recon r CROSS JOIN p WHERE abs(r.unexplained_amount_usd) > p.max_unexplained
UNION ALL
SELECT 'CASH-04', m.entity_code, m.period, m.record_key, 'bank_entry', abs(m.amount) * m.usd_rate,
       concat(CASE WHEN a.advice_reference IS NULL THEN 'No bank advice on file for ' ELSE 'Bank advice amount disagrees for ' END, m.bank_entry_ref),
       m.item_date, 'silver_bank_entry', m.bank_entry_ref,
       map('bank_account', m.bank_account, 'bank_entry_ref', m.bank_entry_ref, 'advice_amount', COALESCE(CAST(a.amount AS STRING), ''))
FROM m CROSS JOIN p
LEFT JOIN advices a ON a.advice_reference = m.bank_entry_ref
WHERE m.match_status = 'BANK_ONLY' AND m.age_bd > p.aging_bd_04
  AND (a.advice_reference IS NULL OR abs(abs(m.amount) - a.amount) > 0.01);
