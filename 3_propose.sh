#!/bin/sh
# Step 3: write changes.csv from tags.sqlite + schema.toml.
# Extra arguments are passed through, e.g. ./3_propose.sh --only genre,style
. "$(dirname "$0")/config.sh"
[ -f schema.toml ] || { echo "schema.toml not found: cp schema.proposed.toml schema.toml and edit it" >&2; exit 1; }
exec "$PYTHON" propose_changes.py "$@"
