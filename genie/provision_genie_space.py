#!/usr/bin/env python3
"""Local CLI twin of provision_genie_space_job.py (ad-hoc use).

Shares genie_space_def.py with the job. Auth is delegated to the Databricks
CLI (`databricks api`), so no credentials live here.

    python genie/provision_genie_space.py --profile <p> --catalog <c> --warehouse-id <w> --dry-run
    python genie/provision_genie_space.py --profile <p> --catalog <c> --warehouse-id <w>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile

from genie_space_def import DEFAULT_DESCRIPTION, build_serialized_space, space_title


def api(method: str, path: str, profile: str, body: dict | None = None) -> dict:
    args = ["databricks", "api", method, path, "--profile", profile]
    if body is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(body, fh)
        args += ["--json", f"@{fh.name}"]
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip())
    return json.loads(p.stdout) if p.stdout.strip() else {}


def find_space_id(title: str, profile: str) -> str | None:
    token = ""
    while True:
        res = api("get", f"/api/2.0/genie/spaces?page_size=100{'&page_token=' + token if token else ''}", profile)
        for s in res.get("spaces", []):
            if s.get("title") == title:
                return s["space_id"]
        token = res.get("next_page_token", "")
        if not token:
            return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--catalog", required=True)
    ap.add_argument("--schema", default="fin_recon_observability")
    ap.add_argument("--warehouse-id", required=True)
    ap.add_argument("--target", default="prod")
    ap.add_argument("--parent-path", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    title = space_title(a.target)
    serialized = build_serialized_space(a.catalog, a.schema)
    if a.dry_run:
        print(json.dumps(serialized, indent=2))
        return 0
    body = {"title": title, "description": DEFAULT_DESCRIPTION,
            "warehouse_id": a.warehouse_id, "serialized_space": json.dumps(serialized)}
    existing = find_space_id(title, a.profile)
    if existing:
        api("patch", f"/api/2.0/genie/spaces/{existing}", a.profile, body)
        print(f"Updated {existing}")
    else:
        if a.parent_path:
            body["parent_path"] = a.parent_path
        print(f"Created {api('post', '/api/2.0/genie/spaces', a.profile, body).get('space_id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
