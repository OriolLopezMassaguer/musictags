# Architecture

## Modules

### Shared library

| Module | Lines | What is in it |
|---|---|---|
| `core.py` | ~475 | The canonical field set and its per-format mapping; `read_tags`/`write_tags` over mutagen; name, genre and sort normalisation; ~190 built-in classical composers with periods and spelling variants; the genre keyword taxonomy. |
| `rules.py` | ~102 | `CreditSplitter` (split `A & B feat. C`, honouring names that must stay whole), `Canon` (alias lookup), the default separator / feat / keep-together constants. |
| `album_names.py` | ~313 | Classical album naming: performer role classification (ensemble / conductor / soloist), 4-letter orchestra codes, work summarising and grouping, `build_name`. |

### Steps

| Module | Reads | Writes |
|---|---|---|
| `scan_tags.py` | your files | `tags.sqlite`, `tags.csv` |
| `analyze_tags.py` | `tags.sqlite` | `report.md`, `schema.proposed.toml` |
| `propose_changes.py` | `tags.sqlite`, `schema.toml` | `changes.csv` |
| `apply_changes.py` | `changes.csv` | your files, `undo_*.jsonl` |

### GUI

| Module | Lines | What is in it |
|---|---|---|
| `gui/schema_edit.py` | ~435 | The line-level TOML reader/writer. The foundation; everything else depends on it being exact. |
| `gui/schema_merge.py` | ~180 | Diffing and merging `schema.proposed.toml` into `schema.toml`. |
| `gui/changes.py` | ~270 | `changes.csv` in memory: grouping, facets, filters, saving. |
| `gui/runner.py` | ~295 | The step declarations, argv building with validation, and subprocess running with a live log. |
| `gui/state.py` | ~190 | Dashboard data: pipeline freshness, library stats, schema health. |
| `gui/app.py` | ~420 | Flask routes. Thin — the logic is in the modules above. |

The GUI **imports** `core`, `propose_changes.album_key` and `analyze_tags.split_genres`
rather than reimplementing them, so its grouping and its "looks classical" test are the
same ones the pipeline uses. It never modifies a pipeline module.

---

## Three decisions worth knowing

### The TOML editor is a line model, not an AST

`analyze_tags.py` emits the schema as a flat list of literal strings, and the comments
in it carry information that is not recoverable from the values: how many tracks a
genre has, which values an option accepts, and which entries are deliberately parked
under *NOT mapped: decide*. A normal load-and-dump cycle through a dict would lose all
of it.

So `SchemaFile` keeps every source line verbatim and re-renders **only** the lines that
were edited. A multi-line array is one node covering its whole block. A comment is
treated as a commented-out entry only when its key is quoted, which is what keeps
prose like `# raw genre (as found in your files) = [GENRE, optional STYLE]` from being
parsed as data.

Two independent tests guard this, and both are needed:

- re-dumping an untouched file is byte-identical — proves nothing is **lost**;
- `to_dict()` equals `tomli.load()` — proves the values are **understood**.

The first passes trivially for a line stored and never interpreted, which is how a real
bug hid: all 142 `keep_together` entries were parsed as prose and re-emitted perfectly.

### Merging is the feature, not copying

Step 2 has no merge logic and never will — it is a report generator. The decisions a
user makes live only in `schema.toml` and the README's answer was a manual `cp`, which
destroys them. `gui/schema_merge.py` is where that asymmetry is resolved, and its
default for every difference follows one rule: the analysis knows what is **in the
library**, the user knows what the values should **be**.

### The album is the unit of review

`changes.csv` is one row per (file, field) — tens of thousands of them — but the
decisions a human makes are per album: this album's new name, this album's artist. So
the review groups rows with `propose_changes.album_key()`, the proposer's own function,
rather than a lookalike. Resolve the album title **per file** before grouping, not per
row: only the `album` rows carry the old name, so a per-row fallback scatters one
file's rows across different groups.

---

## Invariants

Anything added here has to keep these true.

1. **The pipeline scripts are not modified by the GUI.** `./1_scan.sh` … `./5_undo.sh`
   keep working, unchanged, at every point.
2. **File formats do not change.** `changes.csv` keeps its eight columns, its BOM and
   its `" || "` lists; `schema.toml` keeps its comments.
3. **Only `WRITABLE` fields reach your music.** `core.write_tags` raises on anything
   else, so titles, track numbers, dates and artwork cannot be written even by mistake.
4. **Dry run is the default.** Writing requires an explicit flag on the CLI and an
   explicit confirmation token in the API.
5. **Re-read before write.** If a field no longer matches `old`, the row is skipped
   rather than clobbered.
6. **Undo first.** The undo entry is flushed before the file it describes is touched.
7. **Nothing is overwritten without a `.bak`**, and a schema that would not re-parse is
   not written at all.

## Adding things

**A new step flag** — add it to the step's `args` in `gui/runner.py:STEPS` and to the
script's `argparse`. The form control, the argv and the validation all follow from the
declaration; no template change.

**A new schema section** — it appears in the editor automatically. Add a line to
`SECTION_HELP` in `gui/app.py`, and to `MAP_SECTIONS` in `gui/schema_merge.py` if its
keys are data rather than options.

**A new page** — a route in `gui/app.py` and a template extending `base.html`. The nav,
the log drawer and the step forms come from the base template and `_step.html`.

## Environment

Python 3.10 on the NAS, so `tomllib` does not exist and `tomli` is used instead
(`core.py` falls back automatically). `tkinter` is not available, which is part of why
the GUI is a web app. Runtime dependencies: `mutagen` and `tomli` for the pipeline,
plus `flask` and `markdown` for the GUI only.
