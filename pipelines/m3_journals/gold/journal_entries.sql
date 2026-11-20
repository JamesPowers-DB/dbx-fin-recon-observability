-- ============================================================================
-- GOLD (M3 Journals): journal entry fact with every test flag
-- ============================================================================
-- Grain: journal. Carries each JET test result as a boolean so the metric
-- view (gold_mv_journal_entries) and the app read one table: no joins.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_fact_journal_entries
COMMENT "Journal entry fact (grain: je_header_id) with JET-01..05 flags. Full population: every journal of every period, not a sample."
AS
WITH p AS (
  SELECT
    max(CASE WHEN control_id = 'JET-02' THEN CAST(parameters['threshold_usd'] AS DOUBLE) END) AS jet02_threshold,
    max(CASE WHEN control_id = 'JET-03' THEN CAST(parameters['after_hour'] AS INT) END)      AS after_hour,
    max(CASE WHEN control_id = 'JET-03' THEN CAST(parameters['before_hour'] AS INT) END)     AS before_hour,
    max(CASE WHEN control_id = 'JET-04' THEN CAST(parameters['window_days'] AS INT) END)     AS dup_window,
    max(CASE WHEN control_id = 'JET-05' THEN CAST(parameters['round_min_usd'] AS DOUBLE) END) AS round_min,
    max(CASE WHEN control_id = 'JET-05' THEN CAST(parameters['z_threshold'] AS DOUBLE) END)  AS z_threshold
  FROM ${schema}.silver_control_library
), j AS (
  SELECT f.*, d.is_business_day AS posted_on_business_day, hour(f.posted_at) AS posted_hour
  FROM ${schema}.silver_m3_journal_flags f
  LEFT JOIN ${schema}.gold_dim_business_day d ON d.cal_date = to_date(f.posted_at)
), stats AS (
  SELECT entity_code, debit_accounts, avg(amount_usd) AS mean_usd, stddev_pop(amount_usd) AS sd_usd, count(*) AS n
  FROM j WHERE is_manual GROUP BY entity_code, debit_accounts
), dups AS (
  SELECT DISTINCT b.je_header_id, a.je_header_id AS duplicate_of
  FROM j a JOIN j b
    ON a.is_manual AND b.is_manual AND a.entity_code = b.entity_code AND a.debit_accounts = b.debit_accounts
   AND round(a.amount_entered, 2) = round(b.amount_entered, 2) AND a.je_header_id < b.je_header_id
   AND abs(datediff(b.accounting_date, a.accounting_date)) <= (SELECT dup_window FROM p)
   AND a.je_category NOT IN ('Accrual Reversal', 'Opening Balances') AND b.je_category NOT IN ('Accrual Reversal', 'Opening Balances')
)
SELECT
  j.*,
  e.entity_name, e.region,
  j.is_manual AND NOT j.ctl_jet_01_pass                                                     AS jet01_self_approved,
  j.is_manual AND j.amount_usd > p.jet02_threshold
    AND (j.approval_status_code <> 'A' OR j.approved_at IS NULL OR j.approved_at > j.posted_at) AS jet02_unapproved_over_threshold,
  j.is_manual AND NOT j.created_by_system
    AND (NOT COALESCE(j.posted_on_business_day, true) OR j.posted_hour >= p.after_hour OR j.posted_hour < p.before_hour) AS jet03_off_hours,
  dups.duplicate_of IS NOT NULL                                                             AS jet04_duplicate,
  dups.duplicate_of,
  j.is_manual AND j.amount_entered >= p.round_min AND j.amount_entered % 1000 = 0          AS jet05_round_amount,
  CASE WHEN s.sd_usd > 0 AND s.n >= 5 THEN (j.amount_usd - s.mean_usd) / s.sd_usd END     AS amount_zscore,
  j.is_manual AND ((j.amount_entered >= p.round_min AND j.amount_entered % 1000 = 0)
    OR (s.sd_usd > 0 AND s.n >= 5 AND (j.amount_usd - s.mean_usd) / s.sd_usd > p.z_threshold)) AS jet05_outlier
FROM j
CROSS JOIN p
LEFT JOIN stats s ON s.entity_code = j.entity_code AND s.debit_accounts = j.debit_accounts
LEFT JOIN dups ON dups.je_header_id = j.je_header_id
LEFT JOIN ${schema}.gold_dim_entity e ON e.entity_code = j.entity_code;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_m3_benford_by_user
COMMENT "Benford first-digit analysis of manual journal amounts by preparer (KRI for JET-05). mad = mean absolute deviation from log10(1 + 1/d); above 0.015 is non-conformity (Nigrini)."
AS
WITH d AS (
  SELECT created_by_user_id, created_by_user_name, CAST(left(regexp_replace(CAST(CAST(amount_entered AS BIGINT) AS STRING), '^0+', ''), 1) AS INT) AS digit
  FROM ${schema}.gold_fact_journal_entries WHERE is_manual AND amount_entered >= 10
), c AS (
  SELECT created_by_user_id, max(created_by_user_name) AS user_name, digit, count(*) AS n,
         sum(count(*)) OVER (PARTITION BY created_by_user_id) AS total
  FROM d WHERE digit BETWEEN 1 AND 9 GROUP BY created_by_user_id, digit
)
SELECT created_by_user_id, max(user_name) AS user_name, max(total) AS journals,
       avg(abs(n / total - log10(1 + 1.0 / digit))) AS mad,
       avg(abs(n / total - log10(1 + 1.0 / digit))) > 0.015 AS non_conforming
FROM c GROUP BY created_by_user_id;
