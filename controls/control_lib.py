"""Control library: load, validate, and flatten the controls-as-code YAML.

Pure Python (PyYAML only, no Databricks imports). It is shared by three callers:
  * controls/runtime/publish_controls.py   job task: publishes meta_control_library
  * controls/validate_controls.py          local CLI twin and pre-deploy check
  * controls/runtime/gate_controls.py      monitoring-integrity gate (PLT-01)

Rules enforced by validate():
  1. Control ids are unique and every required field is present.
  2. executed_by.kind is expectation | pipeline_dataset | job_task, with its binding
     (expectation name, dataset, task) present.
  3. Every risk_id exists in risk_register.yml; every risk's control exists.
  4. Every close-calendar control and dependency exists; every operating control is
     used by at least one close task.
  5. Binding is real (checked against the SQL/notebook text when available): an
     expectation control's `CONSTRAINT <expectation>` appears in its test file;
     a dataset control's id appears as a literal in its test file.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
from datetime import date
from typing import Dict, List, Optional, Tuple

import yaml

KINDS = {"expectation", "pipeline_dataset", "job_task"}
LANES = {"management", "assurance"}
REQUIRED = ["control_id", "version", "title", "objective", "risk_ids", "key_control", "assertions", "nature", "lane",
            "frequency", "owner_role", "population", "parameters", "tolerance", "executed_by", "exceptions_dataset",
            "test_sql_file", "evidence", "signoff", "lifecycle"]


def controls_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def repo_root_from(controls_path: Optional[str] = None) -> str:
    return os.path.dirname(controls_path or controls_dir())


def _load(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_library(base: Optional[str] = None) -> List[dict]:
    base = base or controls_dir()
    out = []
    for path in sorted(glob.glob(os.path.join(base, "library", "*.yml"))):
        doc = _load(path)
        for c in doc.get("controls", []):
            c = dict(c)
            c["module"] = doc["module"]
            c["module_name"] = doc["module_name"]
            c["source_file"] = os.path.relpath(path, repo_root_from(base))
            c["slice"] = doc.get("slice", {})
            out.append(c)
    return out


def load_risks(base: Optional[str] = None) -> dict:
    return _load(os.path.join(base or controls_dir(), "risk_register.yml"))


def load_calendar(base: Optional[str] = None) -> dict:
    return _load(os.path.join(base or controls_dir(), "close_calendar.yml"))


def _canonical(c: dict) -> str:
    def default(o):
        return o.isoformat() if isinstance(o, date) else str(o)
    core = {k: v for k, v in c.items() if k not in ("source_file", "slice")}
    return json.dumps(core, sort_keys=True, default=default)


def definition_hash(c: dict) -> str:
    return hashlib.sha256(_canonical(c).encode()).hexdigest()[:16]


def validate(controls: List[dict], risks: dict, calendar: dict, repo_root: Optional[str] = None) -> List[str]:
    errors: List[str] = []
    ids = [c.get("control_id") for c in controls]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append(f"duplicate control ids: {sorted(dupes)}")
    risk_ids = {r["risk_id"] for r in risks.get("risks", [])}
    for c in controls:
        cid = c.get("control_id", "?")
        for f in REQUIRED:
            if f not in c:
                errors.append(f"{cid}: missing field '{f}'")
        eb = c.get("executed_by", {}) or {}
        kind = eb.get("kind")
        if kind not in KINDS:
            errors.append(f"{cid}: executed_by.kind '{kind}' not in {sorted(KINDS)}")
        if kind == "expectation" and not eb.get("expectation"):
            errors.append(f"{cid}: expectation control without executed_by.expectation")
        if kind in ("expectation", "pipeline_dataset") and not eb.get("dataset"):
            errors.append(f"{cid}: executed_by.dataset is required for kind {kind}")
        if kind == "job_task" and not eb.get("task"):
            errors.append(f"{cid}: executed_by.task is required for kind job_task")
        if c.get("lane") not in LANES:
            errors.append(f"{cid}: lane must be one of {sorted(LANES)}")
        for r in c.get("risk_ids", []):
            if r not in risk_ids:
                errors.append(f"{cid}: unknown risk {r}")
        if repo_root and c.get("test_sql_file"):
            p = os.path.join(repo_root, c["test_sql_file"])
            if not os.path.exists(p):
                errors.append(f"{cid}: test file {c['test_sql_file']} not found")
            else:
                text = open(p).read()
                if kind == "expectation" and f"CONSTRAINT {eb.get('expectation')}" not in text:
                    errors.append(f"{cid}: expectation '{eb.get('expectation')}' not declared in {c['test_sql_file']}")
                if kind == "pipeline_dataset" and f"'{cid}'" not in text:
                    errors.append(f"{cid}: control id literal not emitted by {c['test_sql_file']}")
    known = set(ids)
    for r in risks.get("risks", []):
        for cid in r.get("control_ids", []):
            if cid not in known:
                errors.append(f"risk {r['risk_id']}: unknown control {cid}")
    used = set()
    task_codes = {t["task_code"] for t in calendar.get("tasks", [])}
    for t in calendar.get("tasks", []):
        for cid in t.get("controls", []):
            used.add(cid)
            if cid not in known:
                errors.append(f"close task {t['task_code']}: unknown control {cid}")
        for dep in t.get("depends_on", []) or []:
            if dep not in task_codes:
                errors.append(f"close task {t['task_code']}: unknown dependency {dep}")
    for c in controls:
        if (c.get("lifecycle") or {}).get("state") == "operating" and c["control_id"] not in used:
            errors.append(f"{c['control_id']}: operating control not used by any close task")
    return errors


def control_rows(controls: List[dict]) -> List[dict]:
    rows = []
    for c in controls:
        nat, eb, tol = c["nature"], c["executed_by"], c["tolerance"] or {}
        ev, so, lc, pop = c["evidence"] or {}, c["signoff"] or {}, c["lifecycle"] or {}, c["population"] or {}
        eff = lc.get("effective_from")
        rows.append({
            "control_id": c["control_id"], "version": int(c["version"]), "module": c["module"],
            "module_name": c["module_name"], "title": c["title"], "objective": c["objective"],
            "risk_ids": list(c["risk_ids"]), "key_control": bool(c["key_control"]),
            "assertions": list(c["assertions"]), "nature_type": nat.get("type"), "automation": nat.get("automation"),
            "line_of_defense": int(nat.get("line_of_defense", 1)), "lane": c["lane"], "frequency": c["frequency"],
            "owner_role": c["owner_role"], "population_dataset": pop.get("dataset"), "population_unit": pop.get("unit"),
            "population_description": pop.get("description"),
            "parameters": {str(k): str(v) for k, v in (c.get("parameters") or {}).items()},
            "max_exceptions": tol.get("max_exceptions"), "max_amount_usd": tol.get("max_amount_usd"),
            "executed_by_kind": eb.get("kind"), "executed_by_job": eb.get("job"), "executed_by_task": eb.get("task"),
            "executed_by_dataset": eb.get("dataset"), "executed_by_expectation": eb.get("expectation"),
            "exceptions_dataset": c["exceptions_dataset"], "test_sql_file": c["test_sql_file"],
            "policy_ref": ev.get("policy_ref"), "evidence_documents": list(ev.get("documents") or []),
            "signoff_preparer_role": so.get("preparer_role"), "signoff_reviewer_role": so.get("reviewer_role"),
            "four_eyes": bool(so.get("four_eyes", True)), "lifecycle_state": lc.get("state"),
            "effective_from": eff if isinstance(eff, date) else (date.fromisoformat(str(eff)) if eff else None),
            "traditional_sample_size": int(c.get("traditional_sample_size") or 0),
            "definition_hash": definition_hash(c), "definition_json": _canonical(c), "source_file": c["source_file"],
        })
    return rows


def risk_rows(risks: dict) -> List[dict]:
    out = []
    for r in risks["risks"]:
        k, inh = r["kri"], r["inherent"]
        out.append({"risk_id": r["risk_id"], "title": r["title"], "category": r["category"], "owner_role": r["owner_role"],
                    "inherent_likelihood": int(inh["likelihood"]), "inherent_impact": int(inh["impact"]),
                    "inherent_score": int(inh["likelihood"]) * int(inh["impact"]), "appetite": r["appetite"],
                    "kri_metric_view": k["metric_view"], "kri_measure": k["measure"], "kri_threshold": float(k["threshold"]),
                    "kri_direction": k["direction"], "kri_label": k["label"], "control_ids": list(r["control_ids"]),
                    "register_version": int(risks.get("version", 1))})
    return out


def calendar_rows(cal: dict) -> List[dict]:
    out = []
    for t in cal["tasks"]:
        out.append({"task_code": t["task_code"], "name": t["name"], "workstream": t["workstream"],
                    "owner_role": t["owner_role"], "controls": list(t.get("controls") or []),
                    "depends_on": list(t.get("depends_on") or []), "signoff": t.get("signoff"),
                    "due_offset_bd": int(t["due_offset_bd"]), "traditional_due_bd": int(t["traditional_due_bd"]),
                    "earliest_offset_bd": int(t["earliest_offset_bd"]), "pre_close": bool(t.get("pre_close", False)),
                    "calendar_version": int(cal.get("version", 1)),
                    "target_days_to_close": int(cal["target_days_to_close"]),
                    "north_star_days_to_close": int(cal["north_star_days_to_close"]),
                    "traditional_days_to_close": int(cal["traditional_days_to_close"])})
    return out


def library_hash(controls: List[dict]) -> str:
    return hashlib.sha256("|".join(sorted(definition_hash(c) for c in controls)).encode()).hexdigest()[:16]


def load_all(base: Optional[str] = None) -> Tuple[List[dict], dict, dict]:
    return load_library(base), load_risks(base), load_calendar(base)
