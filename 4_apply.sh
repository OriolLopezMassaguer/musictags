#!/bin/sh
# Step 4: apply approved rows of changes.csv. Dry run unless --apply is given.
#   ./4_apply.sh                      dry run
#   ./4_apply.sh --apply --limit 20   try on 20 files
#   ./4_apply.sh --apply              everything
. "$(dirname "$0")/config.sh"
[ -f changes.csv ] || { echo "changes.csv not found: run ./3_propose.sh first" >&2; exit 1; }
exec "$PYTHON" apply_changes.py changes.csv "$@"
