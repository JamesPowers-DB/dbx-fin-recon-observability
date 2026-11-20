-- ============================================================================
-- GOLD (M4): control populations and exceptions (PAM-01 .. PAM-04)
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m4_population
COMMENT "Populations tested by the access controls, per control x entity x month."
AS
SELECT 'PAM-01' AS control_id, entity_code, period, COUNT(*) AS population_count, CAST(0 AS DOUBLE) AS population_amount_usd
FROM ${schema}.gold_fact_user_access GROUP BY ALL
UNION ALL
SELECT 'PAM-02', entity_code, date_format(termination_date, 'yyyy-MM'), COUNT(DISTINCT user_id), CAST(0 AS DOUBLE)
FROM ${schema}.gold_fact_user_access WHERE termination_date IS NOT NULL GROUP BY ALL
UNION ALL
SELECT 'PAM-03', j.entity_code, j.period, COUNT(*), SUM(j.amount_usd)
FROM ${schema}.gold_fact_journals j WHERE j.is_manual AND NOT j.created_by_system GROUP BY ALL
UNION ALL
SELECT 'PAM-04', entity_code, period, COUNT(*), CAST(0 AS DOUBLE) FROM ${schema}.silver_m4_grant_checks GROUP BY ALL;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m4_exceptions
COMMENT "Access control exceptions: SoD conflicts (PAM-01), late or missing access removal (PAM-02), postings after termination (PAM-03), privileged grants without an approved request (PAM-04)."
AS
WITH p AS (SELECT CAST(parameters['removal_bd'] AS INT) AS removal_bd FROM ${schema}.silver_control_library WHERE control_id = 'PAM-02')
SELECT 'PAM-01' AS control_id, a.entity_code, a.period, concat(a.user_id, '|', pair) AS record_key, 'user' AS record_type,
       CAST(0 AS DOUBLE) AS amount_usd, concat('User ', a.user_name, ' holds conflicting roles ', replace(pair, '+', ' + ')) AS detected_value,
       last_day(to_date(concat(a.period, '-01'))) AS item_date, 'gold_fact_user_access' AS source_table,
       concat(a.user_id, '|', a.period) AS source_primary_key,
       map('user_id', CAST(a.user_id AS STRING), 'user_name', a.user_name, 'conflict', pair) AS lineage
FROM ${schema}.gold_fact_user_access a LATERAL VIEW explode(a.sod_conflicts) x AS pair
UNION ALL
SELECT 'PAM-02', a.entity_code, date_format(a.termination_date, 'yyyy-MM'), CAST(a.user_id AS STRING), 'user', CAST(0 AS DOUBLE),
       concat('User ', a.user_name, ' terminated ', a.termination_date, '; ERP access ',
              CASE WHEN a.access_end_date IS NULL THEN 'still active' ELSE concat('removed ', a.access_end_date) END,
              ' (', a.removal_lag_bd, ' business days)'),
       a.termination_date, 'gold_fact_user_access', CAST(a.user_id AS STRING),
       map('user_id', CAST(a.user_id AS STRING), 'user_name', a.user_name, 'worker_id', COALESCE(a.worker_id, ''))
FROM (SELECT DISTINCT user_id, user_name, worker_id, entity_code, termination_date, access_end_date, removal_lag_bd
      FROM ${schema}.gold_fact_user_access WHERE termination_date IS NOT NULL) a
CROSS JOIN p WHERE a.removal_lag_bd > p.removal_bd
UNION ALL
SELECT 'PAM-03', j.entity_code, j.period, CAST(j.je_header_id AS STRING), 'journal', CAST(j.amount_usd AS DOUBLE),
       concat('Journal ', j.je_header_id, ' created by ', j.created_by_user_name, ' on ', j.accounting_date, ', after termination on ', w.termination_date),
       j.accounting_date, 'gold_fact_journals', CAST(j.je_header_id AS STRING),
       map('je_header_id', CAST(j.je_header_id AS STRING), 'user_id', CAST(j.created_by_user_id AS STRING), 'termination_date', CAST(w.termination_date AS STRING))
FROM ${schema}.gold_fact_journals j
JOIN ${schema}.silver_erp_user u ON u.user_id = j.created_by_user_id
JOIN ${schema}.silver_worker w ON w.worker_id = u.worker_id
WHERE w.termination_date IS NOT NULL AND j.accounting_date > w.termination_date
UNION ALL
SELECT 'PAM-04', g.entity_code, g.period, concat(g.user_id, '|', g.role_name, '|', g.start_date), 'role_grant', CAST(0 AS DOUBLE),
       concat('Privileged role ', g.role_name, ' assigned to user ', g.user_id, ' on ', g.start_date, ' (', g.assigned_by, ') without an approved request'),
       g.start_date, 'silver_m4_grant_checks', concat(g.user_id, '|', g.role_name, '|', g.start_date),
       map('user_id', CAST(g.user_id AS STRING), 'role', g.role_name, 'assigned_by', g.assigned_by)
FROM ${schema}.silver_m4_grant_checks g WHERE NOT g.ctl_pam_04_pass;
