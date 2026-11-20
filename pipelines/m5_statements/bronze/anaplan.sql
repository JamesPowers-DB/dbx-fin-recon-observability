-- ============================================================================
-- BRONZE (M5): Anaplan plan export (budget, forecast) and MTD phasing profile
-- ============================================================================
CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_anaplan_plan
COMMENT "Anaplan export: Version (Budget FY25, Budget FY26, Forecast 3+9 FY26) x Time x E1_Entity x G1_Account, USD."
TBLPROPERTIES ('source_system' = 'Anaplan')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/anaplan/plan_[BF]*.csv",
  format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_anaplan_phasing
COMMENT "Anaplan month-to-date phasing profile per account (linear, payroll, period_end, step_bd5)."
TBLPROPERTIES ('source_system' = 'Anaplan')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/anaplan/",
  pathGlobFilter => "plan_phasing.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");
