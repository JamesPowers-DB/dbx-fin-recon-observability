-- ============================================================================
-- BRONZE: Oracle Fusion masters (ledgers, chart of accounts, users)
-- ============================================================================
-- Stable master files, overwritten on regeneration (setup and refresh run a
-- full refresh). Native Oracle names, all columns STRING; silver casts.
-- ============================================================================

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_gl_ledgers
COMMENT "Oracle GL_LEDGERS: one primary ledger per legal entity (currency, country, region)."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/",
  pathGlobFilter => "gl_ledgers.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_gl_account_hierarchy
COMMENT "Oracle natural-account value set (FND_FLEX_VALUES) with the financial statement line (FSLI) mapping and control-account flags."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/",
  pathGlobFilter => "gl_account_hierarchy.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_gl_code_combinations
COMMENT "Oracle GL_CODE_COMBINATIONS: entity-segment-account combinations enabled for posting."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/",
  pathGlobFilter => "gl_code_combinations.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_fnd_user
COMMENT "Oracle FND_USER: ERP users. employee_id links to the Workday Worker_ID; system accounts run interfaces."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/",
  pathGlobFilter => "fnd_user.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");
