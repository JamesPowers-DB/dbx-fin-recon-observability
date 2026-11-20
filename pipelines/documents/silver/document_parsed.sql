-- ============================================================================
-- SILVER: document_parsed (ai_parse_document, once per file)
-- ============================================================================
-- Streaming so each PDF is parsed exactly once (ai_parse_document is not
-- deterministic; a materialized view would re-parse on every recompute).
-- ============================================================================
CREATE OR REFRESH STREAMING TABLE ${schema}.silver_document_parsed
COMMENT "PDFs parsed with ai_parse_document (layout-aware). parsed is the VARIANT output; page text is extracted downstream into fields and policy sections."
AS SELECT
  doc_id,
  doc_type,
  path,
  ai_parse_document(content)        AS parsed,
  current_timestamp()               AS parsed_at
FROM STREAM ${schema}.bronze_docs_files;
