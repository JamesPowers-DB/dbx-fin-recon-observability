-- ============================================================================
-- SILVER (M5): plan and phasing
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_plan
COMMENT "Plan amounts (USD, full month) by version, entity, account and period. version_type = Budget | Forecast."
AS SELECT 'Anaplan' AS source_system, 'plan_export' AS source_table,
  concat_ws('|', Version, Time, E1_Entity, G1_Account) AS source_primary_key,
  Version AS version, CASE WHEN Version LIKE 'Budget%' THEN 'Budget' ELSE 'Forecast' END AS version_type,
  date_format(to_date(concat('01 ', Time), 'dd MMM yy'), 'yyyy-MM') AS period,
  E1_Entity AS entity_code, G1_Account AS account_code, CAST(Amount AS DECIMAL(18,2)) AS amount_usd
FROM ${schema}.bronze_anaplan_plan;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_plan_phasing
COMMENT "Month-to-date phasing per account: profile plus payroll and period-end shares (the remainder phases linearly by business day)."
AS SELECT G1_Account AS account_code, Profile AS profile, CAST(Payroll_Share AS DOUBLE) AS payroll_share,
          CAST(Period_End_Share AS DOUBLE) AS period_end_share
FROM ${schema}.bronze_anaplan_phasing;
