#!/usr/bin/env python3
"""
Step 4 - apply_changes.py: write the approved changes to the files (with undo).

    python apply_changes.py changes.csv                 # DRY RUN: shows what would change
    python apply_changes.py changes.csv --apply         # writes tags, creates undo_<time>.jsonl
    python apply_changes.py --undo undo_20261020_1400.jsonl --apply   # restore previous values

Only rows with approve = y/yes/x/1 are applied (--all applies every row, approved or not,
including the low-confidence ones). Before writing, each file is re-read:
if a field no longer has the 'old' value of the CSV (the file changed after the scan),
that change is skipped (use --force to override).

Ctrl-C (or the GUI's "Parar") is honoured between files, never inside a write, so no
file is ever left half-tagged. The undo log covers what was written before stopping.
"""
import argparse
import csv
import json
import sqlite3
import sys
import time
from collections import defaultdict

from core import (EXIT_INTERRUPTED, LIST_SEP, handle_interrupts, load_config, read_tags,
                  stopping, write_tags)

YES = {"y", "yes", "x", "1", "true", "si", "sí"}


def split_list(s):
    return [x.strip() for x in s.split(LIST_SEP.strip())] if s.strip() else []


def refresh_cache(db_path, paths):
    try:
        db = sqlite3.connect(db_path)
        import os
        for p in paths:
            fmt, tags = read_tags(p)
            st = os.stat(p)
            db.execute("UPDATE files SET tags=?, mtime=?, size=?, scanned=? WHERE path=?",
                       (json.dumps(tags, ensure_ascii=False), st.st_mtime, st.st_size, time.time(), p))
        db.commit()
    except Exception as exc:
        print(f"(cache not updated: {exc}; just re-run scan_tags.py)", file=sys.stderr)


def run(plan, apply, force, id3_version, log_path, db_path):
    """plan: {path: [(field, old_list, new_list)]}"""
    done = skipped = failed = 0
    log = open(log_path, "a", encoding="utf-8") if apply else None
    written = []
    interrupted = False
    for path, items in plan.items():
        if stopping():
            # Between two files: the previous write_tags() finished and its undo
            # lines are already flushed, so stopping here loses nothing.
            interrupted = True
            break
        try:
            _, cur = read_tags(path)
        except Exception as exc:
            print(f"ERROR reading {path}: {exc}", file=sys.stderr); failed += len(items); continue
        changes, undo = {}, []
        for field, old, new in items:
            now = cur.get(field, [])
            if now == new:
                continue
            if now != old and not force:
                print(f"SKIP (changed since scan) {path} [{field}] now={now} expected={old}", file=sys.stderr)
                skipped += 1
                continue
            changes[field] = new
            undo.append({"path": path, "field": field, "before": now, "after": new})
        if not changes:
            continue
        if not apply:
            for u in undo:
                print(f"{path}\n    {u['field']}: {u['before']}  ->  {u['after']}")
            done += len(changes)
            continue
        try:
            for u in undo:                       # log first, so an interrupted run can still be undone
                log.write(json.dumps(u, ensure_ascii=False) + "\n")
            log.flush()
            write_tags(path, changes, id3_version=id3_version)
            done += len(changes)
            written.append(path)
        except Exception as exc:
            print(f"ERROR writing {path}: {exc}", file=sys.stderr)
            failed += len(changes)
    if log:
        log.close()
    if written and db_path:
        refresh_cache(db_path, written)
    verb = "Applied" if apply else "Would apply"
    print(f"\n{verb} {done} field changes in {len(written) if apply else len(plan)} files; "
          f"skipped {skipped}; failed {failed}.", file=sys.stderr)
    if interrupted:
        print(f"Interrupted after {len(written) if apply else done} of {len(plan)} files "
              "(stopped between files, none left half-written).", file=sys.stderr)
    if apply:
        print(f"Undo log: {log_path}", file=sys.stderr)
    else:
        print("Dry run only. Add --apply to write.", file=sys.stderr)
    return EXIT_INTERRUPTED if interrupted else 0


def main():
    # Windows consoles default to cp1252/cp850 and choke on e.g. Cyrillic tags; never crash on output.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="changes.csv from propose_changes.py")
    ap.add_argument("--apply", action="store_true", help="really write (default is a dry run)")
    ap.add_argument("--undo", metavar="LOG", help="restore values from an undo_*.jsonl log")
    ap.add_argument("--all", action="store_true", help="apply every row of the CSV, whatever its approve column says")
    ap.add_argument("--force", action="store_true", help="write even if the file changed since the scan")
    ap.add_argument("--schema", default="schema.toml", help="for the id3_version setting")
    ap.add_argument("--db", default="tags.sqlite", help="cache to refresh after writing")
    ap.add_argument("--limit", type=int, help="only the first N files (useful for a first test)")
    args = ap.parse_args()
    handle_interrupts()

    try:
        id3v = int(load_config(args.schema).get("general", {}).get("id3_version", 4))
    except FileNotFoundError:
        id3v = 4
    stamp = time.strftime("%Y%m%d_%H%M%S")
    plan = defaultdict(list)

    if args.undo:
        with open(args.undo, encoding="utf-8") as fh:
            entries = [json.loads(l) for l in fh if l.strip()]
        for e in reversed(entries):
            plan[e["path"]].append((e["field"], e["after"], e["before"]))
        log_path = f"undo_{stamp}_of_{args.undo.rsplit('/', 1)[-1]}"
    elif args.csv:
        with open(args.csv, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if args.all or r["approve"].strip().lower() in YES:
                    plan[r["path"]].append((r["field"], split_list(r["old"]), split_list(r["new"])))
        log_path = f"undo_{stamp}.jsonl"
    else:
        ap.error("give a changes.csv or --undo LOG")

    if args.limit:
        plan = dict(list(plan.items())[: args.limit])
    return run(plan, args.apply, args.force, id3v, log_path, args.db)


if __name__ == "__main__":
    sys.exit(main())
