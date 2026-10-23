"""What the dashboard shows: pipeline freshness, library stats, schema health.

The staleness check is the useful part. The four steps are stateless scripts over
fixed filenames, so the only way to know that changes.csv no longer reflects the
schema you just edited is to compare mtimes -- which is exactly the mistake the
terminal workflow makes easy.
"""

import json
import os
import sqlite3
import time

from analyze_tags import split_genres
from classical_genres import Tree, tree_status
from core import composer_aliases, name_key, suggest_genre
from propose_changes import album_key
from rules import CreditSplitter

from gui.runner import ROOT, STEPS, music_dir
from gui.schema_edit import SchemaFile

COMPOSER_SPLIT = ["/", "; ", ";", ", ", " & ", " and "]
COVERAGE_FIELDS = ["title", "artist", "artists", "albumartist", "album", "artistsort",
                   "albumartistsort", "composer", "composersort", "conductor",
                   "ensemble", "genre", "style", "work", "movementname", "movement",
                   "date", "compilation"]
_LIB_CACHE = {}


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%d %s" % (n, unit) if n >= 10 or unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0


def human_age(ts):
    s = max(0, time.time() - ts)
    for limit, div, unit in ((90, 1, "s"), (5400, 60, "min"), (172800, 3600, "h")):
        if s < limit:
            return "hace %d %s" % (s // div, unit)
    return "hace %d días" % (s // 86400)


def file_info(name):
    try:
        st = os.stat(os.path.join(ROOT, name))
    except OSError:
        return {"name": name, "exists": False}
    return {"name": name, "exists": True, "mtime": st.st_mtime, "size": st.st_size,
            "size_h": human_size(st.st_size), "age": human_age(st.st_mtime),
            "when": time.strftime("%d/%m %H:%M", time.localtime(st.st_mtime))}


def pipeline():
    """Each step with its inputs, outputs, and whether its output is out of date."""
    out = []
    for step in STEPS:
        outputs = [file_info(n) for n in step["outputs"]]
        inputs = [file_info(n) for n in step["inputs"]]
        oldest_output = min([o["mtime"] for o in outputs if o["exists"]], default=0)
        done = bool(outputs) and all(o["exists"] for o in outputs)
        behind = [i["name"] for i in inputs if i["exists"] and i["mtime"] > oldest_output]
        out.append(dict(step, outputs=outputs, inputs=inputs,
                        missing=[i["name"] for i in inputs if not i["exists"]],
                        done=done, stale=bool(done and behind), stale_because=behind))
    return out


def library():
    """Counts straight from tags.sqlite, cached on its mtime (~11k rows, one pass)."""
    info = file_info("tags.sqlite")
    if not info["exists"]:
        return None
    if _LIB_CACHE.get("stamp") == info["mtime"]:
        return _LIB_CACHE["value"]

    db = sqlite3.connect(os.path.join(ROOT, "tags.sqlite"))
    rows = db.execute("SELECT path, format, tags, error, size FROM files").fetchall()
    root = (db.execute("SELECT value FROM meta WHERE key='root'").fetchone() or [""])[0]
    db.close()

    calias = composer_aliases()
    splitter = CreditSplitter(COMPOSER_SPLIT, [], [])
    coverage, formats, albums = {}, {}, set()
    classical = errors = total = 0
    for path, fmt, raw, err, size in rows:
        total += size or 0
        if err:
            errors += 1
            continue
        tags = json.loads(raw) if raw else {}
        formats[fmt] = formats.get(fmt, 0) + 1
        for field, values in tags.items():
            if values:
                coverage[field] = coverage.get(field, 0) + 1
        albums.add(album_key(path, tags))   # same grouping as the proposer
        if looks_classical(tags, calias, splitter):
            classical += 1

    n = len(rows) - errors
    value = {
        "root": root or music_dir(), "tracks": n, "errors": errors,
        "albums": len(albums), "classical": classical,
        "classical_pct": round(100 * classical / max(n, 1)),
        "formats": dict(sorted(formats.items(), key=lambda kv: -kv[1])),
        "bytes_h": human_size(total), "scanned": info,
        "coverage": [{"field": f, "n": coverage.get(f, 0),
                      "pct": round(100 * coverage.get(f, 0) / max(n, 1))}
                     for f in COVERAGE_FIELDS],
    }
    _LIB_CACHE.update(stamp=info["mtime"], value=value)
    return value


def looks_classical(tags, calias, splitter):
    """The same test analyze_tags.py uses for its 'tracks that look classical' line."""
    for v in tags.get("genre", []):
        for tok in split_genres(v):
            if suggest_genre(tok)[0] == "Classical":
                return True
    for v in tags.get("composer", []):
        for name in splitter.split_list(v):
            if name_key(name) in calias:
                return True
    return False


def schema_health():
    """Is schema.toml usable, and what does schema.proposed.toml have that it lacks?"""
    live, proposed = file_info("schema.toml"), file_info("schema.proposed.toml")
    out = {"live": live, "proposed": proposed, "missing_sections": [], "sections": [],
           "problems": [], "keep_together": 0, "keep_together_junk": [],
           "genres_pending": [], "ok": False}
    if not live["exists"]:
        out["problems"].append("No hay schema.toml: analiza la biblioteca y fusiona "
                               "la propuesta.")
        return out
    try:
        schema = SchemaFile.load(os.path.join(ROOT, "schema.toml"))
        cfg = schema.to_dict()
    except Exception as exc:                                      # noqa: BLE001
        out["problems"].append("schema.toml no se puede leer: %s" % exc)
        return out

    out["sections"] = schema.sections()
    if proposed["exists"]:
        try:
            other = SchemaFile.load(os.path.join(ROOT, "schema.proposed.toml"))
            out["missing_sections"] = [s for s in other.sections()
                                       if s not in out["sections"]]
        except Exception:                                         # noqa: BLE001
            pass

    if "album" not in out["sections"]:
        out["problems"].append("Falta la sección [album]: el renombrado de álbumes "
                               "clásicos está desactivado y proponer no te avisa.")
    elif not cfg.get("album", {}).get("enabled"):
        out["problems"].append("[album] enabled = false: no se renombrará ningún álbum.")
    out["problems"].extend(_classical_tree_problems(cfg))
    if "orchestra_abbrev" not in out["sections"]:
        out["problems"].append("Falta [orchestra_abbrev]: las orquestas aparecerán con "
                               "su nombre largo en vez de su código de 4 letras.")

    keep = cfg.get("artists", {}).get("keep_together", [])
    junk = [k for k in keep if is_junk_credit(k)]
    out["keep_together"], out["keep_together_junk"] = len(keep), junk
    if junk:
        out["problems"].append(
            "%d de las %d entradas de keep_together son créditos de iTunes sin limpiar "
            "('Main Artist, Orchestra - ...')." % (len(junk), len(keep)))

    # The undecided genres are the commented '# "Moderna" = ["?"]' lines, which
    # to_dict() leaves out on purpose, plus any active entry left empty.
    out["genres_pending"] = sorted(
        {l.key for l in schema.pairs("genre_map") if not l.active}
        | {k for k, v in cfg.get("genre_map", {}).items() if not v})
    if out["genres_pending"]:
        out["problems"].append(
            "%d géneros sin decidir en [genre_map]: %s." % (
                len(out["genres_pending"]), ", ".join(out["genres_pending"][:6])))
    out["ok"] = not out["problems"]
    return out


def _classical_tree_problems(cfg):
    """Why the GENRE path for classical albums (Clásica\\Orquestal\\Sinfonias) is not being proposed."""
    status = tree_status(cfg)
    if status == "missing":
        return ["Falta la sección [classical_genres]: lo clásico se queda con GENRE = Classical "
                "y tu jerarquía no se escribe. Fusiona la propuesta del análisis."]
    if status == "disabled":
        return ["[classical_genres] enabled = false: lo clásico se queda con GENRE = Classical."]
    if status == "empty":
        return ["[classical_rules] está vacía: no hay árbol de géneros clásicos que proponer."]
    tree = Tree.from_cfg(cfg)
    return ["[classical_rules]: %s" % p for p in (tree.problems if tree else [])]


def is_junk_credit(name):
    """iTunes role soup: 'Andrew Manze, Associated Performer, Violin, Main Artist - ...'."""
    low = name.lower()
    return len(name) > 60 and any(r in low for r in (
        "associated performer", "main artist", "featured artist", "orchestra, orchestra"))
