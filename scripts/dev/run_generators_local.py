#!/usr/bin/env python3
"""Run the data generators locally (no Databricks) for fast iteration.

Executes each notebook in data/generators/ in job order with stubbed `dbutils`
and `spark`. /Volumes/<cat>/<schema>/<vol>/ maps to --out, and Delta writes
(meta_planted_exceptions, meta_dim_period_anchors) are kept in memory and
dumped to --out/_tables/*.parquet.

  uv run --with polars --with numpy --with fpdf2 --with pyyaml --with pandas \
    python scripts/dev/run_generators_local.py --out .scratch/gen [--only 01,02]
"""
import argparse
import os
import re
import sys
import time
import types
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
GEN = ROOT / "data" / "generators"
ORDER = ["01_period_anchors_seed", "02_reference_masters", "03_salesforce_billing", "04_workday_payroll",
         "05_oracle_ap", "06_oracle_gl", "07_bank_camt053", "08_anaplan_plan", "09_close_tool_history",
         "10_documents_pdfs", "99_reconcile"]


class Widgets:
    def __init__(self, values):
        self.values = values

    def text(self, name, default="", label=None):
        self.values.setdefault(name, default)

    def get(self, name):
        return self.values.get(name, "")


class NotebookExit(Exception):
    pass


class FakeDbutils:
    def __init__(self, values):
        self.widgets = Widgets(values)
        self.notebook = types.SimpleNamespace(exit=self._exit)
        self.jobs = types.SimpleNamespace(taskValues=types.SimpleNamespace(set=lambda **k: None))

    @staticmethod
    def _exit(value=None):
        raise NotebookExit(value)


class FakeFrame:
    def __init__(self, pdf):
        self.pdf = pdf

    def toPandas(self):
        return self.pdf.copy()

    def where(self, cond):
        # Minimal parser for "period < 'X' AND expected_disposition <> 'open'".
        df = self.pdf
        for part in re.split(r"\s+AND\s+", cond, flags=re.I):
            m = re.match(r"\s*(\w+)\s*(<>|<|=)\s*'([^']*)'\s*", part)
            col, op, val = m.groups()
            df = df[df[col] < val] if op == "<" else df[df[col] != val] if op == "<>" else df[df[col] == val]
        return FakeFrame(df)

    @property
    def write(self):
        return FakeWriter(self)


class FakeWriter:
    def __init__(self, frame):
        self.frame, self.mode_ = frame, "overwrite"

    def format(self, *_):
        return self

    def mode(self, m):
        self.mode_ = m
        return self

    def option(self, *_):
        return self

    def saveAsTable(self, name):
        key = name.replace("`", "").split(".")[-1]
        if self.mode_ == "append" and key in TABLES:
            TABLES[key] = pd.concat([TABLES[key], self.frame.pdf], ignore_index=True)
        else:
            TABLES[key] = self.frame.pdf.copy()


TABLES: dict = {}


class FakeSpark:
    def sql(self, q):
        m = re.match(r"\s*DELETE FROM\s+(\S+)\s+WHERE\s+generator\s*=\s*'([^']+)'", q, flags=re.I)
        if m:
            key = m.group(1).replace("`", "").split(".")[-1]
            if key in TABLES:
                TABLES[key] = TABLES[key][TABLES[key]["generator"] != m.group(2)]
        return FakeFrame(pd.DataFrame())

    def createDataFrame(self, pdf, schema=None):
        return FakeFrame(pdf)

    def table(self, name):
        return FakeFrame(TABLES.get(name.replace("`", "").split(".")[-1], pd.DataFrame()))


def run(nb: str, out: Path, catalog: str, schema: str) -> None:
    src = (GEN / f"{nb}.py").read_text()
    lib = (GEN / "_lib.py").read_text()
    vol_root = str(out)
    g = {"__name__": "__main__", "spark": FakeSpark(),
         "dbutils": FakeDbutils({"catalog": catalog, "schema": schema, "raw_volume": "files", "tolerance_pct": "2.0"})}
    exec(compile(lib, "_lib.py", "exec"), g)
    g["volume_dir"] = lambda c, s, v, *parts: os.path.join(vol_root, *parts)
    g["repo_root"] = lambda: str(ROOT)
    body = src.replace("# MAGIC %run ./_lib", "")
    t = time.time()
    try:
        exec(compile(body, f"{nb}.py", "exec"), g)
    except NotebookExit as e:
        print(f"  exit: {str(e.args[0])[:300] if e.args else ''}")
    print(f"== {nb} OK in {time.time() - t:.1f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / ".scratch" / "gen"))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tdir = out / "_tables"
    tdir.mkdir(exist_ok=True)
    for p in tdir.glob("*.parquet"):
        TABLES[p.stem] = pd.read_parquet(p)
    only = [x for x in a.only.split(",") if x]
    for nb in ORDER:
        if only and not any(nb.startswith(o) for o in only):
            continue
        print(f"-> {nb}")
        run(nb, out, "local_catalog", "fin_recon_observability")
        for k, v in TABLES.items():
            v.to_parquet(tdir / f"{k}.parquet", index=False)


if __name__ == "__main__":
    sys.exit(main())
