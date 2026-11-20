// Payload types for backend/routers/*. Field names match the JSON 1:1.
// Detail tables pass through as Row (column -> value) and render generically.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Row = Record<string, any>;

export interface MeResponse { email: string; display_name: string; initials: string; }

export interface AppConfigResponse {
  catalog: string;
  schema: string;
  workspace_url: string;
  run_controls_job_id: string;
  simulate_job_id: string;
  pipeline_id: string;
}

export interface RunTriggerResponse { job_id: string; run_id: number; run_page_url: string; }
export interface RunTask { task_key: string; state: string; result_state: string | null; start_time: number | null; end_time: number | null; }
export interface RunStatusResponse {
  run_id: number; life_cycle_state: string; result_state: string | null; state_message: string | null;
  start_time: number | null; end_time: number | null; run_page_url: string; tasks: RunTask[];
}

/** Deep-link templates from sqlutil.links(): {job_id} {run_id} {update_id} {table} {path}. */
export interface LinkTemplates { job_run: string; pipeline_update: string; pipeline: string; table: string; workspace_file: string; }

/** One row of meta_control_runs (the run ledger). */
export interface ControlRun {
  job_run_id: number; job_id: number | null; trigger_type: string | null; trigger_source: string | null;
  requested_by: string | null; reason: string | null; started_at: string | null; ended_at: string | null; status: string | null;
  library_hash: string | null; test_update_id: string | null; controls_executed: number | null; controls_failed: number | null;
  key_controls_failed: number | null; exceptions_found: number | null; new_exceptions: number | null;
  resolved_exceptions: number | null; triaged_exceptions: number | null; planted_recall: number | null;
  gate_result: string | null; gate_detail: string | null; active_period: string | null;
  [k: string]: unknown;
}

// ── Close ───────────────────────────────────────────────────────────────────
export interface LifecycleStage { stage: string; value: string | number; caption: string; page: string; }
export interface CloseSummary {
  active_period: string; last_closed_period: string; today_close_day: number | null;
  days_to_close_last: number | null; days_to_close_traditional: number | null; projected_days_to_close: number | null;
  target_days_to_close: number; north_star_days_to_close: number; pre_close_completion_pct: number | null;
  tasks_complete_pct: number | null; tasks_complete: number | null; tasks_total: number | null;
  tasks_overdue: number | null; tasks_blocked: number | null; control_pass_rate: number | null;
  controls_failed: number | null; key_controls_failed: number | null; records_tested: number | null;
  traditional_sample: number | null; open_exceptions: number | null; critical_open_exceptions: number | null;
  ai_triage_coverage_pct: number | null; unreconciled_amount_usd: number | null;
  lifecycle: LifecycleStage[]; latest_run: ControlRun | null;
}
export interface CloseTrendPoint { period: string; period_status: string; days_to_close: number | null; pre_close_completion_pct: number | null; target: number | null; }
export interface CloseTask {
  period: string; task_code: string; task_name: string; workstream: string; owner_role: string; period_status: string;
  due_offset_bd: number; traditional_due_bd: number; earliest_offset_bd: number; pre_close: boolean; signoff_role: string | null;
  controls: string[]; depends_on: string[]; controls_green: boolean; failing_controls: string[]; ready_at: string | null;
  signed_off_by: string | null; signed_off_at: string | null; completed_at: string | null; completed_close_day: number | null;
  projected_close_day: number | null; status: string; source: string; reopened_count: number; is_overdue: boolean;
  today_close_day: number | null; last_job_run_id: number | null;
}
export interface BurndownPoint { date: string; t: number; planned: number; traditional: number; actual: number | null; projected: number | null; }
export interface CloseBurndown {
  period: string; status: string; points: BurndownPoint[]; total: number; completed: number; remaining: number;
  pct_complete: number; today_t: number | null; target_t: number; projected_t: number | null; on_track: boolean; traditional_t: number;
}

// ── Checklist ───────────────────────────────────────────────────────────────
export interface SparkPoint { run: number; r: number; exceptions: number; }
export interface ChecklistRow {
  control_id: string; version: number; title: string; objective: string; module: string; module_name: string; lane: string;
  key_control: boolean; assertions: string[]; nature_type: string; automation: string; line_of_defense: number;
  frequency: string; owner_role: string; risk_ids: string[]; policy_ref: string | null;
  executed_by_kind: string; executed_by_task: string | null; executed_by_dataset: string | null; executed_by_expectation: string | null;
  is_info: boolean; traditional_sample_size: number | null;
  status: string; population: number | null; exceptions: number | null; amount_usd: number | null; open_exceptions: number | null;
  instances: number | null; failed_instances: number | null; executed_at: string | null; job_run_id: number | null;
  task_run_id: number | null; test_update_id: string | null; job_id: number | null;
  triage_pct: number | null; evidence_pct: number | null; dispositioned_pct: number | null; ai_high_risk: number | null;
  expectation: { passed: number; failed: number; dataset: string } | null;
  sparkline: SparkPoint[]; close_tasks: { task_code: string; name: string }[];
  signoff: { by: string; at: string; attested_job_run_id: number | null; pending_sync: boolean; superseded?: boolean } | null;
}
export interface ChecklistResponse { period: string; run: ControlRun | null; controls: ChecklistRow[]; summary: Record<string, number>; links: LinkTemplates; }
export interface ControlDetail {
  control: Row; period: string; entities: Row[]; run_history: Row[]; periods: Row[]; risks: Row[];
  policy: { policy_ref: string; clause_text: string } | null; definition_yaml: string | null; test_sql: string | null;
  test_sql_file: string | null; links: LinkTemplates;
}

// ── Exceptions ──────────────────────────────────────────────────────────────
export interface ExceptionRow {
  exception_id: string; module: string; control_id: string; control_title: string; key_control: boolean; lane: string;
  entity_code: string; region: string; period: string; record_key: string; record_type: string; amount_usd: number | null;
  detected_value: string; item_date: string | null; age_bd: number | null; is_info: boolean; rule_severity: string | null;
  disposition_status: string; disposition: string | null; proposed_by: string | null; approved_by: string | null;
  approved_at: string | null; review_comment: string | null; policy_ref: string | null; has_document_evidence: boolean;
  requires_evidence: boolean; lineage: Record<string, string> | null;
  ai_severity: string | null; ai_root_cause: string | null; ai_confidence: number | null; needs_human: boolean | null;
  ai_draft_finding: string | null; ai_recommended_action: string | null; ai_model: string | null;
  ai_rationale?: string | null; ai_triaged_at?: string | null; ai_prompt_version?: string | null;
  live_state?: Row; pending_sync?: boolean;
}
export interface ExceptionsResponse { period: string; rows: ExceptionRow[]; }
export interface TimelineEntry { action: string; disposition: string | null; comment: string | null; actor_email: string; actor_role: string; acted_at: string; source: string; pending_sync: boolean; }
export interface ExceptionDetail {
  exception: ExceptionRow; control: Row | null; evidence: Row[]; source_records: Record<string, Row[]>;
  timeline: TimelineEntry[]; state: Row; run_log: Row[];
  working_paper: { exception_id: string; title: string; body_md: string; ai_draft_md: string | null; author_email: string; updated_at: string } | null;
}

// ── Statements ──────────────────────────────────────────────────────────────
export interface StatementLine {
  line_code: string; line_name: string; line_order: number; line_type: string; actual: number | null; prior_period: number | null;
  prior_year: number | null; budget: number | null; budget_mtd: number | null; forecast: number | null;
  material_variances: number | null; unexplained: number | null;
}
export interface StatementResponse {
  statement: "IS" | "BS" | "CF"; entity: string; period: string; lines: StatementLine[];
  entities: { entity_code: string; entity_name: string; currency_code: string; region: string }[];
  badge: "FINAL" | "DRAFT"; close_day: number | null; data_status: string | null; basis_note: string;
}
export interface IntegrityResponse { period: string; checks: Row[]; differences: Row[]; }
export interface VariancesResponse { period: string; rows: Row[]; }
export interface DrillResponse { line: string; entity: string; period: string; accounts: Row[]; journals: Row[]; }

// ── Lineage ─────────────────────────────────────────────────────────────────
export type FlowStatus = "ok" | "drift" | "warn" | "fail";
export interface SankeyNode {
  id: string; label: string; stage: string; rows: number; datasets: string[]; status: FlowStatus;
  failed_records: number; rescued_rows: number; open?: number;
}
export interface SankeyLink { source: string; target: string; rows: number; status: FlowStatus; datasets: string[]; }
export interface SankeyResponse {
  update_id: string; job_run_id: number | null; recorded_at: string | null; level: string; stages: string[];
  nodes: SankeyNode[]; links: SankeyLink[]; links_tpl: LinkTemplates; dropped_back_edges: number;
  totals: { datasets: number; rows: number; failed_records: number; rescued_rows: number };
}
export interface LineageDatasets { rows: Row[]; links: LinkTemplates; }
export interface LineageFeeds { feeds: Row[]; drift: Row[]; }
export interface LineageExpectations { rows: Row[]; }
export interface FailingRecords { dataset: string; expectation: string | null; sql: string; rows: Row[]; note?: string; }
export interface LineageTimeline { runs: Row[]; links: LinkTemplates; }

// ── Modules ─────────────────────────────────────────────────────────────────
export interface ModuleResponse { module: string; name: string; period: string; kpis: Row; visual: Row & { kind: string }; }

// ── Reporting ───────────────────────────────────────────────────────────────
export interface RiskRow extends Row {
  risk_id: string; title: string; category: string; owner_role: string; inherent_likelihood: number; inherent_impact: number;
  inherent_score: number; appetite: string; kri_metric_view: string; kri_measure: string; kri_threshold: number;
  kri_direction: string; kri_label: string; control_ids: string[]; kri_value: number | null; kri_breached: boolean | null;
  linked_controls: { control_id: string; result: string; open_exceptions: number | null }[]; failing_controls: number; residual: string;
}
export interface RisksResponse { period: string; risks: RiskRow[]; }
export interface SoxPack {
  period: string; by_module: Row[]; by_assertion: Row[]; by_lane: Row[]; deficiencies: Row[]; remediation: Row[];
  health: Row; run: ControlRun | null;
}
export interface ReportSummary { period: string; markdown: string; numbers: Row; model: string; }

// ── Architecture ────────────────────────────────────────────────────────────
export interface Probe<T = unknown> { ok: boolean; data?: T; error?: string; }
export interface ArchitectureStatus {
  sources: Probe<Row[]>; pipeline: Probe<Row[]>; library: Probe<Row[]>; ledger: Probe<Row[]>; tables: Probe<Row[]>;
  triage: Probe<Row[]>; documents: Probe<Row[]>; tags: Probe<Row[]>;
  run_controls: Probe<Row>; simulate: Probe<Row>; refresh: Probe<Row>; genie: Probe<Row>; lakebase: Probe<Row>;
  assets: Probe<Row>; links: LinkTemplates;
}

// ── Assistant ───────────────────────────────────────────────────────────────
export interface ChatSession { session_id: string; title: string; created_at?: string; updated_at?: string; }
export interface ChatMessage { message_id: string; role: "user" | "assistant" | "tool"; content: string; tool_calls: Row[] | null; created_at: string; }
