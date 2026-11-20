-- ============================================================================
-- BRONZE (M4): Oracle security (role grants, provisioning requests)
-- ============================================================================
CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_per_user_roles
COMMENT "Oracle PER_USER_ROLES: role grant history per ERP user (start and end dates, privileged flag)."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/",
  pathGlobFilter => "per_user_roles.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");

CREATE OR REFRESH STREAMING TABLE ${schema}.bronze_oracle_per_user_role_requests
COMMENT "Oracle role provisioning requests: requester, approver, status."
TBLPROPERTIES ('source_system' = 'Oracle Fusion ERP')
AS SELECT *, _metadata.file_path AS _source_file, _metadata.file_modification_time AS _ingested_at
FROM STREAM read_files("/Volumes/${catalog}/${schema}/${raw_volume}/oracle/",
  pathGlobFilter => "per_user_role_requests.csv", format => "csv", header => true, inferColumnTypes => false, rescuedDataColumn => "_rescued_data");
