-- ============================================================================
-- GOLD: business-day calendar and close periods
-- ============================================================================
-- gold_dim_business_day: one row per date. bd_seq counts business days up to
-- and including the date, so the close-day offset of date d against period p
-- is bd_seq(d) - bd_seq_at_period_end(p): T+1 is the first business day after
-- month end; 0 is the last business day of the month.
-- gold_dim_period: one row per monthly close period with the data cutoff
-- (yesterday) and the month-to-date phasing inputs used by the live flux
-- review (business days elapsed, payroll runs elapsed, 5th business day).
-- Office closures: Jan 1, Dec 25, Dec 26 (same as the generators).
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dim_business_day
COMMENT "Calendar dim with business days (weekdays except Jan 1, Dec 25, Dec 26) and bd_seq, the running business-day count used for close-day (T+n) arithmetic."
AS
WITH d AS (
  SELECT explode(sequence(DATE'2024-12-01', DATE'2027-02-28', INTERVAL 1 DAY)) AS cal_date
), flagged AS (
  SELECT
    cal_date,
    date_format(cal_date, 'yyyy-MM')                                        AS period,
    dayofweek(cal_date) IN (1, 7)                                           AS is_weekend,
    dayofweek(cal_date) NOT IN (1, 7)
      AND NOT ((month(cal_date) = 1 AND day(cal_date) = 1)
            OR (month(cal_date) = 12 AND day(cal_date) IN (25, 26)))        AS is_business_day,
    date_format(cal_date, 'EEE')                                            AS day_name
  FROM d
)
SELECT *, SUM(CAST(is_business_day AS INT)) OVER (ORDER BY cal_date) AS bd_seq
FROM flagged;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.gold_dim_period
COMMENT "Monthly close periods. status: CLOSED (month fully elapsed), ACTIVE (current month, data through yesterday), FUTURE. Phasing fractions drive the month-to-date budget for continuous flux."
AS
WITH cut AS (SELECT date_sub(current_date(), 1) AS cutoff),
bd AS (SELECT b.*, c.cutoff FROM ${schema}.gold_dim_business_day b CROSS JOIN cut c),
p AS (
  SELECT
    period,
    min(cal_date)                                                          AS period_start,
    max(cal_date)                                                          AS period_end,
    max(cutoff)                                                            AS data_cutoff,
    sum(CAST(is_business_day AS INT))                                      AS bd_total,
    sum(CASE WHEN is_business_day AND cal_date <= cutoff THEN 1 ELSE 0 END) AS bd_elapsed,
    max(CASE WHEN is_business_day THEN cal_date END)                       AS last_business_day,
    max(CASE WHEN is_business_day AND day(cal_date) <= 15 THEN cal_date END) AS payroll_run_1,
    max(CASE WHEN cal_date = last_day(cal_date) THEN bd_seq END)           AS bd_seq_at_period_end
  FROM bd GROUP BY period
), bd5 AS (
  SELECT period, max(CASE WHEN rn = 5 THEN cal_date END) AS fifth_business_day
  FROM (SELECT period, cal_date, row_number() OVER (PARTITION BY period ORDER BY cal_date) AS rn
        FROM ${schema}.gold_dim_business_day WHERE is_business_day)
  GROUP BY period
)
SELECT
  p.period,
  p.period_start,
  p.period_end,
  year(p.period_start)                                                     AS fiscal_year,
  quarter(p.period_start)                                                  AS fiscal_quarter,
  date_format(p.period_start, 'MMM yyyy')                                  AS period_label,
  date_format(add_months(p.period_start, -1), 'yyyy-MM')                   AS prior_period,
  date_format(add_months(p.period_start, -12), 'yyyy-MM')                  AS prior_year_period,
  p.data_cutoff,
  CASE WHEN p.last_business_day <= p.data_cutoff THEN 'CLOSED'
       WHEN p.period_start <= p.data_cutoff THEN 'ACTIVE'
       ELSE 'FUTURE' END                                                   AS status,
  p.bd_total,
  p.bd_elapsed,
  p.last_business_day,
  p.payroll_run_1,
  bd5.fifth_business_day,
  p.bd_seq_at_period_end,
  CASE WHEN p.last_business_day <= p.data_cutoff THEN 1.0 ELSE p.bd_elapsed / p.bd_total END           AS phase_linear,
  ((CASE WHEN p.payroll_run_1 <= p.data_cutoff THEN 1 ELSE 0 END)
    + (CASE WHEN p.last_business_day <= p.data_cutoff THEN 1 ELSE 0 END)) / 2.0                        AS phase_payroll_runs,
  CASE WHEN p.last_business_day <= p.data_cutoff THEN 1.0 ELSE 0.0 END                                 AS phase_period_end,
  CASE WHEN bd5.fifth_business_day <= p.data_cutoff THEN 1.0 ELSE 0.0 END                              AS phase_step_bd5
FROM p JOIN bd5 USING (period)
WHERE p.period >= '2024-12' AND p.period <= '2027-01';
