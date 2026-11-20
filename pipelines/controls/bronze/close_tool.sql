-- ============================================================================
-- BRONZE: prior close-management tool export (closed periods only)
-- ============================================================================
CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_close_tool_task_history
COMMENT "Close task history migrated from the prior close tool: completion and sign-off per closed period and task."
TBLPROPERTIES ('source_system' = 'Prior close tool')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/close_tool/",
  pathGlobFilter => "close_task_history.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_close_tool_review_history
COMMENT "Exception dispositions migrated from the prior close tool (closed periods)."
TBLPROPERTIES ('source_system' = 'Prior close tool')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/close_tool/",
  pathGlobFilter => "review_history.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_close_tool_variance_commentary
COMMENT "Flux explanations and acknowledgements migrated from the prior close tool (closed periods)."
TBLPROPERTIES ('source_system' = 'Prior close tool')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/close_tool/",
  pathGlobFilter => "variance_commentary_history.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");
