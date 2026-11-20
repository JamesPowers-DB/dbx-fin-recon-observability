"""Data Quality & Lineage: the Sankey, feed freshness, expectations, schema drift, run timelines.

Everything here is read from what the platform recorded about itself:
meta_pipeline_update_metrics (copied from the pipeline's published event log by
run_controls.record_results: datasets, input datasets, rows, expectations) and the
run ledger. The Sankey is the pipeline's own flow graph for the update that tested
the controls; no band is drawn from a hard-coded list.
"""

from __future__ import annotations

import re
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException

from ..auth import CallerIdentity, caller_identity
from ..db import fetch_all, fetch_many
from ..sqlutil import fq, links, safe_code

router = APIRouter(prefix="/lineage", tags=["lineage"])

SOURCE_SYSTEMS = {
    "oracle": "Oracle Fusion ERP", "sfdc": "Salesforce", "workday": "Workday", "anaplan": "Anaplan",
    "bank": "Bank feed (camt.053)", "close": "Close tool export", "docs": "Evidence documents",
}
EXTERNAL = {
    "meta_control_library": "Control library (Git)", "meta_risk_register": "Control library (Git)",
    "meta_close_calendar": "Control library (Git)", "meta_review_actions": "Lakebase review store",
}
DOMAIN_LABEL = {
    "core": "Core ledger", "documents": "Documents", "m1_cash": "M1 Cash", "m2_subledger": "M2 Subledger",
    "m3_journals": "M3 Journals", "m4_access": "M4 Access", "m5_statements": "M5 Statements & FP&A", "controls": "Controls spine",
}
MODULE_DOMAIN = {"M1": "m1_cash", "M2": "m2_subledger", "M3": "m3_journals", "M4": "m4_access", "M5": "m5_statements",
                 "DQ": "controls", "PLT": "controls"}
MODULE_LABEL = {"M1": "M1 Cash", "M2": "M2 Subledger", "M3": "M3 Journals", "M4": "M4 Access", "M5": "M5 Statements & FP&A",
                "DQ": "Data quality", "PLT": "Platform"}
_EXP_NAME = re.compile(r"^ctl_[a-z0-9_]+$")


def _source_of(bronze: str) -> str:
    key = bronze.removeprefix("bronze_").split("_")[0]
    return SOURCE_SYSTEMS.get(key, key)


def _stage(d: dict) -> str:
    if d["dataset"].endswith("_exceptions") or d["dataset"] in ("gold_control_exceptions", "gold_control_results"):
        return "tests"
    return d["layer"]


def _status(d: dict, rescued: dict[str, int]) -> str:
    if (d.get("failed_records") or 0) > 0:
        return "warn"
    if rescued.get(d["dataset"], 0) > 0:
        return "drift"
    if d.get("status") not in (None, "COMPLETED", "NOT_RUN"):
        return "fail"
    return "ok"


def _drop_cycles(node_ids: list[str], links_: list[dict]) -> tuple[list[dict], int]:
    """A Sankey needs a DAG. Domain-level grouping can fold a dataset DAG into a cycle
    (for example the controls spine reads module tests and is read by them); drop
    the back edges found by a DFS in stage order and report how many were dropped."""
    adj: dict[str, list[dict]] = defaultdict(list)
    for lk in links_:
        adj[lk["source"]].append(lk)
    state: dict[str, int] = {}
    dropped: set[int] = set()

    def visit(n: str) -> None:
        state[n] = 1
        for lk in adj[n]:
            t = lk["target"]
            if state.get(t) == 1:
                dropped.add(id(lk))
            elif t not in state:
                visit(t)
        state[n] = 2

    for n in node_ids:
        if n not in state:
            visit(n)
    return [lk for lk in links_ if id(lk) not in dropped], len(dropped)


@router.get("/sankey")
def sankey(update_id: str | None = None, level: str = "domain", caller: CallerIdentity = Depends(caller_identity)) -> dict:
    """level=domain: source systems -> bronze by source -> silver/gold by domain -> control tests by module.
    level=dataset: every pipeline dataset, edges from the flow definitions."""
    upd = safe_code(update_id, "update id")
    r = fetch_many(caller, {
        "upd": (f"""SELECT update_id, max_by(job_run_id, recorded_at) AS job_run_id, max(recorded_at) AS recorded_at
                    FROM {fq('meta_pipeline_update_metrics')} {'WHERE update_id = ?' if upd else ''}
                    GROUP BY update_id ORDER BY recorded_at DESC LIMIT 1""", [upd] if upd else None),
        "rescued": f"SELECT bronze_table, sum(rows_rescued) AS n FROM {fq('gold_dq_rescued_files')} GROUP BY bronze_table",
        "exc": f"""SELECT module, count(*) AS n, sum(CASE WHEN is_open THEN 1 ELSE 0 END) AS open
                   FROM {fq('gold_control_exceptions')} GROUP BY module""",
    })
    if not r["upd"]:
        raise HTTPException(404, "No pipeline update metrics yet. Run run_controls to record them.")
    u = r["upd"][0]
    ds = fetch_all(caller, f"SELECT * FROM {fq('meta_pipeline_update_metrics')} WHERE update_id = ?", [u["update_id"]])
    rescued = {x["bronze_table"]: int(x["n"] or 0) for x in r["rescued"]}
    by_name = {d["dataset"]: d for d in ds}

    nodes: dict[str, dict] = {}
    links_: dict[tuple[str, str], dict] = {}

    def node(nid: str, label: str, stage: str, **kw) -> str:
        n = nodes.setdefault(nid, {"id": nid, "label": label, "stage": stage, "rows": 0, "datasets": [], "status": "ok",
                                   "failed_records": 0, "rescued_rows": 0, **kw})
        return nid

    def link(a: str, b: str, rows: int, status: str, dataset: str | None) -> None:
        lk = links_.setdefault((a, b), {"source": a, "target": b, "rows": 0, "status": "ok", "datasets": set()})
        lk["rows"] += max(int(rows or 0), 0)
        if dataset:
            lk["datasets"].add(dataset)
        order = ["ok", "drift", "warn", "fail"]
        if order.index(status) > order.index(lk["status"]):
            lk["status"] = status

    def group_id(d: dict) -> str:
        if level == "dataset":
            return d["dataset"]
        st = _stage(d)
        if st == "bronze":
            return f"bronze:{_source_of(d['dataset'])}"
        if st == "tests":
            mod = {"controls": "Controls spine"}.get(d["domain"], DOMAIN_LABEL.get(d["domain"], d["domain"]))
            return f"tests:{mod}"
        return f"{st}:{d['domain']}"

    def group_label(d: dict) -> str:
        if level == "dataset":
            return d["dataset"]
        st = _stage(d)
        if st == "bronze":
            return _source_of(d["dataset"])
        if st == "tests":
            return f"{DOMAIN_LABEL.get(d['domain'], d['domain'])} tests"
        return f"{DOMAIN_LABEL.get(d['domain'], d['domain'])} ({st})"

    for d in ds:
        gid = group_id(d)
        st = _status(d, rescued)
        n = nodes[node(gid, group_label(d), _stage(d))]
        n["rows"] += int(d.get("rows_in_table") or 0)
        n["datasets"].append(d["dataset"])
        n["failed_records"] += int(d.get("failed_records") or 0)
        n["rescued_rows"] += rescued.get(d["dataset"], 0)
        if ["ok", "drift", "warn", "fail"].index(st) > ["ok", "drift", "warn", "fail"].index(n["status"]):
            n["status"] = st
        if _stage(d) == "bronze":
            src = node(f"src:{_source_of(d['dataset'])}", _source_of(d["dataset"]), "source")
            nodes[src]["rows"] += int(d.get("rows_in_table") or 0)
            link(src, gid, d.get("rows_in_table") or 0, "drift" if rescued.get(d["dataset"]) else "ok", d["dataset"])
        for inp in d.get("input_datasets") or []:
            if inp in by_name:
                a = group_id(by_name[inp])
                if a != gid:
                    link(a, gid, by_name[inp].get("rows_in_table") or 0, st, d["dataset"])
            elif inp in EXTERNAL:
                src = node(f"src:{EXTERNAL[inp]}", EXTERNAL[inp], "source")
                link(src, gid, 1, "ok", d["dataset"])

    # Close the graph at the right edge: control tests -> exceptions found by module.
    for m in r["exc"]:
        label = MODULE_LABEL.get(m["module"], m["module"])
        tgt = node(f"exc:{m['module']}", f"{label}: {int(m['n'])} exceptions", "exceptions", open=int(m["open"] or 0))
        nodes[tgt]["rows"] = int(m["n"])
        nodes[tgt]["status"] = "fail" if (m["open"] or 0) > 0 else "ok"
        want = "gold_dq_exceptions" if m["module"] == "DQ" else f"gold_{m['module'].lower()}_exceptions"
        src_id = next((nid for nid, n in nodes.items() if n["stage"] == "tests" and want in n["datasets"]), None)
        if src_id:
            link(src_id, tgt, int(m["n"]), "fail" if (m["open"] or 0) > 0 else "ok", None)

    stages = ["source", "bronze", "silver", "gold", "tests", "exceptions"]
    order = sorted(nodes, key=lambda nid: stages.index(nodes[nid]["stage"]) if nodes[nid]["stage"] in stages else 9)
    out_links, dropped = _drop_cycles(order, [{**v, "datasets": sorted(v["datasets"])} for v in links_.values()
                                              if v["source"] in nodes and v["target"] in nodes])
    return {"update_id": u["update_id"], "job_run_id": u["job_run_id"], "recorded_at": u["recorded_at"], "level": level,
            "stages": stages, "nodes": sorted(nodes.values(), key=lambda n: (stages.index(n["stage"]) if n["stage"] in stages else 9, n["label"])),
            "links": out_links, "links_tpl": links(), "dropped_back_edges": dropped,
            "totals": {"datasets": len(ds), "rows": sum(int(d.get("rows_in_table") or 0) for d in ds),
                       "failed_records": sum(int(d.get("failed_records") or 0) for d in ds),
                       "rescued_rows": sum(rescued.values())}}


@router.get("/datasets")
def datasets(update_id: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    upd = safe_code(update_id, "update id")
    where = "update_id = ?" if upd else f"update_id = (SELECT max_by(update_id, recorded_at) FROM {fq('meta_pipeline_update_metrics')})"
    rows = fetch_all(caller, f"""SELECT dataset, domain, layer, dataset_kind, source_file, input_datasets, rows_in_table, rows_written,
                                        duration_s, expectations, passed_records, failed_records, status, update_id, job_run_id
                                 FROM {fq('meta_pipeline_update_metrics')} WHERE {where} ORDER BY domain, layer, dataset""",
                     [upd] if upd else None)
    return {"rows": rows, "links": links()}


@router.get("/feeds")
def feeds(caller: CallerIdentity = Depends(caller_identity)) -> dict:
    r = fetch_many(caller, {
        "feeds": f"SELECT * FROM {fq('gold_dq_feed_status')} ORDER BY within_sla, source_system, feed",
        "drift": f"""SELECT bronze_table, file_name, rows_total, rows_rescued, sample_rescued_field
                     FROM {fq('gold_dq_rescued_files')} WHERE rows_rescued > 0 ORDER BY rows_rescued DESC""",
    })
    return r


@router.get("/expectations")
def expectations(caller: CallerIdentity = Depends(caller_identity)) -> dict:
    """Expectation pass/fail per pipeline update (the trend behind the WARN expectations that implement controls)."""
    rows = fetch_all(caller, f"""
        SELECT m.update_id, max(m.recorded_at) AS recorded_at, max(m.job_run_id) AS job_run_id, e.name, max(m.dataset) AS dataset,
               sum(e.passed) AS passed, sum(e.failed) AS failed
        FROM {fq('meta_pipeline_update_metrics')} m LATERAL VIEW explode(m.expectations) x AS e
        GROUP BY m.update_id, e.name ORDER BY recorded_at DESC, e.name LIMIT 400""")
    ctl = fetch_all(caller, f"""SELECT executed_by_expectation AS name, control_id, title FROM {fq('gold_dim_control')}
                                WHERE executed_by_expectation IS NOT NULL""")
    by = {c["name"]: c for c in ctl}
    for r in rows:
        c = by.get(r["name"]) or {}
        r["control_id"], r["control_title"] = c.get("control_id"), c.get("title")
    return {"rows": rows}


@router.get("/failing-records")
def failing_records(dataset: str, expectation: str | None = None, caller: CallerIdentity = Depends(caller_identity)) -> dict:
    """Rows that failed an expectation (WARN keeps them, the flag column says which) or carry rescued data."""
    ds = safe_code(dataset, "dataset")
    known = fetch_all(caller, f"""SELECT dataset, expectations FROM {fq('meta_pipeline_update_metrics')}
                                  WHERE dataset = ? ORDER BY recorded_at DESC LIMIT 1""", [ds])
    if not known:
        raise HTTPException(404, f"{ds} is not a pipeline dataset")
    exps = [e["name"] for e in (known[0].get("expectations") or [])]
    if expectation:
        if expectation not in exps or not _EXP_NAME.match(expectation):
            raise HTTPException(400, f"{expectation} is not an expectation on {ds}")
        sql = f"SELECT * FROM {fq(ds)} WHERE NOT {expectation}_pass LIMIT 100"
        rows = fetch_all(caller, sql)
        return {"dataset": ds, "expectation": expectation, "sql": sql, "rows": rows}
    if ds.startswith("bronze_"):
        sql = f"SELECT * FROM {fq(ds)} WHERE _rescued_data IS NOT NULL AND _rescued_data <> '' LIMIT 100"
        return {"dataset": ds, "expectation": None, "sql": sql, "rows": fetch_all(caller, sql)}
    if exps:
        cond = " OR ".join(f"NOT {e}_pass" for e in exps if _EXP_NAME.match(e))
        sql = f"SELECT * FROM {fq(ds)} WHERE {cond} LIMIT 100"
        return {"dataset": ds, "expectation": None, "sql": sql, "rows": fetch_all(caller, sql)}
    if ds.endswith("_exceptions"):
        sql = f"SELECT * FROM {fq(ds)} ORDER BY amount_usd DESC LIMIT 100"
        return {"dataset": ds, "expectation": None, "sql": sql, "rows": fetch_all(caller, sql)}
    sql = f"SELECT * FROM {fq(ds)} LIMIT 25"
    return {"dataset": ds, "expectation": None, "sql": sql, "rows": fetch_all(caller, sql), "note": "No failing-record rule on this dataset; sample rows."}


@router.get("/timeline")
def timeline(caller: CallerIdentity = Depends(caller_identity)) -> dict:
    """Run ledger joined to the pipeline update each run tested: the audit trail of when monitoring ran."""
    r = fetch_many(caller, {
        "runs": f"""SELECT r.*, u.datasets, u.rows_written, u.failed_records, u.duration_s
                    FROM {fq('meta_control_runs')} r
                    LEFT JOIN (SELECT update_id, count(*) AS datasets, sum(rows_written) AS rows_written,
                                      sum(failed_records) AS failed_records, max(duration_s) AS duration_s
                               FROM {fq('meta_pipeline_update_metrics')} GROUP BY update_id) u ON u.update_id = r.test_update_id
                    ORDER BY r.started_at DESC LIMIT 40""",
        "changes": f"""SELECT job_run_id, change, count(*) AS n FROM {fq('meta_control_exception_log')}
                       WHERE job_run_id IN (SELECT job_run_id FROM {fq('meta_control_runs')} ORDER BY started_at DESC LIMIT 40)
                       GROUP BY job_run_id, change""",
    })
    by = defaultdict(dict)
    for c in r["changes"]:
        by[c["job_run_id"]][c["change"]] = c["n"]
    for x in r["runs"]:
        x["exception_changes"] = by.get(x["job_run_id"], {})
    return {"runs": r["runs"], "links": links()}
