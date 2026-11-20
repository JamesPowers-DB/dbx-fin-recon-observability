-- ============================================================================
-- BRONZE: evidence documents (PDF), binary
-- ============================================================================
-- Source: docs/invoices/*.pdf, docs/bank_advices/*.pdf, docs/policies/*.pdf.
-- One row per file. The binary content is parsed once in silver.
-- ============================================================================
CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_docs_files
COMMENT "Evidence and policy PDFs as binary files. doc_type comes from the folder (invoices, bank_advices, policies)."
TBLPROPERTIES ('source_system' = 'Evidence documents')
AS SELECT
  path,
  regexp_extract(path, '/docs/([^/]+)/', 1)              AS doc_type,
  regexp_extract(path, '/([^/]+)\\.pdf$', 1)             AS doc_id,
  length,
  modificationTime                                        AS modified_at,
  content,
  _metadata.file_modification_time                        AS _ingested_at
FROM STREAM read_files(
  "/Volumes/${catalog}/${schema}/${raw_volume}/docs/",
  format => "binaryFile", pathGlobFilter => "*.pdf", recursiveFileLookup => true);
