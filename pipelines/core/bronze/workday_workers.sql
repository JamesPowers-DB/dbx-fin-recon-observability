-- ============================================================================
-- BRONZE: Workday workers (RaaS export, Parquet)
-- ============================================================================
CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_workday_workers
COMMENT "Workday Workers report: hire and termination dates drive the access controls (M4). Legal_Name and Email_Address are PII."
TBLPROPERTIES ('source_system' = 'Workday')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/workday/",
  pathGlobFilter => "workers.parquet", format => "parquet", rescuedDataColumn => "_rescued_data");
