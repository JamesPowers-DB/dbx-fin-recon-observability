#!/usr/bin/env python3
"""Validate the control library locally (CLI twin of publish_controls).

  uv run --with pyyaml python controls/validate_controls.py

Exit code 1 on any violation of the containment and binding rules in
control_lib.validate(). Run before every deploy; publish_controls and
gate_controls run the same checks on the workspace.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control_lib  # noqa: E402

controls, risks, cal = control_lib.load_all()
errors = control_lib.validate(controls, risks, cal, repo_root=control_lib.repo_root_from())
print(f"controls={len(controls)} risks={len(risks['risks'])} close_tasks={len(cal['tasks'])} "
      f"library_hash={control_lib.library_hash(controls)}")
for e in errors:
    print("  ERROR", e)
sys.exit(1 if errors else 0)
