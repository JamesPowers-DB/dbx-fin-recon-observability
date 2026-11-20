-- ============================================================================
-- GOLD (DQ): feed freshness (DQ-01), schema drift (DQ-02), referential integrity (DQ-03)
-- ============================================================================
-- Platform-level checks on the feeds every module depends on. Freshness is in
-- business days behind the data cutoff (yesterday). Schema drift counts rows
-- whose fields did not fit the feed contract (_rescued_data) per source file.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dq_feed_status
COMMENT "Freshness per source feed (and per bank account): latest business date received, business days behind yesterday, SLA."
AS
WITH cut AS (SELECT bd_seq AS cut_seq FROM ${schema}.gold_dim_business_day WHERE cal_date = date_sub(current_date(), 1)),
p AS (
  SELECT max(CASE WHEN control_id = 'DQ-01' THEN CAST(parameters['sla_bd'] AS INT) END) AS sla_bd,
         max(CASE WHEN control_id = 'DQ-01' THEN CAST(parameters['payroll_sla_days'] AS INT) END) AS payroll_days
  FROM ${schema}.silver_control_library
), feeds AS (
  SELECT 'oracle:gl' AS feed, 'Oracle Fusion ERP' AS source_system, 'ALL' AS entity_code, max(accounting_date) AS latest_date, 'bd' AS sla_unit
  FROM ${schema}.silver_gl_journal
  UNION ALL SELECT 'oracle:ap', 'Oracle Fusion ERP', 'ALL', max(gl_date), 'bd' FROM ${schema}.silver_ap_invoice
  UNION ALL SELECT 'salesforce:billing', 'Salesforce', 'ALL', greatest(max(i.invoice_date), (SELECT max(payment_date) FROM ${schema}.silver_ar_payment)), 'bd'
            FROM ${schema}.silver_ar_invoice i
  UNION ALL SELECT 'workday:payroll', 'Workday', 'ALL', max(payment_date), 'days' FROM ${schema}.silver_payroll_result
  UNION ALL SELECT concat('bank:', bank_account), 'Bank feed (camt.053)', max(entity_code), max(statement_date), 'bd'
            FROM ${schema}.silver_bank_statement GROUP BY bank_account
)
SELECT f.feed, f.source_system, f.entity_code, f.latest_date,
       CASE WHEN f.sla_unit = 'bd' THEN cut.cut_seq - d.bd_seq ELSE datediff(date_sub(current_date(), 1), f.latest_date) END AS behind,
       f.sla_unit,
       CASE WHEN f.sla_unit = 'bd' THEN p.sla_bd ELSE p.payroll_days END AS sla,
       CASE WHEN f.sla_unit = 'bd' THEN cut.cut_seq - d.bd_seq <= p.sla_bd
            ELSE datediff(date_sub(current_date(), 1), f.latest_date) <= p.payroll_days END AS within_sla
FROM feeds f CROSS JOIN cut CROSS JOIN p
LEFT JOIN ${schema}.gold_dim_business_day d ON d.cal_date = f.latest_date;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dq_rescued_files
COMMENT "Schema-drift monitor: rows per bronze table and source file whose fields did not fit the feed contract (_rescued_data)."
AS
WITH r AS (
  SELECT 'bronze_oracle_gl_je_headers' AS bronze_table, _source_file, _rescued_data FROM ${schema}.bronze_oracle_gl_je_headers
  UNION ALL SELECT 'bronze_oracle_gl_je_lines', _source_file, _rescued_data FROM ${schema}.bronze_oracle_gl_je_lines
  UNION ALL SELECT 'bronze_oracle_ap_invoices_all', _source_file, _rescued_data FROM ${schema}.bronze_oracle_ap_invoices_all
  UNION ALL SELECT 'bronze_oracle_ap_checks_all', _source_file, _rescued_data FROM ${schema}.bronze_oracle_ap_checks_all
  UNION ALL SELECT 'bronze_sfdc_blng__invoice__c', _source_file, _rescued_data FROM ${schema}.bronze_sfdc_blng__invoice__c
  UNION ALL SELECT 'bronze_sfdc_blng__payment__c', _source_file, _rescued_data FROM ${schema}.bronze_sfdc_blng__payment__c
  UNION ALL SELECT 'bronze_workday_payroll_results', _source_file, _rescued_data FROM ${schema}.bronze_workday_payroll_results
  UNION ALL SELECT 'bronze_bank_camt053_stmt', _source_file, _rescued_data FROM ${schema}.bronze_bank_camt053_stmt
  UNION ALL SELECT 'bronze_anaplan_plan', _source_file, _rescued_data FROM ${schema}.bronze_anaplan_plan
)
SELECT bronze_table, element_at(split(_source_file, '/'), -1) AS file_name, _source_file,
       count(*) AS rows_total,
       sum(CASE WHEN _rescued_data IS NOT NULL AND _rescued_data <> '' THEN 1 ELSE 0 END) AS rows_rescued,
       max(regexp_extract(_rescued_data, '"([A-Za-z0-9_]+)"\\s*:', 1)) AS sample_rescued_field,
       regexp_extract(element_at(split(_source_file, '/'), -1), '([0-9]{4})M([0-9]{2})', 0) AS file_period_token
FROM r GROUP BY bronze_table, _source_file;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dq_population
COMMENT "Populations tested by the data-quality controls."
AS
SELECT 'DQ-01' AS control_id, entity_code, date_format(date_sub(current_date(), 1), 'yyyy-MM') AS period, COUNT(*) AS population_count,
       CAST(0 AS DOUBLE) AS population_amount_usd
FROM ${schema}.gold_dq_feed_status GROUP BY entity_code
UNION ALL
SELECT 'DQ-02', 'ALL', period, COUNT(*), CAST(0 AS DOUBLE)
FROM (SELECT COALESCE(concat(substr(file_period_token, 1, 4), '-', substr(file_period_token, 6, 2)),
                      date_format(date_sub(current_date(), 1), 'yyyy-MM')) AS period
      FROM ${schema}.gold_dq_rescued_files)
GROUP BY period
UNION ALL
SELECT 'DQ-03', entity_code, period, COUNT(*), SUM(amount_usd) FROM ${schema}.silver_dq_gl_line_integrity GROUP BY ALL;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dq_exceptions
COMMENT "Data-quality exceptions: stale feeds (DQ-01), schema drift (DQ-02), lines with unknown account or entity (DQ-03)."
AS
SELECT 'DQ-01' AS control_id, f.entity_code, date_format(date_sub(current_date(), 1), 'yyyy-MM') AS period, f.feed AS record_key,
       'feed' AS record_type, CAST(0 AS DOUBLE) AS amount_usd,
       concat(f.source_system, ' feed ', f.feed, ' is ', f.behind, ' ', CASE f.sla_unit WHEN 'bd' THEN 'business days' ELSE 'days' END,
              ' behind (latest ', f.latest_date, ', SLA ', f.sla, ')') AS detected_value,
       f.latest_date AS item_date, 'gold_dq_feed_status' AS source_table, f.feed AS source_primary_key,
       map('feed', f.feed, 'latest_date', CAST(f.latest_date AS STRING), 'behind', CAST(f.behind AS STRING)) AS lineage
FROM ${schema}.gold_dq_feed_status f WHERE NOT f.within_sla
UNION ALL
SELECT 'DQ-02', 'ALL', COALESCE(concat(substr(r.file_period_token, 1, 4), '-', substr(r.file_period_token, 6, 2)), date_format(date_sub(current_date(), 1), 'yyyy-MM')),
       concat(r.bronze_table, '|', r.file_name), 'source_file', CAST(0 AS DOUBLE),
       concat(r.rows_rescued, ' of ', r.rows_total, ' rows in ', r.file_name, ' carry fields outside the feed contract',
              CASE WHEN r.sample_rescued_field IS NOT NULL THEN concat(' (e.g. ', r.sample_rescued_field, ')') ELSE '' END),
       CAST(NULL AS DATE), r.bronze_table, r._source_file,
       map('bronze_table', r.bronze_table, 'file', r.file_name, 'rows_rescued', CAST(r.rows_rescued AS STRING))
FROM ${schema}.gold_dq_rescued_files r WHERE r.rows_rescued > 0
UNION ALL
SELECT 'DQ-03', i.entity_code, i.period, concat(i.je_header_id, ':', i.je_line_num), 'journal_line', i.amount_usd,
       concat('Journal ', i.je_header_id, ' line ', i.je_line_num, ' uses ', i.code_combination_id, ' (account ', i.account_code, ' not in the chart of accounts)'),
       i.accounting_date, 'silver_dq_gl_line_integrity', concat(i.je_header_id, ':', i.je_line_num),
       map('je_header_id', CAST(i.je_header_id AS STRING), 'code_combination_id', i.code_combination_id)
FROM ${schema}.silver_dq_gl_line_integrity i WHERE NOT i.ctl_dq_03_pass;
