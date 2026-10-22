# The GUI

A browser front end for the four steps, meant to be opened from another machine on the
LAN. It **wraps** the pipeline — it runs the same scripts as subprocesses and reads and
writes the same files, in the same formats. Everything you do in the browser is still
visible, and still fixable, from the terminal.

```
pip install --user -r requirements.txt    # adds flask + markdown
./gui.sh                                  # -> http://<nas-ip>:8765
```

The UI is in Spanish; this document names each page as the UI does.

---

## Starting and stopping

```
./gui.sh                      # 0.0.0.0:8765 -- the whole LAN, if the firewall allows it
./gui-local.sh                # 127.0.0.1 only -- use with the SSH tunnel below
./gui.sh --port 9000
./gui.sh --token secreto      # require ?t=secreto; --token with no value generates one
./gui.sh --debug              # Flask reloader; do not leave this on
```

On start it prints every LAN address it answers on. To survive logging out:

```
nohup ./gui.sh > gui.log 2>&1 &
pkill -f "[g]ui[.]app"        # stop it
```

The brackets matter: `pkill -f "gui.app"` also matches the shell you typed it in and
kills your own session.

## Giving another machine access

The server binds `0.0.0.0`, so if the page does not open from your laptop the port is
being filtered, not closed. Three ways round it, best first:

**1. SSH tunnel — nothing to configure, and nothing exposed.** This is the right
default for a service that can rewrite your music library and has no login. Two scripts
in the repo do it for you.

On the NAS, bind the GUI to loopback only:

```
./gui-local.sh                 # = ./gui.sh --host 127.0.0.1
./gui-local.sh --port 9000     # extra arguments pass through
```

On the Windows laptop, from a copy of the repo (or just the one file):

```powershell
.\tunnel.ps1                   # tunnel + browser, against a GUI already running
.\tunnel.ps1 -Start            # also start it on the NAS if it is not up
.\tunnel.ps1 -NasHost 192.168.1.3 -User oriol -LocalPort 9000 -Token secreto
```

`tunnel.ps1` checks that `ssh.exe` exists and that the local port is free, optionally
starts the remote GUI, opens `ssh -N -L`, waits for the tunnel to answer, opens the
browser, and tears the tunnel down on Ctrl+C. If `ssh` dies immediately — wrong user,
SSH disabled in DSM — it says so instead of hanging. `-Start` detects whether the GUI
is up by checking the **port**, not the process: this NAS has no `pgrep`, and the port
is the thing you actually care about.

By hand it is just:

```
ssh -L 8765:127.0.0.1:8765 <user>@<nas-ip>
```

then open <http://localhost:8765>.

**2. Open the port in DSM.** *Panel de control → Seguridad → Cortafuegos → Editar
reglas → Crear*: Puertos → Personalizado → **TCP 8765**, IP de origen → Subred
`192.168.1.0/24`, acción **Permitir**. The rule must sit **above** any deny-all rule;
DSM applies them top to bottom. Add `--token` as well, since the rule lets the whole
subnet in.

**3. DSM reverse proxy**, if 443 is already allowed and you would rather not open
another port: *Panel de control → Portal de inicio de sesión → Avanzado → Proxy
inverso*, origin `https://nas:443` with a hostname, destination
`http://localhost:8765`. You get TLS and DSM's own access controls for free.

## Security model

There is no login. Anyone who can reach the port can rewrite the tags of your library.
That is acceptable behind an SSH tunnel or a subnet-scoped firewall rule, and not
acceptable on an open network. `--token` is a shared secret in the query string
(`?t=…`, then kept in a cookie) — enough to stop a curious device on the same LAN, not
a substitute for not exposing the port.

Guards that are always on:

- `--path` on the propose step is resolved and must stay inside `MUSIC_DIR`;
- the undo log name must be one of the `undo_*.jsonl` files actually present;
- numeric flags are range-checked;
- only one job runs at a time;
- writing to your files needs an explicit confirmation token in the request, so a
  stray GET or a mistyped URL cannot start an apply.

---

## The pages

### Panel

The state of the whole thing in one screen.

- **Schema health**, in red at the top: sections missing from `schema.toml`, `[album]
  enabled = false`, genres still undecided in `[genre_map]`, and iTunes role-soup
  entries in `keep_together` (`"… , Associated Performer, Violin, Main Artist - …"`).
  This exists because a `schema.toml` written before the classical-album feature simply
  has no `[album]` section, and step 3 then skips album renaming **without saying so**.
  The classical genre tree is checked the same way: a missing or disabled
  `[classical_genres]`, an empty `[classical_rules]`, and every problem the tree itself
  reports (a node name containing `/ ; , |`, two nodes that differ only by accents or case,
  a rule that is not a concept).
- **Library stats** from `tags.sqlite`: tracks, albums (CD1/CD2 counted as one), how
  much of the library looks classical, formats, total size.
- **Per-step cards**: whether the output exists, when it was written, and whether it is
  **stale** — its output is older than one of its inputs, e.g. `changes.csv` older than
  the `schema.toml` you just edited. That is the mistake the terminal workflow makes
  easy and nothing else catches.
- **Field coverage**: what share of tracks has each tag today. The fields at 0 % are
  exactly the ones the pipeline fills.
- Every step's flags as real controls, and the buttons to run it.
- **Todo seguido**, the card above the steps: runs 1 → 2 → 3 → 4 back to back, taking
  each step's options from that step's own form further down the page, and stops at the
  first step that fails. Step 4 runs as a **dry run**: the chain never writes to your
  music files, because writing is the one action that should stay a deliberate, confirmed
  click. `./0_all.sh` is the same chain from a terminal.

### Fusionar

Replaces `cp schema.proposed.toml schema.toml`. Step 2 rewrites the proposal from
scratch every run, so copying it over your schema throws away everything you decided by
hand. This page resolves the two files difference by difference.

One rule decides the defaults: **the analysis knows what is in the library, you know
what the values should be.**

| Difference | Default |
|---|---|
| A section you do not have (`[album]`, `[orchestra_abbrev]`, `[classical_genres]`) | add it, comments and all |
| A new option | add it |
| A new map entry (a genre, orchestra or alias new to the library; a new node of `[classical_rules]`) | add it |
| A value you changed by hand (a node's rule list included) | keep yours |
| An entry that no longer appears in the library | keep it, flagged as orphaned |

List options (`keep_together`, `taxonomy`, the separators) get a third choice, *unir las
dos*, and show what each side would add or remove — that is how you swap 142 scraped
`keep_together` entries for 55 clean ones while seeing exactly which ones go.

Writes through the same comment-preserving writer as the schema editor, and always
leaves a `.bak`.

### Esquema

`schema.toml` as forms and tables. **Only the lines you change are rewritten**: the
comments, the ordering, the alignment and the `# 85 tracks` counts all survive, because
those counts are what tell you whether a genre is worth deciding about.

- **Options** become typed controls. The allowed values are read out of the trailing
  comment, so `unmapped = "keep"  # "keep" | "drop" | "style"` renders as a dropdown
  with no extra configuration.
- **List options** become tag editors. `keep_together` gets a *quitar los créditos
  largos de iTunes* button for the scraped entries.
- **Map sections** (`genre_map`, `classical_rules`, `orchestra_abbrev`, `aliases`,
  `sort_overrides`) become searchable tables with inline edit, add and delete. In
  `classical_rules` the key is the whole genre path (`Clásica\Orquestal\Sinfonias`, typed
  with single backslashes) and the value is a JSON list of rules (`["symphony"]`, `[]` for a
  node that only receives albums by vote). The two options of `[classical_genres]`
  (`existing`, `no_match`) are dropdowns.
- **Commented-out entries** — the `# "Moderna" = ["?"]   # 85 tracks` lines that step 2
  writes under *NOT mapped: decide* — show as rows marked *sin decidir*. Giving one a
  value uncomments it **in place**, keeping its position and its track count.
- *Ver diff* shows the unified diff before you commit to it.

Saving validates the result by re-parsing it; if it is not valid TOML nothing is
written. A `.bak` is kept.

### Cambios

`changes.csv` — tens of thousands of rows over thousands of files — made reviewable.
Rows are grouped with the proposer's own `album_key()`, so the grouping matches what
step 3 thought, `CD1`/`Disc 2` collapsing included.

- **Por álbum** (the default, because most of a classical library is albums): one card
  per album with the proposed `ALBUM` rename old → new, the proposed album artist, the
  proposed classical `GENRE` path (old → new), track and change counts, and confidence
  badges. The rule filter has a `genre-tree` entry for just those rows. Approve or reject a whole album from
  the card; expand it for the per-track table.
- **Lista de filas**: the flat table, for working one field at a time.
- Filters on field, confidence, rule family and free text, plus *solo sin aprobar*.
  Bulk-approve the current filter.
- `new` is editable inline.

**Guardar** rewrites the file with only the `approve` and `new` columns changed —
verified by diffing column by column — so `./4_apply.sh` keeps working on it, and so
does a spreadsheet.

### Informe

`report.md` rendered, with an index of its sections. Read this before touching the
schema: unmapped genres, names spelled several ways, likely typos, and the performers
detected for classical album names.

---

## HTTP API

The pages are thin; this is the actual surface. All JSON.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/state` | pipeline freshness + current job |
| `POST` | `/api/run/<step>` | `{params, write, confirm}`; `write` needs `confirm: "APLICAR"` |
| `POST` | `/api/run-chain/<chain>` | `{params: {step_id: {…}}}` — several steps back to back; every argv is validated before the first one starts |
| `GET` | `/api/job?id=&from=&wait=` | long-polled log tail |
| `GET` | `/stream/<job_id>?from=` | the same as Server-Sent Events |
| `POST` | `/api/job/stop` | `{force}` — ask the job to stop at its next safe point (SIGTERM), or kill it (SIGKILL) |
| `GET` | `/api/changes?view=albums\|rows&page=&size=&…filters` | paged, with facet counts |
| `GET` | `/api/changes/album?key=` | the rows of one album |
| `POST` | `/api/changes/approve` | `{scope: rows\|album\|filter, value, …}` |
| `POST` | `/api/changes/value` | `{row, value}` — edit a proposed value |
| `POST` | `/api/changes/save` | write `changes.csv` |
| `POST` | `/schema/save` | `{set, remove, comment_out, preview}`; `preview` returns a diff instead of writing |
| `POST` | `/merge/apply` | `{diff_id: "mine"\|"theirs"\|"union"\|"skip"}` |

A job is a *list* of steps, so a single step and the whole chain are the same object:
`/api/job` and `/stream/<id>` report `index`, `total` and `steps` alongside the step
running now, and the log of a chain carries a `===== 2/4  analyze =====` banner between
steps.

Approvals and schema edits are held in server memory until you press *Guardar*, so an
accidental reload loses the edits rather than half-writing them.

## Stopping a run

*Parar* sends SIGTERM, which the scripts turn into a tidy stop at their next safe point
(`core.handle_interrupts`); the button then reads *Matar*, and a second press sends
SIGKILL after a confirmation. Each job runs in its own process group, so the signal
reaches any grandchild too.

Stopping during a chain also cancels the steps that have not started — the log ends with
`-- detenido: quedaban N paso(s) sin lanzar`. A stopped job finishes with return code 130
and shows as *detenido*, not as an error. `docs/PIPELINE.md` has what each step
guarantees when stopped.

## Files it writes

| Path | What |
|---|---|
| `schema.toml`, `changes.csv` | the real outputs, in their normal formats |
| `*.bak` | a copy of each file before it is overwritten |
| `gui/logs/<step>-<stamp>.log` | the full output of every run |

Both `*.bak` and `gui/logs/` are gitignored.

## Tests

```
python3 -m unittest discover gui/tests -t .
```

(The pipeline-side tests are in `tests/`; see [ARCHITECTURE.md](ARCHITECTURE.md#tests).)

The ones that matter:

- **Round trip** — parsing and re-dumping `schema.toml`, `schema.proposed.toml` and
  `schema.example.toml` must be byte-identical.
- **Agreement with tomli** — `to_dict()` must equal `tomli.load()` on the same files.
  The round trip alone is not enough: it passes even if a line is stored as opaque text
  and never understood, which is exactly how a real bug hid (all 142 `keep_together`
  entries parsed as prose while re-emitting perfectly).
- **Merge** — defaults, and that applying them keeps your decisions.
- **changes.csv** — that a save touches only `approve` and `new`, and that the CD
  collapsing groups a file's rows together.
- **Chains and stopping** (`test_runner_chain.py`) — a chain's argv are all built before
  the first step starts; the steps run in order; a failure stops the rest; a stop lets the
  running script choose its moment and cancels the steps not yet launched; `--force` kills
  one that ignores SIGTERM; and `as_dict()` keeps the keys the templates read.
- **Classical tree** (`test_classical_gui.py`) — keys with backslashes survive read, edit,
  add and remove; the merge adds new nodes and leaves your rule lists alone; the album card
  carries the proposed genre path; the schema page renders its `value` attributes and
  removes a `Clásica\…` row through `/schema/save`; the health warnings fire.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Page does not open from another machine | DSM firewall; see *Giving another machine access* |
| `403 Falta el token` | started with `--token`; add `?t=…` once and a cookie keeps it |
| `ya hay algo en marcha` | one job at a time, by design; wait or press *Parar* |
| A run shows *detenido* with code 130 | it was stopped on request, not a failure |
| *Parar* does not seem to do anything | the step stops at its next safe point, which for a long scan is the current file; press again to kill it |
| Log stops mid-run | progress is on stderr and is merged in; if the page was reloaded the log is still in `gui/logs/` |
| *Cambios* says there is no `changes.csv` | run step 3 |
| An edit vanished | schema and approval edits live in memory until *Guardar* |
| Saving the schema fails | the result was not valid TOML; nothing was written, and the `.bak` is there |

See also: [PIPELINE.md](PIPELINE.md), [SCHEMA.md](../SCHEMA.md),
[ARCHITECTURE.md](ARCHITECTURE.md).
