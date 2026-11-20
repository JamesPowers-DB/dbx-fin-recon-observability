-- ============================================================================
-- GOLD (controls spine): every module's exceptions and results in one contract
-- ============================================================================
-- gold_control_exceptions  union of module exceptions + control metadata + review state
-- gold_control_results     population x exceptions -> PASS | RESOLVED | FAIL | INFO | NO_POPULATION
-- gold_exception_evidence  documents and policy clauses supporting each exception
-- gold_dim_control / gold_dim_risk  for the checklist and the risk register
-- Adding a module = one line in each union below + its files in resources/pipeline.yml.
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dim_control
COMMENT "Control dimension (current library version): binding, lane (management monitoring vs independent assurance), tolerance, owner, policy."
AS SELECT control_id, version, module, module_name, title, objective, risk_ids, key_control, assertions, nature_type, automation,
          line_of_defense, lane, frequency, owner_role, population_dataset, population_unit, population_description, parameters,
          max_exceptions, max_amount_usd, max_exceptions IS NULL AS is_info, executed_by_kind, executed_by_job, executed_by_task,
          executed_by_dataset, executed_by_expectation, exceptions_dataset, test_sql_file, policy_ref, evidence_documents,
          signoff_preparer_role, signoff_reviewer_role, four_eyes, lifecycle_state, effective_from, traditional_sample_size,
          definition_hash, source_file, published_at
   FROM ${schema}.silver_control_library;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dim_risk
COMMENT "Risk register: inherent rating, KRI (metric view, measure, threshold) and linked controls."
AS SELECT * FROM ${schema}.silver_risk_register;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_control_exceptions
COMMENT "All control exceptions across modules (grain: exception). exception_id = sha2(control_id|period|record_key). disposition_status from review state: open | proposed | approved | rejected. is_open = not yet dispositioned."
AS
WITH x AS (
  SELECT 'M1' AS module, * FROM ${schema}.gold_m1_exceptions
  UNION ALL SELECT 'M2', * FROM ${schema}.gold_m2_exceptions
  UNION ALL SELECT 'M3', * FROM ${schema}.gold_m3_exceptions
  UNION ALL SELECT 'M4', * FROM ${schema}.gold_m4_exceptions
  UNION ALL SELECT 'M5', * FROM ${schema}.gold_m5_exceptions
  UNION ALL SELECT 'DQ', * FROM ${schema}.gold_dq_exceptions
), k AS (
  SELECT x.*, sha2(concat_ws('|', x.control_id, x.period, x.record_key), 256) AS exception_id FROM x
)
SELECT
  k.exception_id, k.module, k.control_id, c.title AS control_title, c.key_control, c.lane, c.owner_role, c.risk_ids,
  c.policy_ref, c.max_exceptions IS NULL AS is_info,
  k.entity_code, e.region, k.period, k.record_key, k.record_type, CAST(k.amount_usd AS DOUBLE) AS amount_usd,
  k.detected_value, k.item_date, k.source_table, k.source_primary_key, k.lineage,
  cut.bd_seq - d.bd_seq                                                       AS age_bd,
  COALESCE(rs.disposition_status, 'open')                                     AS disposition_status,
  rs.disposition, rs.proposed_by, rs.approved_by, rs.approved_at, rs.last_comment AS review_comment, rs.last_source AS review_source,
  COALESCE(rs.disposition_status, 'open') <> 'approved'                       AS is_open,
  size(c.evidence_documents) > 0                                              AS requires_evidence,
  EXISTS (SELECT 1 FROM ${schema}.silver_document_fields d
          WHERE (d.doc_type = 'invoices' AND d.invoice_number = k.lineage['invoice_num'])
             OR (d.doc_type = 'bank_advices' AND d.advice_reference = k.lineage['bank_entry_ref'])) AS has_document_evidence,
  CASE WHEN c.max_exceptions IS NULL THEN 'info'
       WHEN c.key_control AND CAST(k.amount_usd AS DOUBLE) >= 250000 THEN 'critical'
       WHEN c.key_control THEN 'high'
       WHEN CAST(k.amount_usd AS DOUBLE) >= 100000 THEN 'high'
       ELSE 'medium' END                                                      AS rule_severity
FROM k
JOIN ${schema}.silver_control_library c ON c.control_id = k.control_id
LEFT JOIN ${schema}.gold_dim_entity e ON e.entity_code = k.entity_code
LEFT JOIN ${schema}.silver_review_status rs ON rs.item_type = 'exception' AND rs.item_key = k.exception_id
LEFT JOIN ${schema}.gold_dim_business_day d ON d.cal_date = k.item_date
LEFT JOIN ${schema}.gold_dim_business_day cut ON cut.cal_date = date_sub(current_date(), 1);

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_control_results
COMMENT "Control results per control x entity x period from this pipeline update. PASS = exceptions within tolerance; RESOLVED = over tolerance but every excess exception dispositioned; FAIL = open exceptions over tolerance; INFO = KRI-style (no tolerance); NO_POPULATION = nothing in scope. PLT-01 is recorded by run_controls.gate_controls."
AS
WITH pop AS (
  SELECT * FROM ${schema}.gold_m1_population
  UNION ALL SELECT * FROM ${schema}.gold_m2_population
  UNION ALL SELECT * FROM ${schema}.gold_m3_population
  UNION ALL SELECT * FROM ${schema}.gold_m4_population
  UNION ALL SELECT * FROM ${schema}.gold_m5_population
  UNION ALL SELECT * FROM ${schema}.gold_dq_population
), popg AS (
  SELECT control_id, entity_code, period, SUM(population_count) AS population_count, SUM(population_amount_usd) AS population_amount_usd
  FROM pop GROUP BY ALL
), exc AS (
  SELECT control_id, entity_code, period, COUNT(*) AS exceptions, SUM(amount_usd) AS exception_amount_usd,
         SUM(CASE WHEN is_open THEN 1 ELSE 0 END) AS open_exceptions,
         SUM(CASE WHEN is_open THEN amount_usd ELSE 0 END) AS open_exception_amount_usd
  FROM ${schema}.gold_control_exceptions GROUP BY ALL
), g AS (
  SELECT COALESCE(p.control_id, x.control_id) AS control_id, COALESCE(p.entity_code, x.entity_code) AS entity_code,
         COALESCE(p.period, x.period) AS period,
         COALESCE(p.population_count, 0) AS population_count, COALESCE(p.population_amount_usd, 0) AS population_amount_usd,
         COALESCE(x.exceptions, 0) AS exceptions, COALESCE(x.exception_amount_usd, 0) AS exception_amount_usd,
         COALESCE(x.open_exceptions, 0) AS open_exceptions, COALESCE(x.open_exception_amount_usd, 0) AS open_exception_amount_usd
  FROM popg p FULL OUTER JOIN exc x ON p.control_id = x.control_id AND p.entity_code = x.entity_code AND p.period = x.period
)
SELECT
  g.*, c.module, c.title AS control_title, c.key_control, c.lane, c.line_of_defense, c.version AS control_version,
  c.traditional_sample_size,
  CASE
    WHEN c.max_exceptions IS NULL THEN CASE WHEN g.population_count = 0 AND g.exceptions = 0 THEN 'NO_POPULATION' ELSE 'INFO' END
    WHEN g.exceptions <= c.max_exceptions AND g.exception_amount_usd <= COALESCE(c.max_amount_usd, 1e18)
      THEN CASE WHEN g.population_count = 0 AND g.exceptions = 0 THEN 'NO_POPULATION' ELSE 'PASS' END
    WHEN g.open_exceptions <= c.max_exceptions AND g.open_exception_amount_usd <= COALESCE(c.max_amount_usd, 1e18) THEN 'RESOLVED'
    ELSE 'FAIL' END AS result
FROM g JOIN ${schema}.silver_control_library c ON c.control_id = g.control_id
WHERE g.period >= '2025-01';

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_exception_evidence
COMMENT "Evidence linked to exceptions: supplier invoices and bank advices (parsed PDFs with extracted fields) and the governing policy clause."
AS
WITH ex AS (SELECT exception_id, control_id, record_key, lineage, policy_ref FROM ${schema}.gold_control_exceptions),
docs AS (SELECT doc_id, doc_type, path, invoice_number, advice_reference, supplier_name, amount, text FROM ${schema}.silver_document_fields)
SELECT ex.exception_id, ex.control_id, 'document' AS evidence_type, d.doc_type AS evidence_subtype, d.doc_id AS evidence_ref,
       d.path AS evidence_path, d.amount AS evidence_amount, d.supplier_name AS evidence_party, substr(d.text, 1, 1200) AS evidence_text
FROM ex JOIN docs d
  ON (d.doc_type = 'invoices' AND d.invoice_number = ex.lineage['invoice_num'])
  OR (d.doc_type = 'bank_advices' AND d.advice_reference = ex.lineage['bank_entry_ref'])
UNION ALL
SELECT ex.exception_id, ex.control_id, 'policy', 'POL-FC-01', p.policy_ref, CAST(NULL AS STRING), CAST(NULL AS DECIMAL(18,2)),
       CAST(NULL AS STRING), p.clause_text
FROM ex JOIN ${schema}.silver_policy_section p ON p.policy_ref = ex.policy_ref;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_recon_summary
COMMENT "All reconciliations in one contract (source of gold_mv_reconciliations): bank-to-book per account x month (M1) and subledger-to-GL per entity x month (M2). difference_usd = unexplained difference (cash) or subledger minus GL."
AS
SELECT recon_type, recon_object, entity_code, period, period_status, currency_code,
       CAST(book_balance AS DOUBLE) AS book_balance, CAST(external_balance AS DOUBLE) AS external_balance,
       CAST(unexplained_amount AS DOUBLE) AS difference, CAST(unexplained_amount_usd AS DOUBLE) AS difference_usd,
       abs(unexplained_amount_usd) <= 1.0 AS in_tolerance, items_total, items_matched, items_aged_unmatched, 'CASH-03' AS control_id
FROM ${schema}.gold_m1_cash_recon
UNION ALL
SELECT recon_type, recon_object, entity_code, period, period_status, currency_code,
       CAST(book_balance AS DOUBLE), CAST(external_balance AS DOUBLE), CAST(difference AS DOUBLE), CAST(difference_usd AS DOUBLE),
       in_tolerance, CAST(NULL AS BIGINT), CAST(NULL AS BIGINT), CAST(NULL AS BIGINT), control_id
FROM ${schema}.gold_m2_subledger_recon;
