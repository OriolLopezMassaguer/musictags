# musictags — re-tag a music library with a consistent schema

Four Python scripts and a web GUI. Nothing touches your files until step 4 is given
`--apply`, and every write can be undone.

| Step | Script | Reads | Writes |
|---|---|---|---|
| 1 | `scan_tags.py LIBRARY` | your files | `tags.sqlite` (+ `--csv tags.csv`) |
| 2 | `analyze_tags.py` | `tags.sqlite` | `report.md`, `schema.proposed.toml` |
| 3 | `propose_changes.py` | `tags.sqlite`, `schema.toml` | `changes.csv` |
| 4 | `apply_changes.py changes.csv --apply` | `changes.csv` | your files + `undo_*.jsonl` |

Wrappers: `1_scan.sh` … `5_undo.sh` for the steps, `0_all.sh` to run steps 1-4 back to
back (step 4 as a dry run), `gui.sh` / `gui-local.sh` to serve the web interface, and
`tunnel.ps1` to reach it from a Windows machine over SSH. The GUI has the same chain
behind its *Todo seguido* button.

Every step can be stopped with Ctrl-C (or the GUI's *Parar*) and stops at a point where
stopping is safe — never in the middle of writing a file. See *Stopping a run* below.

Classical albums are renamed to `Composer - works (soloist | ORCH / conductor)`, e.g.
`Beethoven - Symphonies Nos. 5 & 7 (BPhO / Herbert von Karajan)`, and get a hierarchical
`GENRE` such as `Clásica\Orquestal\Sinfonias`, so a player that browses by genre only still
shows a tree instead of one flat `Classical` (see *Classical genre tree* in [SCHEMA.md](SCHEMA.md)).

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

Or all of 1-4 in one go, stopping at the first failure (step 4 stays a dry run, so
nothing is written to your files):

```
./0_all.sh                        # scan, analyze, propose, dry-run apply
./0_all.sh --skip-scan            # start at step 2 if the library has not changed
```

Then iterate: edit `schema.toml` → re-propose → review → apply. You can narrow the work
down with `./3_propose.sh --only genre,style` or `--path "/music/Classical"` (give it whole
albums: the classical genre is voted per album).

The first time, read the **Classical genre tree** section of `report.md`: it lists the
`Clásica\…` genres you already have next to the built-in standard tree and says where they
differ. *Fusionar* then brings `[classical_genres]` and `[classical_rules]` into `schema.toml`.

> **Do not `cp schema.proposed.toml schema.toml`.** Step 2 regenerates the proposal from
> scratch every run, so copying it over discards every decision you made by hand —
> mapped genres, orchestra codes, aliases, `keep_together`. Use the GUI's *Fusionar*
> page, which merges the two and keeps your edits, or diff them yourself.

## Stopping a run

Ctrl-C, or *Parar* in the GUI (which sends the same signal), asks the running script to
stop; it finishes what it has in hand and then exits with code **130**. Signalling a
second time kills it outright, which should only ever be needed if it is wedged.

What "a safe point" means per step:

| Step | Stops | What survives |
|---|---|---|
| 1 scan | after the file being read | every file read so far is committed; run it again and it continues from there |
| 2 analyze | between sections | nothing is written, so `report.md` and `schema.proposed.toml` stay as they were |
| 3 propose | between tracks | the CSV is built as `changes.csv.part` and renamed only when finished, so the previous `changes.csv` is untouched |
| 4 apply | **between files, never inside a write** | no file is left half-tagged, and the `undo_*.jsonl` already covers everything written before the stop |

`0_all.sh` and the GUI chain both stop at the step that was interrupted and skip the
rest.

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
| **Cambios** | Review `changes.csv` grouped by album; filter, bulk-approve, edit a proposed value. Writes back only the `approve` and `new` columns, so `./4_apply.sh` still works. Each album card shows the proposed album name and genre path; the `genre-tree` rule filter lists just those. |
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

Tests (from the project root; the GUI ones need `flask`, `markdown` and `tomli` installed):

```
python3 -m unittest discover tests -t .        # genre tree, proposer, analyzer (no music files touched)
python3 -m unittest discover gui/tests -t .    # schema editor, merge, changes.csv, schema page
```

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
- Like `[album]`, the classical genre tree is opt-in through the schema: without
  `[classical_genres]` (or with `enabled = false`) classical tracks keep `GENRE = Classical`.
  Step 3 prints a note when the section is missing and the GUI's Panel flags it.
- MP3s are saved as ID3v2.4 (true multi-value frames). For an old player that needs
  v2.3, set `id3_version = 3`; lists are then joined with `"; "`.
- Back up the library, or at least a test folder, before the first big run anyway.

## Running it elsewhere

Paths in `changes.csv` are the paths seen by the machine that scanned, so scan and apply
from the same place. Docker on the NAS, or a PC with the share mounted, both work — see
[docs/PIPELINE.md](docs/PIPELINE.md#running-it-somewhere-else).
