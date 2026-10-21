# musictags — re-tag a music library with a consistent schema

Four Python scripts and a web GUI. Nothing touches your files until step 4 is given
`--apply`, and every write can be undone.

| Step | Script | Reads | Writes |
|---|---|---|---|
| 1 | `scan_tags.py LIBRARY` | your files | `tags.sqlite` (+ `--csv tags.csv`) |
| 2 | `analyze_tags.py` | `tags.sqlite` | `report.md`, `schema.proposed.toml` |
| 3 | `propose_changes.py` | `tags.sqlite`, `schema.toml` | `changes.csv` |
| 4 | `apply_changes.py changes.csv --apply` | `changes.csv` | your files + `undo_*.jsonl` |

Wrappers: `1_scan.sh` … `5_undo.sh` for the steps, `gui.sh` / `gui-local.sh` to serve the
web interface, and `tunnel.ps1` to reach it from a Windows machine over SSH.

Classical albums are renamed to `Composer - works (soloist | ORCH / conductor)`, e.g.
`Beethoven - Symphonies Nos. 5 & 7 (BPhO / Herbert von Karajan)`.

## Documentation

| | |
|---|---|
| **[SCHEMA.md](SCHEMA.md)** | The tagging schema: which tag holds what, and every rule. Start here to understand *what* the tool does to your library. |
| **[docs/PIPELINE.md](docs/PIPELINE.md)** | The steps in detail — every flag, every intermediate file format, and the safety model. |
| **[docs/GUI.md](docs/GUI.md)** | The web interface: each page, how to reach it from another machine, the HTTP API. |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Module map, the design decisions behind it, and the invariants to keep. |

## Install

Python 3.9+ and [mutagen](https://mutagen.readthedocs.io):

```
pip install --user -r requirements.txt
```

Supported: MP3 (ID3v2), FLAC, Ogg Vorbis, Opus, M4A/MP4. Other files are skipped.
`flask` and `markdown` are in there too, but only the GUI needs them.

## Workflow

One shell script per step. The library path is set in `config.sh`. Extra arguments are
passed straight through to the Python script.

```
./1_scan.sh                       # 1. -> tags.sqlite, tags.csv  (--full to re-read everything)
./2_analyze.sh                    # 2. -> report.md, schema.proposed.toml
                                  #    ...now merge the proposal into schema.toml
./3_propose.sh                    # 3. -> changes.csv
./4_apply.sh                      # 4a. dry run
./4_apply.sh --apply --limit 20   # 4b. try 20 files, check them in your player
./4_apply.sh --apply              # 4c. everything
./5_undo.sh undo_20261020_140000.jsonl --apply   # if needed
```

Then iterate: edit `schema.toml` → re-propose → review → apply. You can narrow the work
down with `./3_propose.sh --only genre,style` or `--path "/music/Classical"`.

> **Do not `cp schema.proposed.toml schema.toml`.** Step 2 regenerates the proposal from
> scratch every run, so copying it over discards every decision you made by hand —
> mapped genres, orchestra codes, aliases, `keep_together`. Use the GUI's *Fusionar*
> page, which merges the two and keeps your edits, or diff them yourself.

## GUI

```
./gui.sh                      # -> http://<nas-ip>:8765
./gui.sh --token secreto      # require ?t=secreto
```

| Page | What it is for |
|---|---|
| **Panel** | State of every step, whether an output is stale, library stats, and the run buttons with each script's flags as controls. |
| **Fusionar** | Merge `schema.proposed.toml` into `schema.toml` difference by difference. Adds what is new, keeps what you changed. |
| **Esquema** | Edit `schema.toml` as forms and searchable tables. Only the lines you change are rewritten — comments and track counts stay. |
| **Cambios** | Review `changes.csv` grouped by album; filter, bulk-approve, edit a proposed value. Writes back only the `approve` and `new` columns, so `./4_apply.sh` still works. |
| **Informe** | `report.md` rendered, with a section index. |

The GUI runs the same scripts as subprocesses and shows their output live; it never
reimplements them. Writing to your music is a separate red button behind a confirmation
— the plain one is a dry run.

### Reaching it from another machine

If the page does not open from your laptop, the port is being filtered by the DSM
firewall, not closed — the server does bind every interface. The safest answer is not
to open the port at all but to tunnel, which is what these two scripts are for:

```
./gui-local.sh      # on the NAS: listen on 127.0.0.1 only
.\tunnel.ps1 -Start # on the Windows laptop: SSH tunnel + browser, starting it if needed
```

`tunnel.ps1` takes `-NasHost`, `-User`, `-Port`, `-LocalPort`, `-Token`, `-NoBrowser`;
`Get-Help .\tunnel.ps1 -Full` explains them. The alternatives — opening TCP 8765 in the
DSM firewall, or a DSM reverse proxy — are in
[docs/GUI.md](docs/GUI.md#giving-another-machine-access).

Tests: `python3 -m unittest discover gui/tests -t .`

## Reviewing changes.csv by hand

Columns: `id, approve, confidence, rule, path, field, old, new`. Lists use `" || "`.

- `approve = y` rows are applied. `high` and `medium` are pre-approved
  (`auto_approve` in the schema); `low` ones — inferred composer, work/movement parsed
  out of a title, unmapped genre kept — are left blank for you.
- You may edit `new` before applying.
- Save as **CSV UTF-8** or the accents break. Excel: *Save As → CSV UTF-8*.

## Safety

- Dry run by default; `--limit N` for a trial.
- Before each write the file is re-read; if a field no longer equals `old` — it changed
  since the scan — the row is skipped rather than clobbered.
- The undo log is written *before* each file is modified.
- Only the managed fields can be written: artists, album artist, sort tags, composer,
  conductor, ensemble, genre, style, work, movement, compilation, and ALBUM for
  classical albums. Titles, track numbers, dates and cover art are never touched, and
  `core.write_tags` raises if anything tries.
- Classical album renaming needs `[album] enabled` in the schema. A `schema.toml`
  written before that feature has no `[album]` section at all and step 3 then skips the
  renaming **silently** — the GUI's Panel flags this; from the terminal, check with
  `grep '^\[album\]' schema.toml`.
- MP3s are saved as ID3v2.4 (true multi-value frames). For an old player that needs
  v2.3, set `id3_version = 3`; lists are then joined with `"; "`.
- Back up the library, or at least a test folder, before the first big run anyway.

## Running it elsewhere

Paths in `changes.csv` are the paths seen by the machine that scanned, so scan and apply
from the same place. Docker on the NAS, or a PC with the share mounted, both work — see
[docs/PIPELINE.md](docs/PIPELINE.md#running-it-somewhere-else).
