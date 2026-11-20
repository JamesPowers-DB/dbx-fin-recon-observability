-- ============================================================================
-- GOLD: entity and account dims, GL line fact (the core fact every module reads)
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dim_entity
COMMENT "Legal entities of Corvane Technologies (fictional): functional currency, region, house bank."
AS SELECT entity_code, entity_name, ledger_id, country_code, region, currency_code, bank_name FROM ${schema}.silver_entity;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dim_account
COMMENT "Natural accounts with statement line (FSLI) mapping. presentation_sign turns ledger debits/credits into statement presentation (revenue, liabilities and equity positive)."
AS SELECT
  account_code, account_name, account_type, fsli_code, fsli_name, statement, control_subledger, is_control_account,
  CASE WHEN account_type IN ('R', 'L', 'E') THEN -1 ELSE 1 END AS presentation_sign
FROM ${schema}.silver_account;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_fact_gl_lines
COMMENT "GL journal line fact (grain: je_header_id x je_line_num) with journal, entity, account and user attributes. accounted_* are USD (one rate per journal); entered_* are functional currency. is_mapped_account = false for lines whose account is not in the chart of accounts (DQ-03)."
AS
SELECT
  l.je_header_id,
  l.je_line_num,
  concat(l.je_header_id, ':', l.je_line_num)              AS line_key,
  l.entity_code,
  e.entity_name,
  e.region,
  e.currency_code,
  l.segment_code,
  l.account_code,
  a.account_name,
  a.account_type,
  a.fsli_code,
  a.fsli_name,
  a.statement,
  a.control_subledger,
  a.account_code IS NOT NULL                              AS is_mapped_account,
  j.je_source,
  j.je_category,
  j.journal_name,
  j.is_manual,
  COALESCE(l.accounting_date, j.accounting_date)          AS accounting_date,
  date_format(COALESCE(l.accounting_date, j.accounting_date), 'yyyy-MM') AS period,
  j.posted_at,
  j.created_at,
  j.created_by_user_id,
  u.user_name                                             AS created_by_user_name,
  COALESCE(u.is_system_account, false)                    AS created_by_system,
  j.approved_by_user_id,
  j.approval_status_code,
  j.approved_at,
  l.entered_dr,
  l.entered_cr,
  l.entered_dr - l.entered_cr                             AS entered_net,
  l.accounted_dr,
  l.accounted_cr,
  l.accounted_dr - l.accounted_cr                         AS accounted_net_usd,
  l.conversion_rate,
  l.reference_1,
  l.reference_2,
  l.line_description
FROM ${schema}.silver_gl_line l
JOIN ${schema}.silver_gl_journal j USING (je_header_id)
LEFT JOIN ${schema}.silver_entity e ON l.entity_code = e.entity_code
LEFT JOIN ${schema}.silver_account a ON l.account_code = a.account_code
LEFT JOIN ${schema}.silver_erp_user u ON j.created_by_user_id = u.user_id;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dim_fx_rate
COMMENT "Monthly average USD rate per functional currency, as used by the GL (one rate per journal and month)."
AS SELECT period, currency_code, max(conversion_rate) AS usd_rate
FROM ${schema}.gold_fact_gl_lines
WHERE conversion_rate IS NOT NULL
GROUP BY period, currency_code;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_fact_journals
COMMENT "GL journal fact (grain: je_header_id): source, preparer and approver, timestamps, total (amount_usd = sum of accounted debits; amount_entered in functional currency), debit-account signature. Core: read by M3 (journal testing) and M4 (access)."
AS
SELECT
  je_header_id,
  max(entity_code)                                                   AS entity_code,
  max(period)                                                        AS period,
  max(accounting_date)                                               AS accounting_date,
  max(je_source)                                                     AS je_source,
  max(je_category)                                                   AS je_category,
  max(journal_name)                                                  AS journal_name,
  bool_or(is_manual)                                                 AS is_manual,
  max(created_by_user_id)                                            AS created_by_user_id,
  max(created_by_user_name)                                          AS created_by_user_name,
  bool_or(created_by_system)                                         AS created_by_system,
  max(approved_by_user_id)                                           AS approved_by_user_id,
  max(approval_status_code)                                          AS approval_status_code,
  max(created_at)                                                    AS created_at,
  max(approved_at)                                                   AS approved_at,
  max(posted_at)                                                     AS posted_at,
  SUM(accounted_dr)                                                  AS amount_usd,
  SUM(entered_dr)                                                    AS amount_entered,
  array_join(array_sort(collect_set(CASE WHEN entered_dr > 0 THEN account_code END)), ',') AS debit_accounts,
  count(*)                                                           AS line_count
FROM ${schema}.gold_fact_gl_lines
GROUP BY je_header_id;
