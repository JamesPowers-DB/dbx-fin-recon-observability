-- ============================================================================
-- BRONZE: Bank feed, ISO 20022 camt.053 (Bank-to-Customer Statement), XML
-- ============================================================================
-- Source: bank/camt053_<account>_<YYYYMM>.xml, one file per bank account per
-- month holding one <Stmt> per business day (+ intraday _b<NNN> batches).
-- rowTag = Stmt: one bronze row per daily statement with its nested balances
-- (Bal) and entries (Ntry) kept as arrays; silver explodes them.
-- ============================================================================
CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_bank_camt053_stmt
COMMENT "Bank camt.053 daily statements (XML), source-shaped. Nested Bal and Ntry arrays; silver_bank_entry explodes entries. Drives cash reconciliation (M1)."
TBLPROPERTIES ('source_system' = 'Bank feed (camt.053)')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files(
  "/Volumes/${catalog}/${schema}/${raw_volume}/bank/camt053_*.xml",
  format => "xml", rowTag => "Stmt", rescuedDataColumn => "_rescued_data");
