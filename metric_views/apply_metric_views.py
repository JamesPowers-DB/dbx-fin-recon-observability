# Databricks notebook source
# MAGIC %md
# MAGIC # apply_metric_views: the governed semantic layer (gold_mv_*)
# MAGIC
# MAGIC Every number in the dashboard, Genie, the app, and the agent resolves from
# MAGIC these seven Unity Catalog metric views. Metric views are not valid Lakeflow
# MAGIC datasets, so they are applied here, after the pipeline and the first control
# MAGIC run. Two of them source the `meta_` run ledger.
# MAGIC
# MAGIC | View | Source | Subject |
# MAGIC |---|---|---|
# MAGIC | gold_mv_close | meta_close_task_status | days to close, pre-close %, task progress |
# MAGIC | gold_mv_control_health | meta_control_results (+ latest-run flag) | control execution and pass rate per run |
# MAGIC | gold_mv_exceptions | gold_control_exceptions + ml_exception_triage | exceptions, AI triage, evidence, disposition |
# MAGIC | gold_mv_reconciliations | gold_recon_summary | cash, AP, AR, payroll tie-outs |
# MAGIC | gold_mv_journal_entries | gold_fact_journal_entries | journal population and test flags |
# MAGIC | gold_mv_access_risk | gold_fact_user_access | SoD, terminations, post-termination activity |
# MAGIC | gold_mv_financials | gold_fact_statement_lines + gold_fact_variance_lines | statements, budget variance, commentary |
# MAGIC
# MAGIC Ratios are fractions (0 to 1) with a percentage format. Definitions are built
# MAGIC as Python dicts and rendered to YAML, which avoids brace collisions with
# MAGIC f-strings. The notebook ends with headline-KPI assertions and UC tags.
# MAGIC Idempotent.

# COMMAND ----------
import json

import yaml

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("schema", "fin_recon_observability")
catalog, schema = dbutils.widgets.get("catalog"), dbutils.widgets.get("schema")
assert catalog and schema
FQ = f"`{catalog}`.`{schema}`"
SRC = f"{catalog}.{schema}"

USD = {"type": "currency", "currency_code": "USD", "decimal_places": {"type": "exact", "places": 0}, "abbreviation": "compact"}
PCT = {"type": "percentage", "decimal_places": {"type": "max", "places": 1}}
NUM = {"type": "number", "decimal_places": {"type": "exact", "places": 0}}
DEC = {"type": "number", "decimal_places": {"type": "max", "places": 1}}


def dim(name, expr, display, comment, synonyms=()):
    return {"name": name, "expr": expr, "display_name": display, "comment": comment, "synonyms": list(synonyms)}


def mea(name, expr, display, comment, fmt=None, synonyms=()):
    m = {"name": name, "expr": expr, "display_name": display, "comment": comment, "synonyms": list(synonyms)}
    if fmt:
        m["format"] = fmt
    return m


class _NoAliasDumper(yaml.SafeDumper):
    """Shared format dicts (USD, PCT) would be emitted as YAML anchors/aliases,
    which the metric view parser does not resolve. Always inline them."""
    def ignore_aliases(self, data):
        return True


def apply(view, source, comment, dims, measures, joins=None):
    body = {"version": 1.1, "source": source, "comment": comment}
    if joins:
        body["joins"] = joins
    body["dimensions"] = dims
    body["measures"] = measures
    text = yaml.dump(body, Dumper=_NoAliasDumper, sort_keys=False, width=1000, allow_unicode=True)
    spark.sql(f"CREATE OR REPLACE VIEW {FQ}.{view} WITH METRICS LANGUAGE YAML AS $$\n{text}$$")
    print(f"applied {view}: {len(dims)} dimensions, {len(measures)} measures")

# COMMAND ----------
# MAGIC %md ## gold_mv_close (days to close, the north star)

# COMMAND ----------
apply("gold_mv_close", f"{SRC}.meta_close_task_status",
      "Monthly close progress per period and close task. Days to close = business days after month end (T+n) on which task CLS-12 "
      "(controller GO) completed. Closed periods come from the prior close tool; the active close is derived on every control run.",
      [dim("period", "period", "Close period", "Month being closed (yyyy-MM).", ["month", "close month"]),
       dim("period_status", "period_status", "Period status", "CLOSED (close complete) or ACTIVE (close in progress)."),
       dim("fiscal_year", "CAST(left(period, 4) AS INT)", "Fiscal year", "Calendar fiscal year.", ["year"]),
       dim("task_code", "task_code", "Close task code", "CLS-01 .. CLS-12."),
       dim("task_name", "task_name", "Close task", "Close task name.", ["task"]),
       dim("workstream", "workstream", "Workstream", "Close workstream (Reconciliation, Journal Entries, Reporting ...)."),
       dim("owner_role", "owner_role", "Owner role", "Role accountable for the task."),
       dim("status", "status", "Task status", "COMPLETE, READY_FOR_SIGNOFF, BLOCKED (controls failing), WAITING (dependencies), NOT_STARTED, REOPENED."),
       dim("pre_close", "pre_close", "Pre-close task", "True when the task can complete before month end (continuous close)."),
       dim("source", "source", "Status source", "close_tool (history) or control_run (live).")],
      [mea("days_to_close", "AVG(CASE WHEN task_code = 'CLS-12' AND completed_at IS NOT NULL THEN completed_close_day END)",
           "Days to close", "Business days after month end until the controller GO (CLS-12). Averaged across periods when grouped above period.", DEC,
           ["close duration", "time to close", "close days", "dtc"]),
       mea("projected_days_to_close", "AVG(CASE WHEN task_code = 'CLS-12' THEN COALESCE(completed_close_day, projected_close_day) END)",
           "Projected days to close", "Actual days to close for closed periods; projection for the active close (remaining tasks at their due day, +1 when controls are failing).", DEC,
           ["projected close", "forecast close day"]),
       mea("target_days_to_close", "AVG(target_days_to_close)", "Target days to close", "Continuous-close commitment from the close calendar (T+3).", DEC),
       mea("traditional_days_to_close", "AVG(traditional_days_to_close)", "Traditional days to close", "Pre-automation baseline (T+8).", DEC),
       mea("pre_close_completion_pct", "SUM(CASE WHEN status = 'COMPLETE' AND completed_close_day <= 0 THEN 1 ELSE 0 END) / NULLIF(COUNT(1), 0)",
           "Pre-close completion", "Share of close tasks completed on or before month end: the continuous-close measure.", PCT, ["continuous close %", "pre-close %"]),
       mea("tasks_complete_pct", "SUM(CASE WHEN status = 'COMPLETE' THEN 1 ELSE 0 END) / NULLIF(COUNT(1), 0)", "Tasks complete",
           "Share of close tasks complete.", PCT, ["close progress"]),
       mea("tasks_total", "COUNT(1)", "Close tasks", "Number of close tasks.", NUM),
       mea("tasks_complete", "SUM(CASE WHEN status = 'COMPLETE' THEN 1 ELSE 0 END)", "Tasks complete (count)", "Completed close tasks.", NUM),
       mea("tasks_overdue", "SUM(CASE WHEN is_overdue THEN 1 ELSE 0 END)", "Tasks overdue", "Open tasks past their due close day.", NUM),
       mea("tasks_blocked", "SUM(CASE WHEN status = 'BLOCKED' THEN 1 ELSE 0 END)", "Tasks blocked", "Tasks whose controls are failing.", NUM)])

# COMMAND ----------
# MAGIC %md ## gold_mv_control_health (the run ledger)

# COMMAND ----------
apply("gold_mv_control_health",
      f"SELECT r.*, to_date(r.executed_at) AS run_date, r.job_run_id = max_by(r.job_run_id, r.executed_at) OVER () AS is_latest_run FROM {SRC}.meta_control_results r",
      "Control results per run_controls run x control x entity x period (immutable ledger). Filter is_latest_run = true for the current state. "
      "Pass rate counts PASS and RESOLVED over PASS, RESOLVED and FAIL (INFO and NO_POPULATION excluded).",
      [dim("job_run_id", "job_run_id", "Control run", "run_controls job run id.", ["run"]),
       dim("is_latest_run", "is_latest_run", "Latest run", "True for the most recent control run."),
       dim("run_date", "run_date", "Run date", "Date the control run executed."),
       dim("executed_at", "executed_at", "Executed at", "Timestamp of the control run."),
       dim("test_update_id", "test_update_id", "Pipeline update", "Lakeflow pipeline update that tested the controls."),
       dim("control_id", "control_id", "Control", "Control id (e.g. JET-01).", ["control"]),
       dim("control_title", "control_title", "Control title", "Control name."),
       dim("module", "module", "Module", "M1 Cash, M2 Subledger, M3 Journals, M4 Access, M5 Statements and FP&A, DQ platform."),
       dim("lane", "lane", "Lane", "management (management monitoring) or assurance (independent Internal Audit tests)."),
       dim("key_control", "key_control", "Key control", "SOX key control flag."),
       dim("entity_code", "entity_code", "Entity", "Legal entity code.", ["legal entity", "company"]),
       dim("period", "period", "Period", "Month tested (yyyy-MM).", ["month"]),
       dim("result", "result", "Result", "PASS, RESOLVED, FAIL, INFO or NO_POPULATION.", ["status"])],
      [mea("controls_executed", "COUNT(DISTINCT control_id)", "Controls executed", "Distinct controls with results.", NUM),
       mea("control_instances", "COUNT(1)", "Control instances", "Control x entity x period results.", NUM),
       mea("controls_failed", "COUNT(DISTINCT CASE WHEN result = 'FAIL' THEN control_id END)", "Controls failed", "Distinct controls with at least one FAIL.", NUM,
           ["failing controls"]),
       mea("key_controls_failed", "COUNT(DISTINCT CASE WHEN result = 'FAIL' AND key_control THEN control_id END)", "Key controls failed",
           "Distinct SOX key controls with at least one FAIL.", NUM, ["failed key controls"]),
       mea("control_pass_rate", "SUM(CASE WHEN result IN ('PASS', 'RESOLVED') THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN result IN ('PASS', 'RESOLVED', 'FAIL') THEN 1 ELSE 0 END), 0)",
           "Control pass rate", "PASS or RESOLVED instances over PASS, RESOLVED and FAIL instances.", PCT, ["pass rate", "control effectiveness"]),
       mea("records_tested", "SUM(population_count)", "Records tested", "Records in the tested populations (full population, not samples).", NUM,
           ["population tested", "coverage"]),
       mea("traditional_sample", "SUM(traditional_sample_size)", "Traditional sample size", "What a sample-based test would have looked at.", NUM),
       mea("exceptions_found", "SUM(exceptions)", "Exceptions found", "Exceptions produced by the controls.", NUM, ["exceptions"]),
       mea("open_exceptions_at_run", "SUM(open_exceptions)", "Open exceptions (at run)", "Exceptions without an approved disposition at run time.", NUM),
       mea("exception_amount_usd", "SUM(exception_amount_usd)", "Exception amount", "Monetary impact of exceptions (USD).", USD),
       mea("latest_run_id", "MAX_BY(job_run_id, executed_at)", "Latest run id", "Most recent control run id in scope.", NUM),
       mea("latest_run_at", "MAX(executed_at)", "Latest run at", "Most recent control run time in scope.")])

# COMMAND ----------
# MAGIC %md ## gold_mv_exceptions (exceptions, AI triage, evidence, review)

# COMMAND ----------
apply("gold_mv_exceptions", f"{SRC}.gold_control_exceptions",
      "Control exceptions across all modules with AI triage (ml_exception_triage, ai_query) and human disposition. "
      "AI fields are AI-generated and need a human disposition. Open = not yet approved by a reviewer.",
      [dim("exception_id", "exception_id", "Exception id", "sha2(control_id|period|record_key)."),
       dim("control_id", "control_id", "Control", "Control id.", ["control"]),
       dim("control_title", "control_title", "Control title", "Control name."),
       dim("module", "module", "Module", "Module code (M1..M5, DQ)."),
       dim("lane", "lane", "Lane", "management or assurance."),
       dim("entity_code", "entity_code", "Entity", "Legal entity code.", ["company"]),
       dim("region", "region", "Region", "NA, EMEA, APAC, LATAM."),
       dim("period", "period", "Period", "Month (yyyy-MM).", ["month"]),
       dim("record_type", "record_type", "Record type", "journal, bank_entry, subledger_tieout, user, variance_line ..."),
       dim("disposition_status", "disposition_status", "Disposition status", "open, proposed, approved, rejected.", ["review status"]),
       dim("is_open", "is_open", "Open", "True until a reviewer approves a disposition."),
       dim("rule_severity", "rule_severity", "Rule severity", "critical, high, medium, info (from key-control flag and amount)."),
       dim("ai_severity", "triage.severity", "AI severity", "Severity assigned by AI triage (low, medium, high, critical).", ["triage severity"]),
       dim("ai_root_cause", "triage.root_cause_category", "AI root cause", "Root-cause category from AI triage.", ["root cause"]),
       dim("needs_human", "triage.needs_human", "Needs human judgement", "AI triage flagged the exception for human judgement.")],
      [mea("exceptions", "COUNT(1)", "Exceptions", "Exception count.", NUM),
       mea("open_exceptions", "SUM(CASE WHEN is_open THEN 1 ELSE 0 END)", "Open exceptions", "Exceptions without an approved disposition.", NUM,
           ["open issues", "unresolved exceptions"]),
       mea("exception_amount_usd", "SUM(amount_usd)", "Exception amount", "Monetary impact (USD).", USD),
       mea("open_exception_amount_usd", "SUM(CASE WHEN is_open THEN amount_usd ELSE 0 END)", "Open exception amount", "Monetary impact of open exceptions (USD).", USD),
       mea("ai_triage_coverage_pct", "COUNT(triage.root_cause_category) / NULLIF(COUNT(1), 0)", "AI triage coverage",
           "Share of exceptions with an AI triage record.", PCT, ["triaged %", "ai coverage"]),
       mea("ai_high_risk_exceptions", "SUM(CASE WHEN triage.severity IN ('high', 'critical') THEN 1 ELSE 0 END)", "AI high-risk exceptions",
           "Exceptions AI triage rated high or critical.", NUM),
       mea("critical_open_exceptions", "SUM(CASE WHEN is_open AND (triage.severity = 'critical' OR rule_severity = 'critical') THEN 1 ELSE 0 END)",
           "Critical open exceptions", "Open exceptions rated critical by AI triage or by rule (key control and >= USD 250k).", NUM),
       mea("evidence_attached_pct", "SUM(CASE WHEN requires_evidence AND has_document_evidence THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN requires_evidence THEN 1 ELSE 0 END), 0)",
           "Evidence attached", "Share of exceptions of evidence-backed controls with a matching document on file.", PCT),
       mea("dispositioned_pct", "SUM(CASE WHEN NOT is_open THEN 1 ELSE 0 END) / NULLIF(COUNT(1), 0)", "Dispositioned",
           "Share of exceptions with an approved disposition.", PCT, ["reviewed %"]),
       mea("avg_age_bd", "AVG(age_bd)", "Average age (business days)", "Average business days since the underlying record.", DEC)],
      joins=[{"name": "triage", "source": f"{SRC}.ml_exception_triage", "on": "source.exception_id = triage.exception_id"}])

# COMMAND ----------
# MAGIC %md ## gold_mv_reconciliations

# COMMAND ----------
apply("gold_mv_reconciliations", f"{SRC}.gold_recon_summary",
      "Reconciliations: bank-to-book per account x month (CASH) and subledger-to-GL per entity x month (AR, AP, PAYROLL). "
      "Unreconciled amount = absolute unexplained difference (USD).",
      [dim("recon_type", "recon_type", "Recon type", "CASH, AR, AP or PAYROLL.", ["reconciliation type"]),
       dim("recon_object", "recon_object", "Reconciliation", "Bank account or subledger x entity."),
       dim("entity_code", "entity_code", "Entity", "Legal entity code.", ["company"]),
       dim("period", "period", "Period", "Month (yyyy-MM).", ["month"]),
       dim("period_status", "period_status", "Period status", "CLOSED or ACTIVE."),
       dim("in_tolerance", "in_tolerance", "In tolerance", "Difference within policy tolerance.")],
      [mea("unreconciled_amount_usd", "SUM(abs(difference_usd))", "Unreconciled amount", "Absolute unexplained difference across reconciliations (USD).", USD,
           ["unreconciled", "recon breaks", "unexplained difference"]),
       mea("recon_in_tolerance_pct", "SUM(CASE WHEN in_tolerance THEN 1 ELSE 0 END) / NULLIF(COUNT(1), 0)", "Recons in tolerance",
           "Share of reconciliations within tolerance.", PCT, ["tie-out rate"]),
       mea("auto_match_rate", "SUM(items_matched) / NULLIF(SUM(items_total), 0)", "Auto-match rate", "Share of bank and book cash items matched automatically.", PCT),
       mea("aged_items", "SUM(items_aged_unmatched)", "Aged unmatched items", "Cash items unmatched beyond the aging window.", NUM),
       mea("reconciliations", "COUNT(1)", "Reconciliations", "Number of reconciliations.", NUM),
       mea("breaks", "SUM(CASE WHEN in_tolerance THEN 0 ELSE 1 END)", "Breaks", "Reconciliations out of tolerance.", NUM)])

# COMMAND ----------
# MAGIC %md ## gold_mv_journal_entries

# COMMAND ----------
apply("gold_mv_journal_entries", f"{SRC}.gold_fact_journal_entries",
      "Journal entries (full population) with journal-entry test flags (JET-01..05).",
      [dim("entity_code", "entity_code", "Entity", "Legal entity code.", ["company"]),
       dim("period", "period", "Period", "Accounting month (yyyy-MM).", ["month"]),
       dim("je_source", "je_source", "Journal source", "Receivables, Payables, Payroll, Manual, Spreadsheet, Assets, Cash Management."),
       dim("je_category", "je_category", "Journal category", "Accrual, Reclass, Adjustment, Sales Invoices ..."),
       dim("is_manual", "is_manual", "Manual journal", "Manual or spreadsheet journal.", ["manual"]),
       dim("created_by_user_name", "created_by_user_name", "Preparer", "ERP user who created the journal.", ["preparer", "user"])],
      [mea("je_count", "COUNT(1)", "Journals", "Journal count.", NUM, ["journal entries"]),
       mea("manual_je_count", "SUM(CASE WHEN is_manual THEN 1 ELSE 0 END)", "Manual journals", "Manual and spreadsheet journals.", NUM),
       mea("je_amount_usd", "SUM(amount_usd)", "Journal amount", "Sum of journal totals (USD).", USD),
       mea("manual_je_pct", "SUM(CASE WHEN is_manual THEN 1 ELSE 0 END) / NULLIF(COUNT(1), 0)", "Manual journal share", "Manual journals over all journals.", PCT),
       mea("flagged_je_count", "SUM(CASE WHEN jet01_self_approved OR jet02_unapproved_over_threshold OR jet03_off_hours OR jet04_duplicate OR jet05_outlier THEN 1 ELSE 0 END)",
           "Flagged journals", "Journals flagged by any JET test.", NUM),
       mea("flagged_je_amount_usd", "SUM(CASE WHEN jet01_self_approved OR jet02_unapproved_over_threshold OR jet03_off_hours OR jet04_duplicate OR jet05_outlier THEN amount_usd ELSE 0 END)",
           "Flagged journal amount", "Value of journals flagged by any JET test (USD).", USD),
       mea("self_approved_count", "SUM(CASE WHEN jet01_self_approved THEN 1 ELSE 0 END)", "Self-approved journals", "JET-01 exceptions.", NUM),
       mea("unapproved_over_threshold_count", "SUM(CASE WHEN jet02_unapproved_over_threshold THEN 1 ELSE 0 END)", "Unapproved over threshold", "JET-02 exceptions.", NUM),
       mea("off_hours_count", "SUM(CASE WHEN jet03_off_hours THEN 1 ELSE 0 END)", "Off-hours postings", "JET-03 exceptions.", NUM),
       mea("duplicate_count", "SUM(CASE WHEN jet04_duplicate THEN 1 ELSE 0 END)", "Potential duplicates", "JET-04 exceptions.", NUM),
       mea("outlier_count", "SUM(CASE WHEN jet05_outlier THEN 1 ELSE 0 END)", "Statistical outliers", "JET-05 KRI rows.", NUM)])

# COMMAND ----------
# MAGIC %md ## gold_mv_access_risk

# COMMAND ----------
apply("gold_mv_access_risk", f"{SRC}.gold_fact_user_access",
      "ERP access risk per user x month: SoD conflicts, terminated users with access, post-termination postings. Identity PII is masked.",
      [dim("entity_code", "entity_code", "Entity", "Legal entity code.", ["company"]),
       dim("period", "period", "Period", "Month (yyyy-MM).", ["month"]),
       dim("job_profile", "job_profile", "Job profile", "Workday job profile."),
       dim("user_name", "user_name", "ERP user", "Oracle user name.", ["user"])],
      [mea("active_users", "COUNT(DISTINCT user_id)", "Active ERP users", "Distinct non-system ERP users active in the period.", NUM),
       mea("sod_conflict_users", "COUNT(DISTINCT CASE WHEN has_sod_conflict THEN user_id END)", "Users with SoD conflicts",
           "Users holding a conflicting role pair.", NUM, ["sod conflicts", "segregation of duties"]),
       mea("terminated_with_access", "COUNT(DISTINCT CASE WHEN terminated_with_access THEN user_id END)", "Terminated users with access",
           "Users terminated in Workday whose ERP access stayed open.", NUM, ["leavers with access"]),
       mea("post_termination_journals", "SUM(post_termination_journals)", "Post-termination journals", "Journals created after termination.", NUM),
       mea("post_termination_amount_usd", "SUM(post_termination_amount_usd)", "Post-termination amount", "Value of journals created after termination (USD).", USD)])

# COMMAND ----------
# MAGIC %md ## gold_mv_financials

# COMMAND ----------
apply("gold_mv_financials", f"{SRC}.gold_fact_statement_lines",
      "Financial statements (income statement, balance sheet, cash flow) per entity x month in USD, with budget (Anaplan), phased MTD budget, "
      "forecast, prior period and prior year, and the variance review (materiality, explanation, independent acknowledgement).",
      [dim("statement", "statement", "Statement", "IS, BS or CF."),
       dim("line_code", "line_code", "Line code", "Statement line (e.g. IS-310, BS-100, CF-T60)."),
       dim("line_name", "line_name", "Line", "Statement line name.", ["account group", "fsli"]),
       dim("line_order", "line_order", "Line order", "Presentation order."),
       dim("line_type", "line_type", "Line type", "detail, subtotal or total."),
       dim("entity_code", "entity_code", "Entity", "Legal entity code.", ["company"]),
       dim("region", "region", "Region", "NA, EMEA, APAC, LATAM."),
       dim("period", "period", "Period", "Month (yyyy-MM).", ["month"]),
       dim("fiscal_year", "fiscal_year", "Fiscal year", "Calendar fiscal year.", ["year"]),
       dim("fiscal_quarter", "fiscal_quarter", "Fiscal quarter", "Quarter 1-4.", ["quarter"]),
       dim("data_status", "data_status", "Data status", "COMPLETE (month elapsed) or MONTH_TO_DATE.")],
      [mea("amount_usd", "SUM(actual_usd)", "Actual", "Actual amount (USD). IS and CF lines: period activity; BS lines: period-end balance.", USD, ["actual"]),
       mea("prior_period_usd", "SUM(prior_period_usd)", "Prior period", "Same line, previous month (USD).", USD),
       mea("prior_year_usd", "SUM(prior_year_usd)", "Prior year", "Same line, same month last year (USD).", USD),
       mea("budget_usd", "SUM(budget_usd)", "Budget", "Full-month budget (Anaplan, USD). Income statement only.", USD, ["plan"]),
       mea("budget_mtd_usd", "SUM(budget_mtd_usd)", "Budget (MTD phased)", "Budget phased to date for the active month (Anaplan phasing profile).", USD),
       mea("forecast_usd", "SUM(forecast_usd)", "Forecast", "Forecast 3+9 (Anaplan, USD).", USD),
       mea("revenue_usd", "SUM(CASE WHEN line_code = 'IS-T10' THEN actual_usd END)", "Revenue", "Total revenue (USD).", USD, ["sales", "revenue"]),
       mea("operating_income_usd", "SUM(CASE WHEN line_code = 'IS-T40' THEN actual_usd END)", "Operating income", "Operating income (USD).", USD, ["ebit"]),
       mea("net_income_usd", "SUM(CASE WHEN line_code = 'IS-T60' THEN actual_usd END)", "Net income", "Net income (USD).", USD, ["profit"]),
       mea("total_assets_usd", "SUM(CASE WHEN line_code = 'BS-T20' THEN actual_usd END)", "Total assets", "Total assets at period end (USD).", USD),
       mea("cash_usd", "SUM(CASE WHEN line_code = 'BS-100' THEN actual_usd END)", "Cash", "Cash and cash equivalents at period end (USD).", USD),
       mea("variance_vs_budget_usd", "SUM(v.variance_usd)", "Variance vs budget", "Actual minus budget (MTD-phased for the active month), P&L lines (USD).", USD),
       mea("material_variances", "SUM(CASE WHEN v.is_material THEN 1 ELSE 0 END)", "Material variances",
           "P&L lines whose variance exceeds both USD 250k and 10% of budget.", NUM, ["flux items"]),
       mea("unexplained_material_variances", "SUM(CASE WHEN v.is_material AND v.explained_by IS NULL THEN 1 ELSE 0 END)", "Unexplained material variances",
           "Material variances without a controller explanation.", NUM, ["unexplained variances", "open flux"]),
       mea("independently_acknowledged_pct",
           "SUM(CASE WHEN v.is_material AND v.independently_acknowledged THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN v.is_material AND v.explained_by IS NOT NULL THEN 1 ELSE 0 END), 0)",
           "Independently acknowledged", "Explained material variances acknowledged by someone other than the author.", PCT)],
      joins=[{"name": "v", "source": f"{SRC}.gold_fact_variance_lines",
              "on": "source.line_code = v.fsli_code AND source.entity_code = v.entity_code AND source.period = v.period"}])

# COMMAND ----------
# MAGIC %md ## Unity Catalog tags (non-fatal)

# COMMAND ----------
TAGS = [
    ("TABLE", "gold_fact_gl_lines", {"sox_scope": "in_scope", "data_domain": "general_ledger"}),
    ("TABLE", "gold_fact_journal_entries", {"sox_scope": "in_scope", "data_domain": "journal_entries"}),
    ("TABLE", "gold_fact_statement_lines", {"sox_scope": "in_scope", "data_domain": "financial_statements"}),
    ("TABLE", "gold_control_exceptions", {"sox_scope": "in_scope", "confidential": "audit_working"}),
    ("TABLE", "ml_exception_triage", {"confidential": "audit_working", "ai_generated": "true"}),
    ("TABLE", "gold_fact_user_access", {"sox_scope": "itgc", "pii": "masked"}),
    ("TABLE", "meta_control_results", {"sox_scope": "evidence", "retention": "7y"}),
]
for kind, t, tags in TAGS:
    kv = ", ".join(f"'{k}' = '{v}'" for k, v in tags.items())
    for stmt in (f"ALTER TABLE {FQ}.{t} SET TAGS ({kv})", f"ALTER MATERIALIZED VIEW {FQ}.{t} SET TAGS ({kv})"):
        try:
            spark.sql(stmt)
            print("tagged", t)
            break
        except Exception as e:  # noqa: BLE001
            last = e
    else:
        print(f"WARN could not tag {t}: {str(last)[:160]}")
for col in ("legal_name", "email"):
    try:
        spark.sql(f"ALTER MATERIALIZED VIEW {FQ}.gold_fact_user_access ALTER COLUMN {col} SET TAGS ('pii' = 'identity')")
    except Exception as e:  # noqa: BLE001
        print(f"WARN column tag {col}: {str(e)[:120]}")

# COMMAND ----------
# MAGIC %md ## Headline KPI assertions (fail the job on a broken semantic layer)

# COMMAND ----------
def one(sql):
    return spark.sql(sql).collect()[0].asDict()


k = {}
k.update(one(f"""SELECT MEASURE(days_to_close) AS last_closed_days_to_close FROM {FQ}.gold_mv_close
                 WHERE period = (SELECT max(period) FROM {FQ}.meta_close_task_status WHERE period_status = 'CLOSED')"""))
k.update(one(f"""SELECT MEASURE(projected_days_to_close) AS projected_days_to_close, MEASURE(pre_close_completion_pct) AS pre_close_completion_pct
                 FROM {FQ}.gold_mv_close WHERE period_status = 'ACTIVE'"""))
k.update(one(f"""SELECT MEASURE(control_pass_rate) AS control_pass_rate, MEASURE(records_tested) AS records_tested,
                        MEASURE(controls_executed) AS controls_executed
                 FROM {FQ}.gold_mv_control_health WHERE is_latest_run AND period = date_format(current_date(), 'yyyy-MM')"""))
k.update(one(f"""SELECT MEASURE(open_exceptions) AS open_exceptions, MEASURE(ai_triage_coverage_pct) AS ai_triage_coverage_pct
                 FROM {FQ}.gold_mv_exceptions WHERE period = date_format(current_date(), 'yyyy-MM')"""))
k.update(one(f"""SELECT MEASURE(unreconciled_amount_usd) AS unreconciled_amount_usd FROM {FQ}.gold_mv_reconciliations
                 WHERE period = date_format(current_date(), 'yyyy-MM')"""))
k.update(one(f"""SELECT MEASURE(unexplained_material_variances) AS unexplained_material_variances, MEASURE(revenue_usd) AS ytd_revenue_usd
                 FROM {FQ}.gold_mv_financials WHERE fiscal_year = year(current_date())"""))
k = {key: (float(v) if v is not None else None) for key, v in k.items()}
print(json.dumps(k, indent=2))
assert k["last_closed_days_to_close"] and 1 <= k["last_closed_days_to_close"] <= 15, "days to close out of range"
assert k["projected_days_to_close"] is not None and k["projected_days_to_close"] <= 15, "projected days to close missing"
assert k["control_pass_rate"] is not None and 0 < k["control_pass_rate"] < 1, "control pass rate out of range"
assert k["records_tested"] and k["records_tested"] > 1000, "records tested too small"
assert k["controls_executed"] and k["controls_executed"] >= 25, "too few controls executed in the latest run"
assert k["open_exceptions"] and k["open_exceptions"] > 0, "no open exceptions in the active close (planted scenarios missing?)"
assert k["ai_triage_coverage_pct"] is not None and 0 <= k["ai_triage_coverage_pct"] <= 1, "triage coverage out of range"
assert k["unreconciled_amount_usd"] and k["unreconciled_amount_usd"] > 0, "no unreconciled amount in the active close"
assert k["unexplained_material_variances"] and k["unexplained_material_variances"] >= 1, "no unexplained material variances"
assert k["ytd_revenue_usd"] and k["ytd_revenue_usd"] > 1e9, "YTD revenue implausible"
dbutils.notebook.exit(json.dumps(k))
