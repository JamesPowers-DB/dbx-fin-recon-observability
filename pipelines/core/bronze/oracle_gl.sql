-- ============================================================================
-- BRONZE: Oracle Fusion General Ledger (journal headers + lines)
-- ============================================================================
-- Source: oracle/gl_je_headers_<YYYY>M<MM>.csv, oracle/gl_je_lines_<YYYY>M<MM>.csv
-- (+ intraday batch files _b<NNN> appended by simulate_activity).
-- One streaming table per file family. No transforms; native Oracle names.
-- Header grain: one row per journal (je_header_id).
-- Line grain:   one row per journal line (je_header_id, je_line_num).
-- ============================================================================

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_gl_je_headers
COMMENT "Oracle Fusion GL journal headers (gl_je_headers), source-shaped. Drives journal-entry testing (M3) and every GL-based control."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files(
  "/Volumes/${catalog}/${schema}/${raw_volume}/oracle/gl_je_headers_*.csv",
  format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_gl_je_lines
COMMENT "Oracle Fusion GL journal lines (gl_je_lines), source-shaped. reference_1 carries the subledger document id (lineage key)."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files(
  "/Volumes/${catalog}/${schema}/${raw_volume}/oracle/gl_je_lines_*.csv",
  format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");
