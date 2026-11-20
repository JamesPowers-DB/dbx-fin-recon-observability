#!/usr/bin/env python3
"""Run SQL on a warehouse through the Statement Execution API (local dev only).

Why: `databricks experimental aitools tools query` re-flows multi-line input,
which breaks indentation-sensitive metric view YAML. This helper sends the
statement verbatim through `databricks api`, so it uses the CLI profile's auth.

  scripts/dev/run_sql.py --profile <profile> --warehouse <id> "SELECT 1"
  scripts/dev/run_sql.py --profile <profile> --warehouse <id> --file x.sql
Statements in a file are split on lines that contain only ';'.
"""
import argparse
import json
import subprocess
import sys
import tempfile


def run(stmt: str, profile: str, warehouse: str) -> dict:
    body = {"warehouse_id": warehouse, "statement": stmt, "wait_timeout": "50s",
            "on_wait_timeout": "CONTINUE", "format": "JSON_ARRAY", "disposition": "INLINE"}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(body, f)
    out = subprocess.run(["databricks", "api", "post", "/api/2.0/sql/statements", "--json", f"@{f.name}",
                          "--profile", profile], capture_output=True, text=True)
    if out.returncode:
        sys.exit(out.stderr)
    r = json.loads(out.stdout)
    sid = r.get("statement_id")
    while r["status"]["state"] in ("PENDING", "RUNNING"):
        g = subprocess.run(["databricks", "api", "get", f"/api/2.0/sql/statements/{sid}", "--profile", profile],
                           capture_output=True, text=True)
        r = json.loads(g.stdout)
    return r


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("sql", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--warehouse", required=True)
    a = ap.parse_args()
    text = open(a.file).read() if a.file else a.sql
    stmts = [s.strip() for s in text.split("\n;\n") if s.strip()]
    for s in stmts:
        r = run(s, a.profile, a.warehouse)
        st = r["status"]["state"]
        if st != "SUCCEEDED":
            print(f"FAILED: {r['status'].get('error', {}).get('message')}")
            sys.exit(1)
        cols = [c["name"] for c in r.get("manifest", {}).get("schema", {}).get("columns", [])]
        rows = r.get("result", {}).get("data_array") or []
        if cols:
            print("\t".join(cols))
            for row in rows:
                print("\t".join("" if v is None else str(v) for v in row))
        else:
            print("OK")


if __name__ == "__main__":
    main()
