#!/bin/sh
# Step 2: write report.md and schema.proposed.toml from tags.sqlite.
. "$(dirname "$0")/config.sh"
[ -f tags.sqlite ] || { echo "tags.sqlite not found: run ./1_scan.sh first" >&2; exit 1; }
"$PYTHON" analyze_tags.py --fuzzy "$@" || exit 1
if [ ! -f schema.toml ]; then
    echo
    echo "Next: review report.md, then  cp schema.proposed.toml schema.toml  and edit it."
fi
