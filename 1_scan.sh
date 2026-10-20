#!/bin/sh
# Step 1: read the tags of every file into tags.sqlite (+ tags.csv).
# Extra arguments are passed through, e.g. ./1_scan.sh --full
. "$(dirname "$0")/config.sh"
exec "$PYTHON" scan_tags.py "$MUSIC_DIR" --csv tags.csv "$@"
