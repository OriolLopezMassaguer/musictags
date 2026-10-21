# The pipeline

Four scripts plus an undo. Each one is a stateless CLI: it reads named files, writes
named files, and keeps no state of its own. That is what makes them safe to re-run and
easy to wrap (the GUI runs these very scripts as subprocesses).

```
  your files ──1 scan──▶ tags.sqlite ──2 analyze──▶ report.md
                              │                      schema.proposed.toml
                              │                             │
                              │                        (3 merge/edit)
                              │                             ▼
                              └────────3 propose──────▶ schema.toml
                                            │
                                            ▼
                                       changes.csv ──4 apply──▶ your files
                                                                undo_*.jsonl
                                                                     │
                                                                5 undo ◀┘
```

Nothing touches your music until step 4 is given `--apply`.

---

## config.sh

Sourced by every `N_*.sh` wrapper. It `cd`s into the repo, so all the relative
filenames below resolve next to the scripts, and it aborts early if mutagen is missing.

```sh
MUSIC_DIR="/volume1/musica/Music server/iTunes"
PYTHON="${PYTHON:-python3}"
```

`PYTHON` is the only environment variable the project reads.

---

## Step 1 — scan

```
./1_scan.sh [extra args]
python3 scan_tags.py LIBRARY --csv tags.csv
```

Walks the library, reads every tag into `tags.sqlite`, optionally exports `tags.csv`.

| Flag | Default | What it does |
|---|---|---|
| `LIBRARY` | from `config.sh` | positional; the folder to walk |
| `--db` | `tags.sqlite` | cache file |
| `--csv` | *(off)* | also export every tag to this CSV |
| `--workers` | `8` | parallel readers; the work is I/O bound, not CPU |
| `--full` | off | re-read every file instead of only the changed ones |

Incremental by `(mtime, size)`: a second run only re-reads what changed, and rows for
files that have disappeared are deleted. Skips dot-directories, `@eaDir`, `#recycle`
and `._` resource forks. Extensions read: `.mp3 .flac .ogg .oga .opus .m4a .mp4 .m4b`.

Progress goes to **stderr** every 500 files; the summary goes to stdout. Anything
wrapping this must merge both streams or the progress disappears.

## Step 2 — analyze

```
./2_analyze.sh            # the wrapper hardcodes --fuzzy
python3 analyze_tags.py --fuzzy
```

Reads the cache and writes two files. It never reads `schema.toml` and never modifies
anything else.

| Flag | Default | What it does |
|---|---|---|
| `--db` | `tags.sqlite` | cache to read |
| `--report` | `report.md` | the human-readable analysis |
| `--out` | `schema.proposed.toml` | a schema built from *your* tags |
| `--fuzzy` | off (on in the wrapper) | find near-duplicate names (ratio ≥ 0.9, keys ≥ 6 chars) |
| `--min-band` | `2` | an `A & B` credit whose parts never appear alone is kept together if it is used on at least this many tracks |

`report.md` sections: field usage, albums, separators found inside single values, names
spelled several ways, possible typos, composers, genres, performers, ambiguous
multi-artist credits.

**The thing to know:** `schema.proposed.toml` is rewritten *wholesale* every run. There
is no merge logic. Copying it over `schema.toml` throws away every decision you made by
hand. Use the GUI's *Fusionar* page, or diff the two files yourself.

## Step 3 — propose

```
./3_propose.sh [extra args]
python3 propose_changes.py
```

Compares the cache against `schema.toml` and writes one row per (file, field) that
should change.

| Flag | Default | What it does |
|---|---|---|
| `--db` | `tags.sqlite` | cache to read |
| `--schema` | `schema.toml` | the rules |
| `--out` | `changes.csv` | proposals |
| `--only` | all | comma-separated fields, e.g. `genre,style` |
| `--path` | all | only files under this folder |

Three phases, in order: per-track proposals, then album-wide ones (album artist,
compilation flag), then classical album names. Each later phase sees the earlier
phases' proposals, so an album name is built from already-canonicalised composers.

Stdout prints the totals, the split by confidence, and a count per rule family.

## Step 4 — apply

```
./4_apply.sh                      # dry run
./4_apply.sh --apply --limit 20   # a real but small first run
./4_apply.sh --apply              # everything
```

| Flag | Default | What it does |
|---|---|---|
| `csv` | `changes.csv` | positional |
| `--apply` | off | actually write; **without it nothing is touched** |
| `--limit` | all | only the first N files |
| `--force` | off | write even if the file changed since the scan |
| `--schema` | `schema.toml` | only for the `id3_version` setting |
| `--db` | `tags.sqlite` | cache rows are refreshed after writing |
| `--undo LOG` | — | restore from an undo log instead (step 5) |

Rows count as approved when `approve` is one of `y yes x 1 true si sí`.

Safety, in the order it happens:
1. the file is re-read; if the field no longer equals `old`, the row is **skipped**
   (unless `--force`) — so a file edited elsewhere since the scan is never clobbered;
2. the undo entry is appended **before** the file is modified;
3. only `WRITABLE` fields can be written; `core.write_tags` raises on anything else, so
   titles, track numbers, dates and cover art cannot be touched even by mistake;
4. the sqlite cache rows are refreshed in place.

## Step 5 — undo

```
./5_undo.sh undo_20261020_140000.jsonl            # dry run
./5_undo.sh undo_20261020_140000.jsonl --apply
```

Replays the log backwards, swapping `after` back to `before`. Undoing an undo produces
`undo_<stamp>_of_<original>.jsonl`.

---

# Data formats

## tags.sqlite

```sql
CREATE TABLE files (
    path   TEXT PRIMARY KEY,
    mtime  REAL, size INTEGER,
    format TEXT,            -- 'id3' | 'mp4' | 'vorbis'
    tags   TEXT,            -- JSON {field: [values]}, non-empty fields only
    error  TEXT,
    scanned REAL
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);   -- holds 'root'
```

## tags.csv

UTF-8 **with BOM** (`utf-8-sig`), so Excel opens it correctly. Header is
`path, format,` the 19 fields of `core.FIELD_MAP` in order, `error`. Multi-valued
fields are joined with `" || "` (`core.LIST_SEP`).

## changes.csv

UTF-8 with BOM. Columns, in this exact order:

```
id, approve, confidence, rule, path, field, old, new
```

- `id` — row number; `apply_changes.py` reads the file with `DictReader` and ignores it.
- `approve` — `y` for rows whose confidence is listed in `[general] auto_approve`
  (`high` and `medium` by default); blank otherwise. **This is the only column you are
  expected to change**, besides `new`.
- `confidence` — `high`, `medium` or `low`. `low` means a guess: an inferred composer,
  a work/movement parsed out of a title, an unmapped genre kept as-is, or a classical
  album name built from track titles rather than from WORK tags.
- `rule` — why, as `<family>: <detail>`. The text before the colon is the rule family
  the GUI filters on.
- `old` / `new` — current and proposed values, lists joined with `" || "`.

If you edit it in a spreadsheet, save as **CSV UTF-8** or the accents break.

## undo_YYYYmmdd_HHMMSS.jsonl

One JSON object per line, appended before each write:

```json
{"path": "...", "field": "composer", "before": ["Chopin"], "after": ["Frédéric Chopin"]}
```

---

## Running it somewhere else

Paths in `changes.csv` are the paths seen by the machine that scanned, so **scan and
apply from the same place**. To run from a PC with the share mounted, pass the mounted
path to `scan_tags.py` and do everything from there. To run in Docker on the NAS:

```
docker run --rm -it -v /volume1/music:/music -v /volume1/docker/musictags:/work -w /work \
  python:3.12-slim sh -c "pip install -q mutagen && python scan_tags.py /music"
```

See also: [SCHEMA.md](../SCHEMA.md) for the tagging rules, [GUI.md](GUI.md) for the web
interface, [ARCHITECTURE.md](ARCHITECTURE.md) for the module map.
