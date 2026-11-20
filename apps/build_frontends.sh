#!/usr/bin/env bash
# Build the React frontends for all Databricks Apps.
# Run before `databricks bundle deploy` so frontend/dist/ exists on disk
# and gets synced to the workspace.
#
# Usage:
#   ./apps/build_frontends.sh           # build all apps
#   ./apps/build_frontends.sh <app>    # build only one app

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APPS=("audit-workbench")

# If an argument is provided, filter to matching app names
if [ $# -gt 0 ]; then
  FILTER="$1"
  FILTERED=()
  for app in "${APPS[@]}"; do
    if [[ "$app" == *"$FILTER"* ]]; then
      FILTERED+=("$app")
    fi
  done
  APPS=("${FILTERED[@]}")
fi

if [ "${#APPS[@]}" -eq 0 ]; then
  echo "No matching apps found for filter: $1" >&2
  exit 1
fi

REPO="$(cd "$HERE/.." && pwd)"

for app in "${APPS[@]}"; do
  echo "=== Building $app ==="
  # Read-only copy of the control definitions and test SQL for the checklist
  # drawer ("show me the control as code"). Regenerated on every build; gitignored.
  SNAP="$HERE/$app/backend/repo_snapshot"
  rm -rf "$SNAP" && mkdir -p "$SNAP"
  for d in controls pipelines ai; do
    rsync -a --exclude '__pycache__' --exclude '*.pyc' "$REPO/$d" "$SNAP/"
  done
  echo "  ✓ repo_snapshot ($(find "$SNAP" -type f | wc -l | tr -d ' ') files)"
  FRONTEND_DIR="$HERE/$app/frontend"
  if [ ! -d "$FRONTEND_DIR" ]; then
    echo "  SKIP: $FRONTEND_DIR not found"
    continue
  fi
  cd "$FRONTEND_DIR"
  npm install --silent
  npm run build
  if [ ! -f "dist/index.html" ]; then
    echo "FAIL: $app/frontend/dist/index.html not produced" >&2
    exit 1
  fi
  echo "  ✓ dist/ ready ($(du -sh dist | cut -f1))"
done

echo ""
echo "All frontends built. Run: databricks bundle deploy -t prod"
