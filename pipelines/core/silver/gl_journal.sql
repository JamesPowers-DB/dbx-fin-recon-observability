-- ============================================================================
-- SILVER: GL journals (headers) and journal lines
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_gl_journal
COMMENT "Conformed GL journal headers from Oracle Fusion. One row per je_header_id. created_by/approved_by are ERP user ids (fnd_user)."
AS
SELECT
  'Oracle Fusion ERP'                                 AS source_system,
  'gl_je_headers'                                     AS source_table,
  CAST(je_header_id AS STRING)                        AS source_primary_key,
  CAST(je_header_id AS BIGINT)                        AS je_header_id,
  CAST(ledger_id AS BIGINT)                           AS ledger_id,
  period_name,
  je_source,
  je_category,
  name                                                AS journal_name,
  description,
  status,
  CAST(default_effective_date AS DATE)                AS accounting_date,
  CAST(posted_date AS TIMESTAMP)                      AS posted_at,
  CAST(created_by AS BIGINT)                          AS created_by_user_id,
  CAST(creation_date AS TIMESTAMP)                    AS created_at,
  approval_status_code,
  CAST(NULLIF(approved_by, '') AS BIGINT)             AS approved_by_user_id,
  CAST(NULLIF(approval_date, '') AS TIMESTAMP)        AS approved_at,
  currency_code,
  CAST(running_total_dr AS DECIMAL(18,2))             AS total_dr,
  CAST(running_total_cr AS DECIMAL(18,2))             AS total_cr,
  je_source IN ('Manual', 'Spreadsheet')              AS is_manual,
  _source_file,
  _ingested_at
FROM ${schema}.bronze_oracle_gl_je_headers;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_gl_line
COMMENT "Conformed GL journal lines. Amounts typed; the code combination is split into entity, segment, natural account. reference_1 = subledger document id (lineage), reference_2 = bank EndToEndId on cash lines."
AS
SELECT
  'Oracle Fusion ERP'                                          AS source_system,
  'gl_je_lines'                                                AS source_table,
  concat(je_header_id, ':', je_line_num)                       AS source_primary_key,
  CAST(je_header_id AS BIGINT)                                 AS je_header_id,
  CAST(je_line_num AS INT)                                     AS je_line_num,
  code_combination_id,
  split_part(code_combination_id, '-', 1)                      AS entity_code,
  split_part(code_combination_id, '-', 2)                      AS segment_code,
  split_part(code_combination_id, '-', 3)                      AS account_code,
  CAST(entered_dr AS DECIMAL(18,2))                            AS entered_dr,
  CAST(entered_cr AS DECIMAL(18,2))                            AS entered_cr,
  CAST(accounted_dr AS DECIMAL(18,2))                          AS accounted_dr,
  CAST(accounted_cr AS DECIMAL(18,2))                          AS accounted_cr,
  CAST(currency_conversion_rate AS DOUBLE)                     AS conversion_rate,
  description                                                  AS line_description,
  NULLIF(reference_1, '')                                      AS reference_1,
  NULLIF(reference_2, '')                                      AS reference_2,
  CAST(effective_date AS DATE)                                 AS accounting_date,
  _source_file
FROM ${schema}.bronze_oracle_gl_je_lines;
