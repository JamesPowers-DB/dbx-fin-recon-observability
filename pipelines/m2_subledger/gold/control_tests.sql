-- ============================================================================
-- GOLD (M2): control populations and exceptions (SLR-01 .. SLR-05)
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m2_population
COMMENT "Populations tested by the subledger controls, per control x entity x month."
AS
SELECT control_id, entity_code, period, COUNT(*) AS population_count, SUM(abs(external_balance) * usd_rate) AS population_amount_usd
FROM ${schema}.gold_m2_subledger_recon GROUP BY ALL
UNION ALL
SELECT 'SLR-04', entity_code, period, COUNT(DISTINCT je_header_id), SUM(accounted_dr)
FROM ${schema}.gold_fact_gl_lines WHERE is_manual AND je_category <> 'Opening Balances' GROUP BY ALL
UNION ALL
SELECT 'SLR-05', i.entity_code, date_format(i.gl_date, 'yyyy-MM'), COUNT(*), SUM(i.invoice_amount * COALESCE(fx.usd_rate, 1.0))
FROM ${schema}.silver_ap_invoice i
LEFT JOIN ${schema}.gold_dim_fx_rate fx ON fx.period = date_format(i.gl_date, 'yyyy-MM') AND fx.currency_code = i.currency_code
CROSS JOIN (SELECT CAST(parameters['threshold_usd'] AS DOUBLE) AS thr FROM ${schema}.silver_control_library WHERE control_id = 'SLR-05') p
WHERE i.invoice_amount * COALESCE(fx.usd_rate, 1.0) >= p.thr
  AND date_format(i.gl_date, 'yyyy-MM') >= date_format(add_months(date_sub(current_date(), 1), -1), 'yyyy-MM')
GROUP BY ALL;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m2_exceptions
COMMENT "Subledger control exceptions: tie-outs out of tolerance (SLR-01/02/03), manual journals to control accounts (SLR-04), large AP invoices without matching supplier evidence (SLR-05)."
AS
WITH docs AS (
  SELECT invoice_number, supplier_name, amount AS doc_amount, doc_id FROM ${schema}.silver_document_fields WHERE doc_type = 'invoices'
), big AS (
  SELECT i.*, i.invoice_amount * COALESCE(fx.usd_rate, 1.0) AS amount_usd, date_format(i.gl_date, 'yyyy-MM') AS period
  FROM ${schema}.silver_ap_invoice i
  LEFT JOIN ${schema}.gold_dim_fx_rate fx ON fx.period = date_format(i.gl_date, 'yyyy-MM') AND fx.currency_code = i.currency_code
  CROSS JOIN (SELECT CAST(parameters['threshold_usd'] AS DOUBLE) AS thr FROM ${schema}.silver_control_library WHERE control_id = 'SLR-05') p
  WHERE i.invoice_amount * COALESCE(fx.usd_rate, 1.0) >= p.thr
    AND date_format(i.gl_date, 'yyyy-MM') >= date_format(add_months(date_sub(current_date(), 1), -1), 'yyyy-MM')
)
SELECT r.control_id, r.entity_code, r.period, concat(r.entity_code, '|', r.period) AS record_key, 'subledger_tieout' AS record_type,
       abs(r.difference_usd) AS amount_usd,
       concat(r.recon_type, ' subledger ', format_number(r.external_balance, 2), ' vs GL ', format_number(r.book_balance, 2), ' ', r.currency_code,
              ' (difference ', format_number(r.difference, 2), ', tolerance ', format_number(r.tolerance_amount, 2), ')') AS detected_value,
       last_day(to_date(concat(r.period, '-01'))) AS item_date, 'gold_m2_subledger_recon' AS source_table,
       concat(r.recon_type, '|', r.entity_code, '|', r.period) AS source_primary_key,
       map('recon_type', r.recon_type, 'subledger_balance', CAST(r.external_balance AS STRING), 'gl_balance', CAST(r.book_balance AS STRING)) AS lineage
FROM ${schema}.gold_m2_subledger_recon r WHERE NOT r.in_tolerance
UNION ALL
SELECT 'SLR-04', l.entity_code, l.period, CAST(l.je_header_id AS STRING), 'journal', SUM(l.accounted_dr + l.accounted_cr) / 2,
       concat('Manual journal ', l.je_header_id, ' (', max(l.journal_name), ') posts to control account ', max(l.account_code)),
       max(l.accounting_date), 'gold_fact_gl_lines', CAST(l.je_header_id AS STRING),
       map('je_header_id', CAST(l.je_header_id AS STRING), 'control_account', max(l.account_code), 'created_by', CAST(max(l.created_by_user_id) AS STRING))
FROM ${schema}.gold_fact_gl_lines l
WHERE l.is_manual AND l.je_category <> 'Opening Balances' AND l.control_subledger IN ('AR', 'AP', 'PAYROLL')
GROUP BY l.entity_code, l.period, l.je_header_id
UNION ALL
SELECT 'SLR-05', b.entity_code, b.period, CAST(b.invoice_id AS STRING), 'ap_invoice', b.amount_usd,
       CASE WHEN d.invoice_number IS NULL THEN concat('No supplier invoice document for ', b.invoice_num)
            WHEN abs(d.doc_amount - b.invoice_amount) > 0.01 THEN concat('Document amount ', format_number(d.doc_amount, 2), ' disagrees with AP ', format_number(b.invoice_amount, 2))
            ELSE concat('Document supplier "', d.supplier_name, '" is not the AP supplier "', b.vendor_name, '"') END,
       b.gl_date, 'silver_ap_invoice', CAST(b.invoice_id AS STRING),
       map('invoice_id', CAST(b.invoice_id AS STRING), 'invoice_num', b.invoice_num, 'document', COALESCE(d.doc_id, ''))
FROM big b LEFT JOIN docs d ON d.invoice_number = b.invoice_num
WHERE d.invoice_number IS NULL OR abs(d.doc_amount - b.invoice_amount) > 0.01
   OR lower(trim(d.supplier_name)) <> lower(trim(b.vendor_name));
