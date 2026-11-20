-- ============================================================================
-- GOLD (M4): user access fact (grain: ERP user x month)
-- ============================================================================
-- Joins Oracle security to Workday HR: who could act in the ERP each month,
-- what they could do, whether they had left, and what they posted. Identity
-- PII (legal_name, email) is masked by the UC column mask mask_pii (created by
-- publish_controls); only members of fin_recon_pii_readers see clear values.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_fact_user_access (
  user_id BIGINT,
  user_name STRING,
  worker_id STRING,
  legal_name STRING MASK ${catalog}.${schema}.mask_pii,
  email STRING MASK ${catalog}.${schema}.mask_pii,
  entity_code STRING,
  job_profile STRING,
  period STRING,
  roles ARRAY<STRING>,
  privileged_roles ARRAY<STRING>,
  sod_conflicts ARRAY<STRING>,
  has_sod_conflict BOOLEAN,
  termination_date DATE,
  access_end_date DATE,
  terminated_by_period_end BOOLEAN,
  terminated_with_access BOOLEAN,
  removal_lag_bd INT,
  post_termination_journals BIGINT,
  post_termination_amount_usd DECIMAL(28,2)
)
COMMENT "ERP access per user and month for non-system users: roles held, SoD conflicts, Workday termination vs Oracle end date, post-termination postings. legal_name and email are masked PII."
AS
WITH params AS (
  SELECT split(parameters['conflicts'], ';') AS pairs FROM ${schema}.silver_control_library WHERE control_id = 'PAM-01'
), periods AS (
  SELECT period, period_start, period_end, data_cutoff FROM ${schema}.gold_dim_period WHERE status IN ('CLOSED', 'ACTIVE') AND period >= '2025-01'
), users AS (
  SELECT u.*, w.legal_name, w.email, w.entity_code, w.job_profile, w.termination_date
  FROM ${schema}.silver_erp_user u LEFT JOIN ${schema}.silver_worker w ON w.worker_id = u.worker_id
  WHERE NOT u.is_system_account
), up AS (
  SELECT u.*, p.period, p.period_start, p.period_end, p.data_cutoff
  FROM users u JOIN periods p
    ON u.start_date <= p.period_end AND (u.end_date IS NULL OR u.end_date >= p.period_start)
), grants AS (
  SELECT up.user_id, up.period, g.role_name, g.is_privileged, greatest(g.start_date, up.period_start) AS gs,
         least(COALESCE(g.end_date, up.period_end), up.period_end) AS ge
  FROM up JOIN ${schema}.silver_role_grant g
    ON g.user_id = up.user_id AND g.start_date <= up.period_end AND (g.end_date IS NULL OR g.end_date >= up.period_start)
), conflicts AS (
  SELECT a.user_id, a.period, concat(a.role_name, '+', b.role_name) AS pair
  FROM grants a JOIN grants b ON a.user_id = b.user_id AND a.period = b.period AND a.role_name <> b.role_name
   AND greatest(a.gs, b.gs) <= least(a.ge, b.ge)
  CROSS JOIN params p
  WHERE array_contains(p.pairs, concat(a.role_name, '+', b.role_name))
), posts AS (
  SELECT j.created_by_user_id AS user_id, j.period, count(*) AS n, SUM(j.amount_usd) AS amt
  FROM ${schema}.gold_fact_journals j
  JOIN users u ON u.user_id = j.created_by_user_id
  WHERE u.termination_date IS NOT NULL AND j.accounting_date > u.termination_date
  GROUP BY ALL
), lag AS (
  SELECT u.user_id,
         CASE WHEN u.termination_date IS NULL THEN NULL
              ELSE de.bd_seq - dt.bd_seq END AS removal_lag_bd
  FROM users u
  LEFT JOIN ${schema}.gold_dim_business_day dt ON dt.cal_date = u.termination_date
  LEFT JOIN ${schema}.gold_dim_business_day de ON de.cal_date = COALESCE(u.end_date, date_sub(current_date(), 1))
)
SELECT
  up.user_id, up.user_name, up.worker_id, up.legal_name, up.email, up.entity_code, up.job_profile, up.period,
  array_sort(collect_set(g.role_name))                                            AS roles,
  array_sort(collect_set(CASE WHEN g.is_privileged THEN g.role_name END))         AS privileged_roles,
  array_sort(collect_set(c.pair))                                                 AS sod_conflicts,
  size(collect_set(c.pair)) > 0                                                   AS has_sod_conflict,
  max(up.termination_date)                                                        AS termination_date,
  max(up.end_date)                                                                AS access_end_date,
  max(up.termination_date) <= max(up.period_end)                                  AS terminated_by_period_end,
  max(up.termination_date) <= max(up.period_end) AND (max(up.end_date) IS NULL OR max(up.end_date) > max(up.termination_date)) AS terminated_with_access,
  CAST(max(lg.removal_lag_bd) AS INT)                                             AS removal_lag_bd,
  CAST(COALESCE(max(ps.n), 0) AS BIGINT)                                          AS post_termination_journals,
  CAST(COALESCE(max(ps.amt), 0) AS DECIMAL(28,2))                                AS post_termination_amount_usd
FROM up
LEFT JOIN grants g ON g.user_id = up.user_id AND g.period = up.period
LEFT JOIN conflicts c ON c.user_id = up.user_id AND c.period = up.period
LEFT JOIN posts ps ON ps.user_id = up.user_id AND ps.period = up.period
LEFT JOIN lag lg ON lg.user_id = up.user_id
GROUP BY up.user_id, up.user_name, up.worker_id, up.legal_name, up.email, up.entity_code, up.job_profile, up.period;
