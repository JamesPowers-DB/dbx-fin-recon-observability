-- ============================================================================
-- GOLD (M1 Cash): book cash lines and the bank-to-book match
-- ============================================================================
-- Matching rule (POL-FC-01 2.2): bank entry <-> GL cash line, one-to-one, on
-- bank account + EndToEndId + amount. Dates may differ (timing items, e.g.
-- supplier payments clearing after month end, a re-interfaced journal posted
-- next month). Unmatched items are BANK_ONLY or BOOK_ONLY; their age in business
-- days is measured to the data cutoff (yesterday).
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m1_book_cash_lines
COMMENT "GL lines on cash accounts 10100 (operating) and 10200 (payroll) mapped to bank accounts. Opening balances excluded (they are in the bank's opening balance)."
AS SELECT
  concat(entity_code, '-', CASE account_code WHEN '10100' THEN 'OPS' ELSE 'PAY' END, '-0001') AS bank_account,
  entity_code, account_code, accounting_date, period, entered_net AS amount, accounted_net_usd AS amount_usd,
  reference_2 AS end_to_end_id, line_key, je_header_id, je_line_num, je_source, je_category, journal_name
FROM ${schema}.gold_fact_gl_lines
WHERE account_code IN ('10100', '10200') AND je_category <> 'Opening Balances';

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m1_cash_match
COMMENT "Bank-to-book match, one row per bank entry or GL cash line. match_status MATCHED | BANK_ONLY | BOOK_ONLY; age_bd = business days from the item date to the data cutoff; record_key = BANK:<AcctSvcrRef> or GL:<je>:<line>."
AS
WITH bank AS (
  SELECT b.*, row_number() OVER (PARTITION BY bank_account, end_to_end_id, amount ORDER BY booking_date, bank_entry_ref) AS rn
  FROM ${schema}.silver_bank_entry b
), book AS (
  SELECT k.*, row_number() OVER (PARTITION BY bank_account, end_to_end_id, amount ORDER BY accounting_date, line_key) AS rn
  FROM ${schema}.gold_m1_book_cash_lines k
), m AS (
  SELECT
    COALESCE(b.bank_account, k.bank_account)                                   AS bank_account,
    COALESCE(b.entity_code, k.entity_code)                                     AS entity_code,
    COALESCE(b.end_to_end_id, k.end_to_end_id)                                 AS end_to_end_id,
    COALESCE(b.amount, k.amount)                                               AS amount,
    b.bank_entry_ref, b.booking_date AS bank_date, b.remittance_info, b.bank_tx_code, b.currency_code,
    k.line_key, k.je_header_id, k.je_line_num, k.accounting_date AS book_date, k.je_source, k.je_category, k.journal_name,
    CASE WHEN b.bank_entry_ref IS NOT NULL AND k.line_key IS NOT NULL THEN 'MATCHED'
         WHEN b.bank_entry_ref IS NOT NULL THEN 'BANK_ONLY' ELSE 'BOOK_ONLY' END AS match_status
  FROM bank b
  FULL OUTER JOIN book k
    ON b.bank_account = k.bank_account AND b.end_to_end_id = k.end_to_end_id AND b.amount = k.amount AND b.rn = k.rn
)
SELECT
  m.*,
  COALESCE(m.bank_date, m.book_date)                                           AS item_date,
  date_format(COALESCE(m.bank_date, m.book_date), 'yyyy-MM')                   AS period,
  CASE m.match_status WHEN 'BANK_ONLY' THEN concat('BANK:', m.bank_entry_ref)
                      WHEN 'BOOK_ONLY' THEN concat('GL:', m.je_header_id, ':', m.je_line_num)
                      ELSE concat('MATCH:', m.bank_entry_ref) END             AS record_key,
  datediff(m.bank_date, m.book_date)                                           AS timing_days,
  cut.bd_seq - d.bd_seq                                                        AS age_bd
FROM m
JOIN ${schema}.gold_dim_business_day d ON d.cal_date = COALESCE(m.bank_date, m.book_date)
JOIN ${schema}.gold_dim_business_day cut ON cut.cal_date = date_sub(current_date(), 1);
