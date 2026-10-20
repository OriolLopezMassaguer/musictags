# musictags — re-tag a music library with a consistent schema

Four Python scripts. Nothing touches your files until step 4 with `--apply`, and every write can be undone.

| Step | Script | Reads | Writes |
|---|---|---|---|
| 1 | `scan_tags.py LIBRARY` | your files | `tags.sqlite` (+ `--csv tags.csv`) |
| 2 | `analyze_tags.py` | `tags.sqlite` | `report.md`, `schema.proposed.toml` |
| 3 | `propose_changes.py` | `tags.sqlite`, `schema.toml` | `changes.csv` |
| 4 | `apply_changes.py changes.csv --apply` | `changes.csv` | your files + `undo_*.jsonl` |

The schema itself is described in [SCHEMA.md](SCHEMA.md).

## Install

Python 3.9+ and [mutagen](https://mutagen.readthedocs.io):

```
pip install -r requirements.txt
```

Supported: MP3 (ID3v2), FLAC, Ogg Vorbis, Opus, M4A/MP4. Other files are skipped.

### On the Synology NAS (Docker, recommended)

Copy this folder to e.g. `/volume1/docker/musictags`, then over SSH:

```
docker run --rm -it -v /volume1/music:/music -v /volume1/docker/musictags:/work -w /work \
  python:3.12-slim sh -c "pip install -q mutagen && python scan_tags.py /music"
```

Use the same command with the other scripts. Alternatively run everything from a PC with the
music share mounted (SMB/NFS): pass the mounted path to `scan_tags.py`. Note: paths in
`changes.csv` are the paths seen by the machine that scanned, so scan and apply from the same place.

## Workflow

One shell script per step. The library path (`/volume1/musica/Music server/iTunes`) is set in
`config.sh`. Extra arguments are passed through to the Python script.

```
./1_scan.sh                       # 1. -> tags.sqlite, tags.csv (later runs only re-read changed files; --full for all)
./2_analyze.sh                    # 2. -> report.md, schema.proposed.toml
cp schema.proposed.toml schema.toml   #    ...edit: unmapped genres, aliases, keep_together
./3_propose.sh                    # 3. -> changes.csv  (review in LibreOffice/Excel)
./4_apply.sh                      # 4a. dry run
./4_apply.sh --apply --limit 20   # 4b. try on 20 files, check in your player
./4_apply.sh --apply              # 4c. everything
./5_undo.sh undo_20261020_140000.jsonl --apply   # if needed
```

Iterate: edit `schema.toml` → `propose_changes.py` → apply. You can also work by field or folder:
`propose_changes.py --only genre,style` or `--path /music/Classical`.

### Reviewing changes.csv

Columns: `approve, confidence, rule, path, field, old, new`. Lists use ` || `.
- `approve = y` rows are applied. `high` and `medium` are pre-approved (`auto_approve` in the schema);
  `low` (guesses: inferred composer, parsed work/movement, unmapped genre kept) are left blank.
- You may edit `new` before applying.
- Save as CSV UTF-8. Excel: *Save As → CSV UTF-8*.

### Safety

- Dry run by default; `--limit N` for a trial.
- Before each write the file is re-read; if a field no longer equals `old` (changed since the
  scan) the change is skipped.
- Undo log is written *before* each file is modified.
- Only the managed fields (artists, album artist, sort tags, composer, conductor, ensemble,
  genre, style, work, movement, compilation) can be written. Titles, album, track numbers and
  cover art are never touched.
- MP3s are saved as ID3v2.4 (true multi-value). If an old player needs v2.3 set
  `id3_version = 3` (lists are then joined with `; `).
- Back up the library (or at least a test folder) before the first big run anyway.
