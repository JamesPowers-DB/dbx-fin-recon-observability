-- ============================================================================
-- GOLD (M1 Cash): bank reconciliation per account x month (CASH-03 population)
-- ============================================================================
-- Reconciliation waterfall, in the account currency:
--   book balance at period end (GL 10100/10200 incl. opening balance)
--   + timing items (matched pairs with one side after period end)
--   + unmatched items aged beyond the policy window   -> unexplained difference
--   = bank closing balance (CLBD of the last statement in the period)
-- unexplained_amount (aged BANK_ONLY minus aged BOOK_ONLY items dated in the
-- period) is what CASH-03 tests against USD 1.00. Items younger than the aging
-- window are pending, not unexplained.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m1_cash_recon
COMMENT "Bank-to-book reconciliation per bank account and month: book and bank balances, timing items, unexplained difference (account currency and USD), auto-match rate."
AS
WITH params AS (
  SELECT CAST(parameters['aging_bd'] AS INT) AS aging_bd FROM ${schema}.silver_control_library WHERE control_id = 'CASH-03'
), periods AS (
  SELECT period, period_end, status FROM ${schema}.gold_dim_period WHERE status IN ('CLOSED', 'ACTIVE') AND period >= '2025-01'
), accounts AS (
  SELECT DISTINCT bank_account, entity_code FROM ${schema}.silver_m1_statement_continuity
), grid AS (
  SELECT a.bank_account, a.entity_code, p.period, p.period_end, p.status FROM accounts a CROSS JOIN periods p
), book_bal AS (
  SELECT g.bank_account, g.period,
         SUM(CASE WHEN l.accounting_date <= g.period_end THEN l.entered_net ELSE 0 END) AS book_balance
  FROM grid g
  JOIN ${schema}.gold_fact_gl_lines l
    ON concat(l.entity_code, '-', CASE l.account_code WHEN '10100' THEN 'OPS' ELSE 'PAY' END, '-0001') = g.bank_account
   AND l.account_code IN ('10100', '10200')
  GROUP BY g.bank_account, g.period
), bank_bal AS (
  SELECT bank_account, date_format(statement_date, 'yyyy-MM') AS period,
         max_by(closing_balance, statement_date) AS bank_closing_balance, max(statement_date) AS last_statement_date
  FROM ${schema}.silver_bank_statement GROUP BY ALL
), items AS (
  SELECT m.bank_account, m.period, m.match_status, m.amount, m.age_bd, m.bank_date, m.book_date
  FROM ${schema}.gold_m1_cash_match m
), agg AS (
  SELECT
    i.bank_account, i.period,
    COUNT(*)                                                                                   AS items_total,
    SUM(CASE WHEN match_status = 'MATCHED' THEN 1 ELSE 0 END)                                 AS items_matched,
    SUM(CASE WHEN match_status <> 'MATCHED' AND age_bd > p.aging_bd THEN 1 ELSE 0 END)        AS items_aged_unmatched,
    SUM(CASE WHEN match_status <> 'MATCHED' AND age_bd <= p.aging_bd THEN 1 ELSE 0 END)       AS items_pending,
    SUM(CASE WHEN match_status = 'BANK_ONLY' AND age_bd > p.aging_bd THEN amount ELSE 0 END)  AS bank_only_aged_amount,
    SUM(CASE WHEN match_status = 'BOOK_ONLY' AND age_bd > p.aging_bd THEN amount ELSE 0 END)  AS book_only_aged_amount
  FROM items i CROSS JOIN params p GROUP BY i.bank_account, i.period
), timing AS (
  -- matched pairs that straddle a period end: book side in period, bank side later (outstanding),
  -- or bank side in period, book side later (in transit to the book)
  SELECT bank_account, date_format(book_date, 'yyyy-MM') AS period,
         SUM(CASE WHEN date_format(bank_date, 'yyyy-MM') > date_format(book_date, 'yyyy-MM') THEN amount ELSE 0 END) AS outstanding_book_items
  FROM items WHERE match_status = 'MATCHED' GROUP BY ALL
), transit AS (
  SELECT bank_account, date_format(bank_date, 'yyyy-MM') AS period,
         SUM(CASE WHEN date_format(book_date, 'yyyy-MM') > date_format(bank_date, 'yyyy-MM') THEN amount ELSE 0 END) AS bank_items_not_in_book
  FROM items WHERE match_status = 'MATCHED' GROUP BY ALL
)
SELECT
  'CASH'                                                                  AS recon_type,
  g.bank_account                                                          AS recon_object,
  g.entity_code, g.period, g.status AS period_status,
  e.currency_code,
  COALESCE(bb.book_balance, 0)                                            AS book_balance,
  kb.bank_closing_balance                                                 AS external_balance,
  kb.last_statement_date,
  COALESCE(t.outstanding_book_items, 0)                                   AS outstanding_book_items,
  COALESCE(tr.bank_items_not_in_book, 0)                                  AS bank_items_not_in_book,
  COALESCE(a.bank_only_aged_amount, 0) - COALESCE(a.book_only_aged_amount, 0) AS unexplained_amount,
  (COALESCE(a.bank_only_aged_amount, 0) - COALESCE(a.book_only_aged_amount, 0)) * COALESCE(fx.usd_rate, 1.0) AS unexplained_amount_usd,
  COALESCE(a.items_total, 0)                                              AS items_total,
  COALESCE(a.items_matched, 0)                                            AS items_matched,
  COALESCE(a.items_aged_unmatched, 0)                                     AS items_aged_unmatched,
  COALESCE(a.items_pending, 0)                                            AS items_pending,
  COALESCE(fx.usd_rate, 1.0)                                              AS usd_rate
FROM grid g
JOIN ${schema}.gold_dim_entity e ON e.entity_code = g.entity_code
LEFT JOIN book_bal bb ON bb.bank_account = g.bank_account AND bb.period = g.period
LEFT JOIN bank_bal kb ON kb.bank_account = g.bank_account AND kb.period = g.period
LEFT JOIN agg a ON a.bank_account = g.bank_account AND a.period = g.period
LEFT JOIN timing t ON t.bank_account = g.bank_account AND t.period = g.period
LEFT JOIN transit tr ON tr.bank_account = g.bank_account AND tr.period = g.period
LEFT JOIN ${schema}.gold_dim_fx_rate fx ON fx.period = g.period AND fx.currency_code = e.currency_code;
