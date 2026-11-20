// Single catalog of metric definitions surfaced via <MetricTooltip>.
// Wording mirrors the metric view comments (metric_views/apply_metric_views.py)
// and the router docstrings. Edit copy here, never in page components.

import type { MetricTooltipContent } from "./MetricTooltip";

type Metric = MetricTooltipContent;

export const METRICS = {
  days_to_close: {
    metric: "Days to close",
    period: "Per close period",
    definition: "Business days after month end (T+n) on which the controller's GO/NO-GO task (CLS-12) completed. The north star of continuous close.",
    formula: "MEASURE(days_to_close) on gold_mv_close",
    filters: "task_code = 'CLS-12', status = 'COMPLETE'",
  },
  projected_days_to_close: {
    metric: "Projected days to close",
    period: "Active close",
    definition: "Projected T+n for CLS-12 from each task's due day, today's position, failing controls (+1 day) and dependencies. Recomputed on every control run.",
    formula: "MEASURE(projected_days_to_close) on gold_mv_close",
    filters: "period = active close",
  },
  pre_close: {
    metric: "Done before month end",
    period: "Active close",
    definition: "Share of all close tasks completed on or before month end (T). The continuous-close measure: how much of the close no longer waits for the final ledger.",
    formula: "MEASURE(pre_close_completion_pct) on gold_mv_close",
    filters: "status = 'COMPLETE' AND completed_close_day <= 0",
  },
  control_pass_rate: {
    metric: "Control pass rate",
    period: "Latest control run, active close",
    definition: "Share of control instances (control x entity) that are PASS or RESOLVED in the latest run_controls run. INFO controls are excluded.",
    formula: "MEASURE(control_pass_rate) on gold_mv_control_health",
    filters: "is_latest_run = true",
  },
  open_exceptions: {
    metric: "Open exceptions",
    period: "Active close",
    definition: "Exceptions found by the control tests that have no approved disposition yet (four-eyes: proposed by one person, approved by another).",
    formula: "MEASURE(open_exceptions) on gold_mv_exceptions",
    filters: "is_open = true",
  },
  unreconciled: {
    metric: "Unreconciled amount",
    period: "Active close",
    definition: "Absolute unexplained difference across bank and subledger reconciliations, in USD.",
    formula: "MEASURE(unreconciled_amount_usd) on gold_mv_reconciliations",
  },
  triage_coverage: {
    metric: "AI triage coverage",
    period: "Active close",
    definition: "Share of exceptions with an AI triage (root cause, severity, draft finding) from the scheduled ai_query task. A human disposition is still required.",
    formula: "MEASURE(ai_triage_coverage_pct) on gold_mv_exceptions",
  },
  records_tested: {
    metric: "Records tested",
    period: "Latest control run",
    definition: "Population tested by the automated controls (every record, not a sample), compared with the traditional sample sizes in the control library.",
    formula: "MEASURE(records_tested) vs MEASURE(traditional_sample) on gold_mv_control_health",
  },
} satisfies Record<string, Metric>;

export type MetricKey = keyof typeof METRICS;
