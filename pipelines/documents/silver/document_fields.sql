-- ============================================================================
-- SILVER (documents): extracted fields and policy clauses
-- ============================================================================
-- silver_document_fields: once per PDF (streaming), the parsed text and AI
-- extraction (ai_extract) of the fields the evidence controls need. A
-- deterministic regex extraction is kept alongside as a cross-check
-- (extraction_agrees); controls use the AI value and fall back to the regex.
-- silver_policy_section: POL-FC-01 split into numbered clauses, mapped to
-- control families, for the triage prompt and the investigator agent.
-- ============================================================================

CREATE OR REFRESH STREAMING TABLE ${schema}.silver_document_fields
COMMENT "Evidence documents with extracted fields. invoices: invoice_number, supplier_name, invoice_date, amount, currency. bank_advices: advice_reference, amount, booking_date. extraction_method = ai_extract (regex cross-check in regex_amount)."
AS
WITH t AS (
  SELECT doc_id, doc_type, path, parsed_at,
         concat_ws('\n', transform(CAST(parsed:document.elements AS ARRAY<VARIANT>), e -> e:content::string)) AS text
  FROM STREAM(${schema}.silver_document_parsed)
), x AS (
  SELECT t.*,
    CASE WHEN doc_type = 'invoices' THEN ai_extract(text, array('invoice_number', 'supplier_name', 'invoice_date', 'amount_due', 'currency')) END AS inv,
    CASE WHEN doc_type = 'bank_advices' THEN ai_extract(text, array('advice_reference', 'amount', 'booking_date', 'account')) END AS adv
  FROM t
)
SELECT
  doc_id, doc_type, path, text, parsed_at,
  COALESCE(inv.invoice_number, regexp_extract(text, 'Invoice number: ([^\\n]+)', 1))           AS invoice_number,
  COALESCE(inv.supplier_name, split(text, '\n')[1])                                          AS supplier_name,
  try_cast(COALESCE(inv.invoice_date, regexp_extract(text, 'Invoice date: ([0-9-]+)', 1)) AS DATE) AS invoice_date,
  COALESCE(inv.currency, regexp_extract(text, 'Currency: ([A-Z]{3})', 1))                      AS currency,
  COALESCE(adv.advice_reference, regexp_extract(text, 'Advice reference: ([^\\n]+)', 1))     AS advice_reference,
  try_cast(regexp_replace(regexp_extract(COALESCE(inv.amount_due, adv.amount, ''), '([0-9][0-9,]*\\.?[0-9]*)', 1), ',', '') AS DECIMAL(18,2)) AS ai_amount,
  try_cast(regexp_replace(regexp_extract(text, '(?:Amount due|Amount): [A-Z]{3} ([0-9,]+\\.[0-9]{2})', 1), ',', '') AS DECIMAL(18,2)) AS regex_amount,
  COALESCE(
    try_cast(regexp_replace(regexp_extract(COALESCE(inv.amount_due, adv.amount, ''), '([0-9][0-9,]*\\.?[0-9]*)', 1), ',', '') AS DECIMAL(18,2)),
    try_cast(regexp_replace(regexp_extract(text, '(?:Amount due|Amount): [A-Z]{3} ([0-9,]+\\.[0-9]{2})', 1), ',', '') AS DECIMAL(18,2))) AS amount,
  'ai_extract'                                                                                AS extraction_method
FROM x;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_policy_section
COMMENT "POL-FC-01 Financial Close and Reconciliation Policy, one row per numbered clause (e.g. 4.2), mapped to the control family it governs."
AS
WITH clauses AS (
  SELECT doc_id, explode(regexp_extract_all(regexp_replace(text, '\\s+', ' '), '([0-9]\\.[0-9] .*?)(?= [0-9]\\.[0-9] |$)', 1)) AS clause
  FROM ${schema}.silver_document_fields WHERE doc_type = 'policies'
)
SELECT
  doc_id                                                                    AS policy_id,
  concat(doc_id, ' ', split(clause, ' ')[0])                                AS policy_ref,
  split(clause, ' ')[0]                                                     AS clause_number,
  CASE split(split(clause, ' ')[0], '\\.')[0]
    WHEN '1' THEN 'GENERAL' WHEN '2' THEN 'CASH' WHEN '3' THEN 'SLR' WHEN '4' THEN 'JET' WHEN '5' THEN 'PAM'
    WHEN '6' THEN 'FSC_FPA' WHEN '7' THEN 'DQ' ELSE 'CLOSE' END             AS control_family,
  trim(clause)                                                              AS clause_text
FROM clauses;
