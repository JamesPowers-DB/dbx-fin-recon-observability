-- ============================================================================
-- SILVER (M4): role grants, requests, and expectation-bound control PAM-04
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_role_grant
COMMENT "ERP role grants (one row per user x role x start date)."
AS SELECT 'Oracle Fusion ERP' AS source_system, 'per_user_roles' AS source_table,
  concat(user_id, '|', role_name, '|', start_date) AS source_primary_key,
  CAST(user_id AS BIGINT) AS user_id, role_name, role_common_name, privileged_flag = 'Y' AS is_privileged,
  CAST(start_date AS DATE) AS start_date, CAST(NULLIF(end_date, '') AS DATE) AS end_date, assigned_by
FROM ${schema}.bronze_oracle_per_user_roles;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_role_request
COMMENT "Role provisioning requests (approved requests authorize privileged grants)."
AS SELECT 'Oracle Fusion ERP' AS source_system, 'per_user_role_requests' AS source_table, request_id AS source_primary_key,
  CAST(request_id AS BIGINT) AS request_id, CAST(user_id AS BIGINT) AS user_id, role_name, requested_by,
  CAST(requested_date AS DATE) AS requested_date, approved_by, CAST(approval_date AS DATE) AS approval_date, status
FROM ${schema}.bronze_oracle_per_user_role_requests;

-- PAM-04: every privileged grant needs an APPROVED request for the same user and
-- role, approved on or before the grant start. WARN: failures stay in the
-- population and become exceptions in gold.
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_m4_grant_checks (
  CONSTRAINT ctl_pam_04 EXPECT (ctl_pam_04_pass)
)
COMMENT "PAM-04 population: privileged role grants. ctl_pam_04_pass = an approved provisioning request precedes the grant."
AS
SELECT g.user_id, g.role_name, g.start_date, g.end_date, g.assigned_by,
       date_format(g.start_date, 'yyyy-MM') AS period,
       u.worker_id, w.entity_code,
       max(r.request_id) AS request_id,
       count(r.request_id) > 0 AS ctl_pam_04_pass
FROM ${schema}.silver_role_grant g
LEFT JOIN ${schema}.silver_role_request r
  ON r.user_id = g.user_id AND r.role_name = g.role_name AND r.status = 'APPROVED' AND r.approval_date <= g.start_date
LEFT JOIN ${schema}.silver_erp_user u ON u.user_id = g.user_id
LEFT JOIN ${schema}.silver_worker w ON w.worker_id = u.worker_id
WHERE g.is_privileged
GROUP BY g.user_id, g.role_name, g.start_date, g.end_date, g.assigned_by, u.worker_id, w.entity_code;
