-- ============================================================================
-- GOLD (M3 Journals): control populations and exceptions (JET-01 .. JET-05)
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m3_population
COMMENT "Populations tested by the journal controls: every manual journal, per control x entity x month."
AS
SELECT c.control_id, j.entity_code, j.period, COUNT(*) AS population_count, SUM(j.amount_usd) AS population_amount_usd
FROM ${schema}.gold_fact_journal_entries j
CROSS JOIN (SELECT explode(array('JET-01', 'JET-02', 'JET-03', 'JET-04', 'JET-05')) AS control_id) c
WHERE j.is_manual AND j.je_category <> 'Opening Balances'
GROUP BY ALL;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m3_exceptions
COMMENT "Journal control exceptions, one row per failing journal per control. record_key = je_header_id."
AS
WITH j AS (SELECT * FROM ${schema}.gold_fact_journal_entries WHERE je_category <> 'Opening Balances'),
lin AS (
  SELECT je_header_id, map('je_header_id', CAST(je_header_id AS STRING), 'created_by', COALESCE(created_by_user_name, CAST(created_by_user_id AS STRING)),
             'approved_by', COALESCE(CAST(approved_by_user_id AS STRING), ''), 'posted_at', CAST(posted_at AS STRING),
             'debit_accounts', debit_accounts) AS lineage
  FROM j
)
SELECT 'JET-01' AS control_id, j.entity_code, j.period, CAST(j.je_header_id AS STRING) AS record_key, 'journal' AS record_type,
       j.amount_usd, concat('Journal ', j.je_header_id, ' created and approved by user ', j.created_by_user_id) AS detected_value,
       j.accounting_date AS item_date, 'gold_fact_journal_entries' AS source_table, CAST(j.je_header_id AS STRING) AS source_primary_key, l.lineage
FROM j JOIN lin l USING (je_header_id) WHERE j.jet01_self_approved
UNION ALL
SELECT 'JET-02', j.entity_code, j.period, CAST(j.je_header_id AS STRING), 'journal', j.amount_usd,
       concat('Journal ', j.je_header_id, ' (', format_number(j.amount_usd, 0), ' USD) ',
              CASE WHEN j.approved_at IS NULL THEN 'posted without approval' ELSE concat('approved ', j.approved_at, ' after posting ', j.posted_at) END),
       j.accounting_date, 'gold_fact_journal_entries', CAST(j.je_header_id AS STRING), l.lineage
FROM j JOIN lin l USING (je_header_id) WHERE j.jet02_unapproved_over_threshold
UNION ALL
SELECT 'JET-03', j.entity_code, j.period, CAST(j.je_header_id AS STRING), 'journal', j.amount_usd,
       concat('Journal ', j.je_header_id, ' posted ', date_format(j.posted_at, 'EEE yyyy-MM-dd HH:mm'), ' by ', COALESCE(j.created_by_user_name, '')),
       j.accounting_date, 'gold_fact_journal_entries', CAST(j.je_header_id AS STRING), l.lineage
FROM j JOIN lin l USING (je_header_id) WHERE j.jet03_off_hours
UNION ALL
SELECT 'JET-04', j.entity_code, j.period, CAST(j.je_header_id AS STRING), 'journal', j.amount_usd,
       concat('Journal ', j.je_header_id, ' duplicates journal ', j.duplicate_of, ' (same account and amount within the window)'),
       j.accounting_date, 'gold_fact_journal_entries', CAST(j.je_header_id AS STRING), l.lineage
FROM j JOIN lin l USING (je_header_id) WHERE j.jet04_duplicate
UNION ALL
SELECT 'JET-05', j.entity_code, j.period, CAST(j.je_header_id AS STRING), 'journal', j.amount_usd,
       concat('Journal ', j.je_header_id, ' ', CASE WHEN j.jet05_round_amount THEN 'is a round amount' ELSE 'is an outlier' END,
              CASE WHEN j.amount_zscore IS NOT NULL THEN concat(' (z = ', format_number(j.amount_zscore, 1), ')') ELSE '' END),
       j.accounting_date, 'gold_fact_journal_entries', CAST(j.je_header_id AS STRING), l.lineage
FROM j JOIN lin l USING (je_header_id) WHERE j.jet05_outlier;
