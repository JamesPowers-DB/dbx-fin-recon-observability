"""Genie space definition (pure Python, no Databricks imports).

Importable by:
  * genie/provision_genie_space_job.py   (bundle job, canonical)
  * genie/provision_genie_space.py       (local CLI twin)
  * scripts/grant_app_sp_job.py          (title lookup for CAN_RUN)

Builds the version-2 serialized_space: the seven gold_mv_* metric views only,
instructions, example SQL, benchmarks, and sample questions. The app resolves the
space id by TITLE_BASE at runtime (GENIE_SPACE_TITLE in resources/apps.yml).
"""

from __future__ import annotations

import itertools

TITLE_BASE = "Fin Recon Observability - Audit & Controls"

DEFAULT_DESCRIPTION = (
    "Ask questions about the continuous close and control assurance at Corvane Technologies (fictional, synthetic data): "
    "days to close, control results per run, exceptions and AI triage, bank and subledger reconciliations, journal-entry "
    "testing, ERP access risk, and the financial statements with budget variance. Answers come only from governed "
    "Unity Catalog metric views, so they match the Audit Workbench app and the dashboard."
)

VIEWS = ["gold_mv_close", "gold_mv_control_health", "gold_mv_exceptions", "gold_mv_reconciliations",
         "gold_mv_journal_entries", "gold_mv_access_risk", "gold_mv_financials"]


def space_title(target: str = "prod") -> str:
    return TITLE_BASE


_ID_COUNTER = itertools.count(1)


def _next_id() -> str:
    return f"{next(_ID_COUNTER):032x}"


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True) or [text]


CURRENT = "date_format(current_date(), 'yyyy-MM')"


def questions(fq: str) -> list[tuple[str, str]]:
    """(question, governed SQL) pairs: example SQL, benchmarks and sample questions."""
    return [
        ("How has days to close trended over the last 12 months?",
         f"SELECT period, MEASURE(days_to_close) AS days_to_close, MEASURE(pre_close_completion_pct) AS pre_close_completion_pct\n"
         f"FROM {fq}.gold_mv_close\n"
         f"WHERE period_status = 'CLOSED' AND period >= date_format(add_months(current_date(), -12), 'yyyy-MM')\n"
         f"GROUP BY period\nORDER BY period"),
        ("Which key controls failed in the latest control run?",
         f"SELECT control_id, control_title, MEASURE(exceptions_found) AS exceptions, MEASURE(exception_amount_usd) AS exception_amount_usd\n"
         f"FROM {fq}.gold_mv_control_health\n"
         f"WHERE is_latest_run = true AND key_control = true AND result = 'FAIL'\n"
         f"GROUP BY control_id, control_title\nORDER BY exception_amount_usd DESC"),
        ("What is the unreconciled amount by entity and reconciliation type for the current close?",
         f"SELECT entity_code, recon_type, MEASURE(unreconciled_amount_usd) AS unreconciled_amount_usd, MEASURE(breaks) AS breaks\n"
         f"FROM {fq}.gold_mv_reconciliations\n"
         f"WHERE period = {CURRENT}\n"
         f"GROUP BY entity_code, recon_type\nHAVING MEASURE(unreconciled_amount_usd) > 0\nORDER BY unreconciled_amount_usd DESC"),
        ("How many manual journals over the approval threshold were posted without prior approval this quarter, by entity?",
         f"SELECT entity_code, MEASURE(unapproved_over_threshold_count) AS unapproved_over_threshold, MEASURE(self_approved_count) AS self_approved\n"
         f"FROM {fq}.gold_mv_journal_entries\n"
         f"WHERE period >= date_format(date_trunc('QUARTER', current_date()), 'yyyy-MM')\n"
         f"GROUP BY entity_code\nORDER BY unapproved_over_threshold DESC"),
        ("Which users posted journals after their termination date, and how much did they post?",
         f"SELECT user_name, entity_code, MEASURE(post_termination_journals) AS journals, MEASURE(post_termination_amount_usd) AS amount_usd\n"
         f"FROM {fq}.gold_mv_access_risk\n"
         f"GROUP BY user_name, entity_code\nHAVING MEASURE(post_termination_journals) > 0\nORDER BY amount_usd DESC"),
        ("Which material budget variances are still unexplained?",
         f"SELECT period, entity_code, line_name, MEASURE(variance_vs_budget_usd) AS variance_vs_budget_usd\n"
         f"FROM {fq}.gold_mv_financials\n"
         f"WHERE statement = 'IS'\n"
         f"GROUP BY period, entity_code, line_name\nHAVING MEASURE(unexplained_material_variances) > 0\nORDER BY period DESC, abs(variance_vs_budget_usd) DESC"),
        ("What is the control pass rate by module in the latest run for the current close?",
         f"SELECT module, MEASURE(control_pass_rate) AS control_pass_rate, MEASURE(controls_failed) AS controls_failed, MEASURE(records_tested) AS records_tested\n"
         f"FROM {fq}.gold_mv_control_health\n"
         f"WHERE is_latest_run = true AND period = {CURRENT}\n"
         f"GROUP BY module\nORDER BY module"),
        ("How many open exceptions did AI triage rate high or critical, by control?",
         f"SELECT control_id, control_title, MEASURE(open_exceptions) AS open_exceptions, MEASURE(ai_high_risk_exceptions) AS ai_high_risk\n"
         f"FROM {fq}.gold_mv_exceptions\n"
         f"WHERE period = {CURRENT}\n"
         f"GROUP BY control_id, control_title\nHAVING MEASURE(ai_high_risk_exceptions) > 0\nORDER BY ai_high_risk DESC"),
    ]


def build_serialized_space(catalog: str, schema: str) -> dict:
    fq = f"{catalog}.{schema}"
    tables = sorted([{"identifier": f"{fq}.{v}"} for v in VIEWS], key=lambda t: t["identifier"])
    qs = questions(fq)
    instructions_text = (
        "## What this space answers\n"
        "The monthly close and control assurance of Corvane Technologies (fictional company, synthetic data): how many days the "
        "close takes and how much is done before month end (continuous close), which controls passed or failed in each "
        "automated control run, the exceptions they found and how AI triage rated them, bank-to-book and subledger-to-GL "
        "reconciliations, journal-entry testing, ERP access risk, and the financial statements against the Anaplan budget.\n\n"
        "## HARD RULE: metric views only\n"
        "Query only the listed metric views and ALWAYS wrap aggregates in MEASURE(). GROUP BY dimensions directly; never "
        "SUM or COUNT a raw column. Filter on measures with HAVING MEASURE(x) > n. The views encode the governed definitions, "
        "so answers match the Audit Workbench app and the dashboard.\n\n"
        "## Which view to use\n"
        f"- `{fq}.gold_mv_close`: days to close, projected days to close, pre-close completion, task progress, overdue and blocked tasks.\n"
        f"- `{fq}.gold_mv_control_health`: control results per control run (ledger). Measures: control_pass_rate, controls_failed, "
        "key_controls_failed, records_tested, exceptions_found. ALWAYS filter is_latest_run = true unless the question is about history across runs.\n"
        f"- `{fq}.gold_mv_exceptions`: exceptions, open vs dispositioned, AI triage severity and root cause, evidence coverage, critical open exceptions.\n"
        f"- `{fq}.gold_mv_reconciliations`: unreconciled amount, breaks, in-tolerance share, auto-match rate (recon_type CASH, AR, AP, PAYROLL).\n"
        f"- `{fq}.gold_mv_journal_entries`: journal population and test flags (self-approved, unapproved over threshold, off-hours, duplicates, outliers).\n"
        f"- `{fq}.gold_mv_access_risk`: SoD conflicts, terminated users with access, post-termination postings.\n"
        f"- `{fq}.gold_mv_financials`: statements (statement IS, BS, CF; line_name), revenue, net income, cash, budget, "
        "variance vs budget, material and unexplained variances.\n\n"
        "## Definitions\n"
        "- DAYS TO CLOSE: business days after month end (T+n) when the controller GO task (CLS-12) completed. Lower is better. "
        "Target T+3, traditional baseline T+8, north star T+1.\n"
        "- PRE-CLOSE COMPLETION: share of close tasks finished on or before month end (continuous close).\n"
        f"- CURRENT CLOSE: period = {CURRENT} (period_status ACTIVE). Closed months have period_status CLOSED.\n"
        "- CONTROL PASS RATE: PASS or RESOLVED over PASS, RESOLVED and FAIL instances (instance = control x entity x period).\n"
        "- RESOLVED: exceptions over tolerance but every one has an approved disposition.\n"
        "- OPEN EXCEPTION: not yet approved by a reviewer. AI triage fields are AI-generated and advisory.\n"
        "- MATERIAL VARIANCE: |actual - budget| > USD 250,000 AND > 10% of budget; the current close compares month-to-date "
        "actuals with the month-to-date phased budget.\n\n"
        "## Style\n"
        "State the period, entity scope and filters you applied. Currency is USD. Measures ending in _pct are fractions: "
        "show them as percentages. When the user says 'this month' or 'the current close', use the current close period."
    )
    example_question_sqls = [
        {"id": _next_id(), "question": [q], "sql": _lines(sql),
         "usage_guidance": ["Governed pattern for this demo question; reuse the filters."]} for q, sql in qs]
    benchmarks = [{"id": _next_id(), "question": [q], "answer": [{"format": "SQL", "content": _lines(sql)}]} for q, sql in qs]
    samples = [q for q, _ in qs[:6]]
    return {
        "version": 2,
        "config": {"sample_questions": [{"id": _next_id(), "question": [q]} for q in samples]},
        "data_sources": {"tables": tables},
        "instructions": {
            "text_instructions": [{"id": _next_id(), "content": _lines(instructions_text)}],
            "example_question_sqls": example_question_sqls,
        },
        "benchmarks": {"questions": benchmarks},
    }
