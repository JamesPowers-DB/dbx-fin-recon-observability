#!/usr/bin/env python3
"""Build dashboards/continuous_close.lvdash.json (AI/BI dashboard, one page).

Every dataset queries a gold_mv_* metric view with MEASURE() and unqualified
names; resources/dashboards.yml binds dataset_catalog / dataset_schema, so the
same JSON deploys to any catalog. Storyline: north-star KPIs -> continuous close
trend -> control health -> reconciliation and risk -> action tables.

  python3 dashboards/build_dashboard.py            # writes the JSON
  python3 dashboards/build_dashboard.py --sql      # prints every dataset query (test them via CLI first)
"""
import json
import sys
from pathlib import Path

CUR = "date_format(current_date(), 'yyyy-MM')"
PREV = "date_format(add_months(current_date(), -1), 'yyyy-MM')"

DATASETS = {
    "ds_last_close": ("Last close", f"""SELECT MEASURE(days_to_close) AS days_to_close
FROM gold_mv_close WHERE period = {PREV}"""),
    "ds_active_close": ("Active close", """SELECT MEASURE(projected_days_to_close) AS projected_days_to_close,
       MEASURE(pre_close_completion_pct) AS pre_close_completion_pct, MEASURE(tasks_complete_pct) AS tasks_complete_pct,
       MEASURE(tasks_overdue) AS tasks_overdue
FROM gold_mv_close WHERE period_status = 'ACTIVE'"""),
    "ds_close_trend": ("Days to close by period", """SELECT period, MEASURE(days_to_close) AS days_to_close,
       MEASURE(pre_close_completion_pct) AS pre_close_completion_pct, MEASURE(target_days_to_close) AS target_days_to_close
FROM gold_mv_close WHERE period_status = 'CLOSED'
GROUP BY period ORDER BY period"""),
    "ds_controls_kpi": ("Controls (latest run)", f"""SELECT MEASURE(control_pass_rate) AS control_pass_rate, MEASURE(controls_failed) AS controls_failed,
       MEASURE(records_tested) AS records_tested
FROM gold_mv_control_health WHERE is_latest_run = true AND period = {CUR}"""),
    "ds_controls_module": ("Pass rate by module", f"""SELECT module, MEASURE(control_pass_rate) AS control_pass_rate, MEASURE(controls_failed) AS controls_failed
FROM gold_mv_control_health WHERE is_latest_run = true AND period = {CUR}
GROUP BY module ORDER BY module"""),
    "ds_exceptions_kpi": ("Exceptions (current close)", f"""SELECT MEASURE(open_exceptions) AS open_exceptions, MEASURE(ai_triage_coverage_pct) AS ai_triage_coverage_pct,
       MEASURE(critical_open_exceptions) AS critical_open_exceptions
FROM gold_mv_exceptions WHERE period = {CUR}"""),
    "ds_exceptions_sev": ("Open exceptions by module and AI severity", f"""SELECT module, COALESCE(ai_severity, 'not triaged') AS ai_severity, MEASURE(open_exceptions) AS open_exceptions
FROM gold_mv_exceptions WHERE period = {CUR}
GROUP BY ALL ORDER BY module"""),
    "ds_recon_kpi": ("Unreconciled (current close)", f"""SELECT MEASURE(unreconciled_amount_usd) AS unreconciled_amount_usd, MEASURE(breaks) AS breaks
FROM gold_mv_reconciliations WHERE period = {CUR}"""),
    "ds_recon_entity": ("Unreconciled by entity", f"""SELECT entity_code, recon_type, MEASURE(unreconciled_amount_usd) AS unreconciled_amount_usd
FROM gold_mv_reconciliations WHERE period = {CUR}
GROUP BY ALL ORDER BY entity_code"""),
    "ds_key_failures": ("Failed key controls", """SELECT control_id, control_title, MEASURE(exceptions_found) AS exceptions,
       MEASURE(exception_amount_usd) AS exception_amount_usd
FROM gold_mv_control_health WHERE is_latest_run = true AND key_control = true AND result = 'FAIL'
GROUP BY control_id, control_title ORDER BY exception_amount_usd DESC"""),
    "ds_variances": ("Unexplained material variances", """SELECT period, entity_code, line_name, MEASURE(variance_vs_budget_usd) AS variance_vs_budget_usd
FROM gold_mv_financials WHERE statement = 'IS'
GROUP BY period, entity_code, line_name HAVING MEASURE(unexplained_material_variances) > 0
ORDER BY period DESC"""),
}

USD = {"type": "number-currency", "currencyCode": "USD", "abbreviation": "compact", "decimalPlaces": {"type": "max", "places": 1}}
PCT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
INT = {"type": "number-plain", "decimalPlaces": {"type": "exact", "places": 0}}
DAYS = {"type": "number-plain", "decimalPlaces": {"type": "max", "places": 1}}
SEV_COLORS = [{"value": "critical", "color": "#FF3621"}, {"value": "high", "color": "#CC2B1A"},
              {"value": "medium", "color": "#FFAB00"}, {"value": "low", "color": "#7A99A6"},
              {"value": "not triaged", "color": "#C4CCD6"}]


def text(name, lines, x, y, w, h):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": lines}}, "position": {"x": x, "y": y, "width": w, "height": h}}


def counter(name, ds, field, title, fmt, x, y, desc=None, template=None):
    value = {"fieldName": field, "displayName": title}
    if fmt:
        value["format"] = fmt
    if template:
        value["formatTemplate"] = template
    frame = {"showTitle": True, "title": title}
    if desc:
        frame.update({"description": desc, "showDescription": True})
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
        "datasetName": ds, "fields": [{"name": field, "expression": f"`{field}`"}], "disaggregated": True}}],
        "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": value}, "frame": frame}},
        "position": {"x": x, "y": y, "width": 2, "height": 3}}


def chart(name, kind, ds, xf, yf, title, x, y, w, h, yfmt=None, color=None, color_map=None, sort=None, desc=None):
    fields = [{"name": xf, "expression": f"`{xf}`"}, {"name": yf, "expression": f"`{yf}`"}]
    enc = {"x": {"fieldName": xf, "scale": {"type": "categorical", **({"sort": sort} if sort else {})}, "displayName": xf.replace("_", " ")},
           "y": {"fieldName": yf, "scale": {"type": "quantitative"}, "displayName": yf.replace("_", " ")}}
    if yfmt:
        enc["y"]["format"] = yfmt
    if color:
        fields.append({"name": color, "expression": f"`{color}`"})
        enc["color"] = {"fieldName": color, "scale": {"type": "categorical", **({"mappings": color_map} if color_map else {})},
                        "displayName": color.replace("_", " ")}
    frame = {"showTitle": True, "title": title}
    if desc:
        frame.update({"description": desc, "showDescription": True})
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {"datasetName": ds, "fields": fields, "disaggregated": True}}],
                       "spec": {"version": 3, "widgetType": kind, "encodings": enc, "frame": frame}},
            "position": {"x": x, "y": y, "width": w, "height": h}}


def table(name, ds, cols, title, x, y, w, h):
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": {
        "datasetName": ds, "fields": [{"name": c, "expression": f"`{c}`"} for c, _, _ in cols], "disaggregated": True}}],
        "spec": {"version": 2, "widgetType": "table",
                 "encodings": {"columns": [{"fieldName": c, "displayName": d, **({"format": f} if f else {})} for c, d, f in cols]},
                 "frame": {"showTitle": True, "title": title}}},
        "position": {"x": x, "y": y, "width": w, "height": h}}


def build():
    L = [
        text("title", ["## Fin Recon Observability - Continuous Close\n", "\n",
                       "Corvane Technologies (fictional, synthetic data). Every number comes from governed Unity Catalog metric views "
                       "(gold_mv_*), the same definitions the Audit Workbench app and the Genie space use."], 0, 0, 12, 2),
        counter("kpi_dtc", "ds_last_close", "days_to_close", "Days to close (last close)", DAYS, 0, 2,
                "Business days after month end to controller GO", "T+{{@formatted}}"),
        counter("kpi_proj", "ds_active_close", "projected_days_to_close", "Projected days to close", DAYS, 2, 2,
                "Active close, from task status", "T+{{@formatted}}"),
        counter("kpi_preclose", "ds_active_close", "pre_close_completion_pct", "Pre-close completion", PCT, 4, 2,
                "Close tasks done before month end"),
        counter("kpi_pass", "ds_controls_kpi", "control_pass_rate", "Control pass rate", PCT, 6, 2, "Latest control run, current close"),
        counter("kpi_open", "ds_exceptions_kpi", "open_exceptions", "Open exceptions", INT, 8, 2, "Current close, awaiting disposition"),
        counter("kpi_unrec", "ds_recon_kpi", "unreconciled_amount_usd", "Unreconciled", USD, 10, 2, "Cash, AP, AR, payroll; current close"),
        text("h_close", ["### Continuous close: days to close is falling toward T+1"], 0, 5, 12, 1),
        chart("close_trend", "bar", "ds_close_trend", "period", "days_to_close", "Days to close by month (T+n)", 0, 6, 6, 6,
              DAYS, desc="FY2025 traditional close vs continuous monitoring from 2026"),
        chart("preclose_trend", "line", "ds_close_trend", "period", "pre_close_completion_pct",
              "Close tasks completed before month end (%)", 6, 6, 6, 6, PCT),
        text("h_controls", ["### Control health: full-population tests on every run"], 0, 12, 12, 1),
        chart("pass_by_module", "bar", "ds_controls_module", "module", "control_pass_rate", "Control pass rate by module (latest run)",
              0, 13, 6, 6, PCT),
        chart("exc_by_sev", "bar", "ds_exceptions_sev", "module", "open_exceptions", "Open exceptions by module and AI severity",
              6, 13, 6, 6, INT, color="ai_severity", color_map=SEV_COLORS),
        text("h_risk", ["### Reconciliation and risk"], 0, 19, 12, 1),
        chart("unrec_by_entity", "bar", "ds_recon_entity", "entity_code", "unreconciled_amount_usd",
              "Unreconciled amount by entity and type (current close)", 0, 20, 6, 6, USD, color="recon_type"),
        table("key_failures", "ds_key_failures", [("control_id", "Control", None), ("control_title", "Key control", None),
                                                  ("exceptions", "Exceptions", INT), ("exception_amount_usd", "Amount", USD)],
              "Failed key controls (latest run)", 6, 20, 6, 6),
        table("variances", "ds_variances", [("period", "Period", None), ("entity_code", "Entity", None), ("line_name", "Line", None),
                                            ("variance_vs_budget_usd", "Variance vs budget", USD)],
              "Unexplained material variances (management review gaps)", 0, 26, 12, 5),
    ]
    return {
        "datasets": [{"name": k, "displayName": v[0], "queryLines": [l + "\n" for l in v[1].splitlines()]} for k, v in DATASETS.items()],
        "pages": [{"name": "continuous_close", "displayName": "Continuous Close", "layout": L, "pageType": "PAGE_TYPE_CANVAS",
                   "layoutVersion": "GRID_V1"}],
        "uiSettings": {"theme": {
            "canvasBackgroundColor": {"light": "#F9F7F4", "dark": "#5A6F77"},
            "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#303F47"},
            "widgetBorderColor": {"light": "#DCE0E2", "dark": "#5A6F77"},
            "fontColor": {"light": "#1B3139", "dark": "#E8ECF0"},
            "selectionColor": {"light": "#FF3621", "dark": "#FF3621"},
            "visualizationColors": ["#1B3139", "#FF3621", "#7A99A6", "#FFAB00", "#CC2B1A", "#C4CCD6", "#243B44", "#FABFBA",
                                    "#0B6B3B", "#04355D", "#9ED6C4", "#BAE1FC", "#4A121A", "#5A6F77", "#E0654F", "#99DDB4"],
            "widgetHeaderAlignment": "LEFT"}, "applyModeEnabled": False},
    }


if __name__ == "__main__":
    if "--sql" in sys.argv:
        for k, (_, sql) in DATASETS.items():
            print(f"-- {k}\n{sql}\n;")
    else:
        out = Path(__file__).with_name("continuous_close.lvdash.json")
        out.write_text(json.dumps(build(), indent=2) + "\n")
        print(f"wrote {out}")
