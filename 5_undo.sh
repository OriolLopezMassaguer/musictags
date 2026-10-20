#!/bin/sh
# Undo a previous apply. Dry run unless --apply is given.
#   ./5_undo.sh undo_20261020_140000.jsonl [--apply]
. "$(dirname "$0")/config.sh"
[ -n "$1" ] || { echo "usage: $0 undo_XXXX.jsonl [--apply]" >&2; ls undo_*.jsonl 2>/dev/null; exit 1; }
log="$1"; shift
exec "$PYTHON" apply_changes.py --undo "$log" "$@"
