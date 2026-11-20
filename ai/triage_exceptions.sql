-- ============================================================================
-- AI triage of control exceptions (run_controls task 6)
-- ============================================================================
-- One governed SQL statement: ai_query() on a pay-per-token Claude endpoint.
-- The prompt fixes a JSON contract; the statement extracts the JSON object,
-- parses it with from_json and validates the enum fields (structured-output
-- responseFormat is not available on current Claude endpoints). For every exception not yet triaged at
-- this prompt version (newest and largest first, capped per run), the model
-- gets the control objective, the governing policy clause, the detected facts,
-- the lineage keys and any parsed evidence. It returns a root-cause category,
-- severity, confidence, rationale, recommended action, a draft finding and
-- whether a human must decide. failOnError => false: a model error never
-- fails the control run; the row is retried next run.
-- Placeholders: __FQ__ __ENDPOINT__ __MAX__ __PROMPT_VERSION__ __JOB_RUN_ID__
-- ============================================================================
MERGE INTO __FQ__.ml_exception_triage t
USING (
  WITH todo AS (
    SELECT x.*
    FROM __FQ__.gold_control_exceptions x
    LEFT JOIN __FQ__.ml_exception_triage tr
      ON tr.exception_id = x.exception_id AND tr.prompt_version = '__PROMPT_VERSION__' AND tr.root_cause_category IS NOT NULL
    WHERE tr.exception_id IS NULL
    ORDER BY x.period DESC, x.amount_usd DESC
    LIMIT __MAX__
  ), ctx AS (
    SELECT t.*, c.objective, c.title, p.clause_text,
           ev.evidence_text
    FROM todo t
    JOIN __FQ__.gold_dim_control c ON c.control_id = t.control_id
    LEFT JOIN __FQ__.silver_policy_section p ON p.policy_ref = c.policy_ref
    LEFT JOIN (SELECT exception_id, concat_ws('\n---\n', collect_list(substr(evidence_text, 1, 600))) AS evidence_text
               FROM __FQ__.gold_exception_evidence WHERE evidence_type = 'document' GROUP BY exception_id) ev
      ON ev.exception_id = t.exception_id
  ), q AS (
    SELECT ctx.*,
      ai_query(
        '__ENDPOINT__',
        concat(
          'You are a SOX controls analyst at Corvane Technologies. Triage one control exception. ',
          'Be specific and concise; do not invent facts beyond the inputs.\n\n',
          'CONTROL ', control_id, ': ', title, '\nObjective: ', objective,
          '\nPolicy: ', COALESCE(clause_text, 'n/a'),
          '\n\nEXCEPTION\nEntity: ', entity_code, '  Period: ', period, '  Amount (USD): ', format_number(amount_usd, 2),
          '\nDetected: ', detected_value,
          '\nLineage keys: ', to_json(lineage),
          '\nAge (business days): ', COALESCE(CAST(age_bd AS STRING), 'n/a'),
          '\nSupporting documents (parsed): ', COALESCE(evidence_text, 'none on file'),
          '\n\nRespond with ONE JSON object and nothing else (no prose, no code fence), with exactly these keys:\n',
          '{"root_cause_category": one of "timing" | "interface_failure" | "missing_evidence" | "data_quality" | ',
          '"segregation_of_duties" | "unauthorized_activity" | "process_gap" | "valuation_or_estimate" | "potential_fraud" | "other", ',
          '"severity": one of "low" | "medium" | "high" | "critical", "confidence": number 0-1, ',
          '"rationale": string (2 sentences max), "recommended_action": string (1 sentence), ',
          '"draft_finding": string (audit-finding style, 2 sentences max), "needs_human": boolean}'),
        modelParameters => named_struct('max_tokens', 2000),
        failOnError => false) AS r
    FROM ctx
  ), parsed AS (
    SELECT exception_id, control_id, entity_code, period, r.errorMessage AS err,
           from_json(regexp_extract(r.result, '(?s)(\\{.*\\})', 1),
                     'root_cause_category STRING, severity STRING, confidence DOUBLE, rationale STRING, recommended_action STRING, draft_finding STRING, needs_human BOOLEAN') AS j
    FROM q
  )
  SELECT exception_id, control_id, entity_code, period,
         named_struct(
           'root_cause_category', CASE WHEN j.root_cause_category IN ('timing', 'interface_failure', 'missing_evidence', 'data_quality',
                                       'segregation_of_duties', 'unauthorized_activity', 'process_gap', 'valuation_or_estimate',
                                       'potential_fraud', 'other') THEN j.root_cause_category WHEN j IS NOT NULL THEN 'other' END,
           'severity', CASE WHEN lower(j.severity) IN ('low', 'medium', 'high', 'critical') THEN lower(j.severity) END,
           'confidence', CASE WHEN j.confidence IS NOT NULL THEN least(greatest(j.confidence, 0.0), 1.0) END,
           'rationale', j.rationale, 'recommended_action', j.recommended_action, 'draft_finding', j.draft_finding,
           'needs_human', COALESCE(j.needs_human, true)) AS o,
         COALESCE(err, CASE WHEN j IS NULL OR j.severity IS NULL THEN 'Model output was not the expected JSON' END) AS error_message
  FROM parsed
) s
ON t.exception_id = s.exception_id
WHEN MATCHED THEN UPDATE SET
  t.root_cause_category = s.o.root_cause_category, t.severity = s.o.severity, t.confidence = s.o.confidence,
  t.rationale = s.o.rationale, t.recommended_action = s.o.recommended_action, t.draft_finding = s.o.draft_finding,
  t.needs_human = s.o.needs_human, t.error_message = s.error_message, t.model = '__ENDPOINT__',
  t.prompt_version = '__PROMPT_VERSION__', t.triaged_at = current_timestamp(), t.job_run_id = __JOB_RUN_ID__
WHEN NOT MATCHED THEN INSERT (exception_id, control_id, entity_code, period, root_cause_category, severity, confidence, rationale,
  recommended_action, draft_finding, needs_human, error_message, model, prompt_version, triaged_at, job_run_id)
  VALUES (s.exception_id, s.control_id, s.entity_code, s.period, s.o.root_cause_category, s.o.severity, s.o.confidence, s.o.rationale,
          s.o.recommended_action, s.o.draft_finding, s.o.needs_human, s.error_message, '__ENDPOINT__', '__PROMPT_VERSION__',
          current_timestamp(), __JOB_RUN_ID__);
