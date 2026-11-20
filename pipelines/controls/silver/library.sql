-- ============================================================================
-- SILVER (controls spine): control library, close calendar, risk register
-- ============================================================================
-- Thin views over the meta_ tables written by publish_controls (outside the
-- pipeline, fully qualified). Thresholds reach every module's SQL as data from
-- here, never as literals.
-- ============================================================================
CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_control_library
COMMENT "Current version of every control (controls/library/*.yml via publish_controls)."
AS SELECT * FROM ${catalog}.${schema}.meta_control_library WHERE is_current;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_close_calendar
COMMENT "The 12 close tasks with their controls, sign-off role and due offsets (controls/close_calendar.yml)."
AS SELECT * FROM ${catalog}.${schema}.meta_close_calendar;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_risk_register
COMMENT "Risk register with KRIs and linked controls (controls/risk_register.yml)."
AS SELECT * FROM ${catalog}.${schema}.meta_risk_register;
