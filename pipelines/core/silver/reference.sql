-- ============================================================================
-- SILVER: core reference entities (entity, account, code combination, ERP user, worker)
-- ============================================================================
-- Typed and renamed to canonical snake_case. Every row carries
-- source_system / source_table / source_primary_key.
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_entity
COMMENT "Legal entities (one Oracle primary ledger each): functional currency, country, region, house bank."
AS SELECT
  'Oracle Fusion ERP' AS source_system, 'gl_ledgers' AS source_table, ledger_id AS source_primary_key,
  CAST(ledger_id AS BIGINT) AS ledger_id, short_name AS entity_code, legal_entity_name AS entity_name,
  country_code, region, currency_code, bank_name
FROM ${schema}.bronze_oracle_gl_ledgers;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_account
COMMENT "Natural accounts with statement mapping. statement = IS or BS; control_subledger names the subledger that owns a control account (AR, AP, PAYROLL, BANK)."
AS SELECT
  'Oracle Fusion ERP' AS source_system, 'gl_account_hierarchy' AS source_table, flex_value AS source_primary_key,
  flex_value AS account_code, description AS account_name, account_type, fsli_code, fsli_name, statement,
  NULLIF(control_subledger, '') AS control_subledger, is_control_account = 'Y' AS is_control_account, normal_balance
FROM ${schema}.bronze_oracle_gl_account_hierarchy;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_code_combination
COMMENT "Enabled code combinations (entity-segment-account)."
AS SELECT
  'Oracle Fusion ERP' AS source_system, 'gl_code_combinations' AS source_table, code_combination_id AS source_primary_key,
  code_combination_id, segment1 AS entity_code, segment2 AS segment_code, segment3 AS account_code, enabled_flag = 'Y' AS enabled
FROM ${schema}.bronze_oracle_gl_code_combinations;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_erp_user
COMMENT "ERP users. worker_id links to Workday; is_system_account marks interface and batch users."
AS SELECT
  'Oracle Fusion ERP' AS source_system, 'fnd_user' AS source_table, user_id AS source_primary_key,
  CAST(user_id AS BIGINT) AS user_id, user_name, description, NULLIF(employee_id, '') AS worker_id,
  NULLIF(email_address, '') AS email_address, CAST(start_date AS DATE) AS start_date,
  CAST(NULLIF(end_date, '') AS DATE) AS end_date, is_system_account = 'Y' AS is_system_account,
  CAST(last_logon_date AS TIMESTAMP) AS last_logon_at
FROM ${schema}.bronze_oracle_fnd_user;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_worker
COMMENT "Workday workers. termination_date is the HR event the access controls test against. legal_name and email are PII (masked in gold)."
AS SELECT
  'Workday' AS source_system, 'Workers' AS source_table, Worker_ID AS source_primary_key,
  Worker_ID AS worker_id, Legal_Name AS legal_name, Email_Address AS email, Company AS entity_code,
  Cost_Center AS cost_center, Supervisory_Org AS department, Job_Profile AS job_profile,
  CAST(Hire_Date AS DATE) AS hire_date, CAST(Termination_Date AS DATE) AS termination_date, Worker_Status AS worker_status
FROM ${schema}.bronze_workday_workers;
