#!/usr/bin/env python3
"""
Step 1 - scan_tags.py: read the current tags of every audio file into a SQLite cache.

    python scan_tags.py /volume1/music                 # -> tags.sqlite
    python scan_tags.py /volume1/music --csv tags.csv  # also export a flat CSV
    python scan_tags.py /volume1/music --full          # ignore cache, re-read everything

Incremental: files whose size and mtime did not change are not re-read.
Files that disappeared from disk are dropped from the cache.

Ctrl-C (or the GUI's "Parar") stops after the file being read: everything read so
far is committed, and running it again picks up where it left off.
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from core import (EXIT_INTERRUPTED, FIELDS, LIST_SEP, handle_interrupts,
                  iter_audio_files, read_tags, stopping)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path   TEXT PRIMARY KEY,
    mtime  REAL, size INTEGER,
    format TEXT, tags TEXT, error TEXT,
    scanned REAL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def read_one(path):
    try:
        st = os.stat(path)
        fmt, tags = read_tags(path)
        return path, st.st_mtime, st.st_size, fmt, json.dumps(tags, ensure_ascii=False), None
    except Exception as exc:  # corrupt file, permission problem...
        try:
            st = os.stat(path); m, s = st.st_mtime, st.st_size
        except OSError:
            m = s = None
        return path, m, s, None, None, f"{type(exc).__name__}: {exc}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", help="music library root folder")
    ap.add_argument("--db", default="tags.sqlite")
    ap.add_argument("--csv", help="also export all tags to this CSV file")
    ap.add_argument("--workers", type=int, default=8, help="parallel readers (I/O bound)")
    ap.add_argument("--full", action="store_true", help="re-read every file")
    args = ap.parse_args()
    handle_interrupts()

    root = os.path.abspath(args.root)
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)
    db.execute("INSERT OR REPLACE INTO meta VALUES ('root', ?)", (root,))
    cached = {} if args.full else {
        p: (m, s) for p, m, s in db.execute("SELECT path, mtime, size FROM files WHERE error IS NULL")}

    print(f"Listing files under {root} ...", file=sys.stderr)
    paths = []
    for p in iter_audio_files(root):
        if stopping():
            print("Stopped while listing: nothing read.", file=sys.stderr)
            return EXIT_INTERRUPTED
        paths.append(p)
    todo = []
    for p in paths:
        c = cached.get(p)
        if c:
            try:
                st = os.stat(p)
                if c == (st.st_mtime, st.st_size):
                    continue
            except OSError:
                pass
        todo.append(p)
    print(f"{len(paths)} audio files, {len(todo)} to (re)read", file=sys.stderr)

    t0, done, errors, interrupted = time.time(), 0, 0, False
    pool = ThreadPoolExecutor(max_workers=args.workers)
    try:
        for row in pool.map(read_one, todo):
            db.execute("INSERT OR REPLACE INTO files VALUES (?,?,?,?,?,?,?)", (*row, time.time()))
            done += 1
            errors += row[5] is not None
            if done % 500 == 0:
                db.commit()
                rate = done / (time.time() - t0)
                print(f"  {done}/{len(todo)}  ({rate:.0f} files/s)", file=sys.stderr)
            if stopping():
                interrupted = True
                break
    finally:
        # pool.map queued every file up front; drop the ones not started yet.
        pool.shutdown(wait=True, cancel_futures=True)
        db.commit()

    if interrupted:
        # The stale-entry sweep and the CSV would both describe a partial scan.
        print(f"Interrupted: {done} of {len(todo)} files read and saved to {args.db} "
              f"({errors} errors). Run it again to carry on.", file=sys.stderr)
        return EXIT_INTERRUPTED

    present = set(paths)
    gone = [p for (p,) in db.execute("SELECT path FROM files") if p not in present]
    db.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in gone])
    db.commit()
    print(f"Done: read {done} files ({errors} errors), removed {len(gone)} stale entries -> {args.db}",
          file=sys.stderr)

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["path", "format", *FIELDS, "error"])
            for path, fmt, tags, err in db.execute("SELECT path, format, tags, error FROM files ORDER BY path"):
                t = json.loads(tags) if tags else {}
                w.writerow([path, fmt, *[LIST_SEP.join(t.get(f, [])) for f in FIELDS], err or ""])
        print(f"Exported {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
