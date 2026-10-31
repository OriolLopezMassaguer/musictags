#!/bin/sh
# Step 2: write report.md and schema.proposed.toml from tags.sqlite.
# On a first run it also seeds schema.toml from the proposal; an existing one is kept.
. "$(dirname "$0")/config.sh"
[ -f tags.sqlite ] || { echo "tags.sqlite not found: run ./1_scan.sh first" >&2; exit 1; }
exec "$PYTHON" analyze_tags.py --fuzzy "$@"
