-- ============================================================================
-- SILVER (controls spine): human review state, one direction only
-- ============================================================================
-- Two sources, unified into one action stream:
--   * closed periods: the prior close tool's dispositions and flux commentary
--   * live: Audit Workbench actions (Lakebase), copied by
--     run_controls.snapshot_review_state into meta_review_actions
-- silver_review_status = latest state per item. item_key formats:
--   exception  sha2(control_id|period|record_key)   variance  period|entity|fsli
--   close_task period|task_code                      control_signoff control_id|period
-- ============================================================================

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_review_actions
COMMENT "All review actions (history + live), one row per action. state_after: proposed | approved | rejected | explained | acknowledged | signed_off."
AS
WITH hist_exc AS (
  SELECT
    concat('hist-', sha2(concat_ws('|', control_id, period, record_key), 256)) AS action_id,
    'exception' AS item_type,
    sha2(concat_ws('|', control_id, period, record_key), 256) AS item_key,
    period, 'approve' AS action, disposition, comment,
    reviewed_by AS actor_email, 'reviewer' AS actor_role, prepared_by AS counterpart_email,
    CAST(reviewed_at AS TIMESTAMP) AS acted_at, 'close_tool' AS source
  FROM ${schema}.bronze_close_tool_review_history
), hist_var_explain AS (
  SELECT concat('hist-exp-', period, entity_code, fsli_code) AS action_id, 'variance' AS item_type,
         concat_ws('|', period, entity_code, fsli_code) AS item_key, period, 'explain' AS action, CAST(NULL AS STRING) AS disposition,
         explanation AS comment, author AS actor_email, 'controller' AS actor_role, CAST(NULL AS STRING) AS counterpart_email,
         CAST(authored_at AS TIMESTAMP) AS acted_at, 'close_tool' AS source
  FROM ${schema}.bronze_close_tool_variance_commentary
), hist_var_ack AS (
  SELECT concat('hist-ack-', period, entity_code, fsli_code), 'variance', concat_ws('|', period, entity_code, fsli_code), period,
         'acknowledge', CAST(NULL AS STRING), CAST(NULL AS STRING), acknowledged_by, 'reviewer', author,
         CAST(acknowledged_at AS TIMESTAMP), 'close_tool'
  FROM ${schema}.bronze_close_tool_variance_commentary WHERE NULLIF(acknowledged_by, '') IS NOT NULL
), hist_task AS (
  SELECT concat('hist-task-', period, task_code), 'close_task', concat_ws('|', period, task_code), period,
         'signoff', CAST(NULL AS STRING), CAST(NULL AS STRING), signed_off_by, 'reviewer', preparer,
         CAST(signed_off_at AS TIMESTAMP), 'close_tool'
  FROM ${schema}.bronze_close_tool_task_history WHERE NULLIF(signed_off_by, '') IS NOT NULL
), live AS (
  SELECT action_id, item_type, item_key, period, action, disposition, comment, actor_email, actor_role,
         get_json_object(payload, '$.counterpart_email') AS counterpart_email, created_at AS acted_at, 'audit_workbench' AS source
  FROM ${catalog}.${schema}.meta_review_actions
)
SELECT * FROM hist_exc
UNION ALL SELECT * FROM hist_var_explain
UNION ALL SELECT * FROM hist_var_ack
UNION ALL SELECT * FROM hist_task
UNION ALL SELECT * FROM live;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_review_status
COMMENT "Latest review state per item. For exceptions: disposition_status open | proposed | approved | rejected (approved = dispositioned). For variances: explained_by / acknowledged_by. For close tasks and controls: signed_off_by / signed_off_at."
AS
WITH a AS (SELECT * FROM ${schema}.silver_review_actions)
SELECT
  item_type, item_key, max(period) AS period,
  max_by(action, acted_at)                                                         AS last_action,
  max_by(source, acted_at)                                                         AS last_source,
  max(acted_at)                                                                    AS last_action_at,
  CASE max_by(action, acted_at) WHEN 'propose' THEN 'proposed' WHEN 'approve' THEN 'approved'
       WHEN 'reject' THEN 'rejected' WHEN 'reopen' THEN 'open' ELSE max_by(action, acted_at) END AS disposition_status,
  max_by(disposition, CASE WHEN action IN ('propose', 'approve') THEN acted_at END)            AS disposition,
  max_by(comment, CASE WHEN action IN ('propose', 'approve', 'explain') THEN acted_at END)     AS last_comment,
  max_by(actor_email, CASE WHEN action = 'propose' THEN acted_at END)                          AS proposed_by,
  max_by(actor_email, CASE WHEN action = 'approve' THEN acted_at END)                          AS approved_by,
  max(CASE WHEN action = 'approve' THEN acted_at END)                                          AS approved_at,
  max_by(actor_email, CASE WHEN action = 'explain' THEN acted_at END)                          AS explained_by,
  max(CASE WHEN action = 'explain' THEN acted_at END)                                          AS explained_at,
  max_by(actor_email, CASE WHEN action = 'acknowledge' THEN acted_at END)                      AS acknowledged_by,
  max(CASE WHEN action = 'acknowledge' THEN acted_at END)                                      AS acknowledged_at,
  max_by(actor_email, CASE WHEN action = 'signoff' THEN acted_at END)                          AS signed_off_by,
  max(CASE WHEN action = 'signoff' THEN acted_at END)                                          AS signed_off_at,
  count(*)                                                                                     AS action_count
FROM a GROUP BY item_type, item_key;

CREATE OR REFRESH MATERIALIZED VIEW ${schema}.silver_close_task_history
COMMENT "Prior close tool task history (closed periods): completion close day per task, used for the days-to-close trend."
AS SELECT period, task_code, task_name, workstream, preparer, NULLIF(reviewer, 'automated') AS reviewer,
          CAST(due_date AS DATE) AS due_date, CAST(completed_at AS TIMESTAMP) AS completed_at,
          CAST(completed_close_day AS INT) AS completed_close_day, NULLIF(signed_off_by, '') AS signed_off_by,
          CAST(NULLIF(signed_off_at, '') AS TIMESTAMP) AS signed_off_at, status, source_tool
FROM ${schema}.bronze_close_tool_task_history;
