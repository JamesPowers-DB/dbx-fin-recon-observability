-- ============================================================================
-- SILVER (M1 Cash): bank statements and entries from camt.053
-- ============================================================================
-- Explodes the nested camt.053 structure: one row per daily statement
-- (silver_bank_statement) and one row per entry (silver_bank_entry). Amounts
-- are signed (credit +, debit -) in the account currency. EndToEndId
-- 'NOTPROVIDED' becomes NULL: those entries can only be matched by
-- investigation, never automatically.
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_bank_statement
COMMENT "Daily bank statements (camt.053 Stmt): account, statement date, opening (OPBD) and closing (CLBD) booked balances, entry count."
AS SELECT
  'Bank feed (camt.053)'                                                     AS source_system,
  'camt.053 Stmt'                                                            AS source_table,
  s.Id                                                                       AS source_primary_key,
  s.Id                                                                       AS statement_id,
  s.Acct.Id.Othr.Id                                                          AS bank_account,
  left(s.Acct.Id.Othr.Id, 4)                                                 AS entity_code,
  s.Acct.Ccy                                                                 AS currency_code,
  s.Acct.Svcr.FinInstnId.Nm                                                  AS bank_name,
  to_date(right(s.Id, 8), 'yyyyMMdd')                                        AS statement_date,
  CAST(filter(s.Bal, b -> b.Tp.CdOrPrtry.Cd = 'OPBD')[0].Amt._VALUE AS DECIMAL(18,2))
    * CASE WHEN filter(s.Bal, b -> b.Tp.CdOrPrtry.Cd = 'OPBD')[0].CdtDbtInd = 'DBIT' THEN -1 ELSE 1 END AS opening_balance,
  CAST(filter(s.Bal, b -> b.Tp.CdOrPrtry.Cd = 'CLBD')[0].Amt._VALUE AS DECIMAL(18,2))
    * CASE WHEN filter(s.Bal, b -> b.Tp.CdOrPrtry.Cd = 'CLBD')[0].CdtDbtInd = 'DBIT' THEN -1 ELSE 1 END AS closing_balance,
  COALESCE(size(s.Ntry), 0)                                                  AS entry_count,
  s._source_file,
  s._ingested_at
FROM ${schema}.bronze_bank_camt053_stmt s;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_bank_entry
COMMENT "Bank entries (camt.053 Ntry), one row per AcctSvcrRef. end_to_end_id is the matching key echoed from the payer's reference (AP check number, Salesforce payment reference, payroll run, tax and interest references)."
AS SELECT
  'Bank feed (camt.053)'                                                     AS source_system,
  'camt.053 Ntry'                                                            AS source_table,
  n.AcctSvcrRef                                                              AS source_primary_key,
  n.AcctSvcrRef                                                              AS bank_entry_ref,
  s.Id                                                                       AS statement_id,
  s.Acct.Id.Othr.Id                                                          AS bank_account,
  left(s.Acct.Id.Othr.Id, 4)                                                 AS entity_code,
  s.Acct.Ccy                                                                 AS currency_code,
  CAST(n.BookgDt.Dt AS DATE)                                                 AS booking_date,
  CAST(n.ValDt.Dt AS DATE)                                                   AS value_date,
  CAST(n.Amt._VALUE AS DECIMAL(18,2)) * CASE WHEN n.CdtDbtInd = 'DBIT' THEN -1 ELSE 1 END AS amount,
  NULLIF(n.NtryDtls.TxDtls.Refs.EndToEndId, 'NOTPROVIDED')                  AS end_to_end_id,
  n.NtryDtls.TxDtls.RmtInf.Ustrd                                             AS remittance_info,
  n.BkTxCd.Prtry.Cd                                                          AS bank_tx_code,
  s._source_file
FROM ${schema}.bronze_bank_camt053_stmt s
LATERAL VIEW explode(s.Ntry) e AS n;
