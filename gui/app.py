"""musictags GUI -- a browser front end for the four-step pipeline.

Everything here wraps the existing scripts; it never re-implements them. The
intermediate files keep their exact formats, so ./1_scan.sh .. ./5_undo.sh stay
usable from the terminal at any point.

    ./gui.sh                  http://<nas>:8765
    ./gui.sh --token secreto  requires ?t=secreto
"""

import argparse
import json
import os
import secrets
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import markdown
from flask import (Flask, Response, abort, jsonify, redirect, render_template,
                   request, url_for)

from gui import changes as changes_mod
from gui import schema_merge, state
from gui.runner import (ROOT, RUNNER, STEPS, BY_ID, BadRequest, undo_logs)
from gui.schema_edit import SchemaFile

app = Flask(__name__)
app.config["TOKEN"] = None
SCHEMA_PATH = os.path.join(ROOT, "schema.toml")

# Sections whose keys are data rows rather than options; rendered as tables.
MAP_SECTIONS = schema_merge.MAP_SECTIONS
SECTION_HELP = {
    "general": "Formato de escritura y qué confianzas se preaprueban.",
    "artists": "Cómo se parte un crédito en personas y cómo se vuelve a montar.",
    "albumartist": "Quién es el artista del álbum cuando falta o no coincide.",
    "composers": "Partido, nombre canónico y deducción de compositores.",
    "genres": "GENRE es la lista cerrada; STYLE recoge el detalle.",
    "genre_map": "Cada género en bruto de tu biblioteca → [GENRE, STYLE]. Vacío = borrarlo.",
    "album": "Nombres de álbum clásicos: compositor - obras (solista | ORQ / director).",
    "orchestra_abbrev": "Código de 4 letras con el que sale cada orquesta en el nombre.",
    "aliases": "Cualquier grafía → nombre canónico (artistas, compositores, directores).",
    "sort_overrides": "Nombre → nombre de ordenación, cuando la regla automática falla.",
}


# --------------------------------------------------------------------------- auth

@app.before_request
def check_token():
    token = app.config["TOKEN"]
    if not token or request.endpoint == "static":
        return None
    if request.args.get("t") == token or request.cookies.get("mt_token") == token:
        return None
    abort(403, "Falta el token. Añade ?t=… a la dirección.")


@app.after_request
def keep_token(response):
    token = app.config["TOKEN"]
    if token and request.args.get("t") == token:
        response.set_cookie("mt_token", token, httponly=True, samesite="Lax")
    return response


@app.context_processor
def globals_():
    return {"steps": STEPS, "busy": RUNNER.busy(), "undo_logs": undo_logs(),
            "current_job": RUNNER.current.as_dict() if RUNNER.current else None}


# --------------------------------------------------------------------------- pages

@app.route("/")
def panel():
    return render_template("panel.html", pipeline=state.pipeline(),
                           library=state.library(), health=state.schema_health(),
                           nav="panel")


@app.route("/merge")
def merge_page():
    live, prop = schema_merge.load_pair()
    if prop is None:
        return render_template("merge.html", nav="merge", diffs=[], summary=None,
                               error="No hay schema.proposed.toml: ejecuta el paso 2.")
    diffs = schema_merge.compare(live, prop)
    return render_template("merge.html", nav="merge",
                           diffs=[d.as_dict() for d in diffs],
                           summary=schema_merge.summary(diffs), error=None,
                           have_live=live is not None)


@app.post("/merge/apply")
def merge_apply():
    live, prop = schema_merge.load_pair()
    if prop is None:
        abort(400, "No hay schema.proposed.toml")
    choices = request.get_json(silent=True) or {}
    if live is None:
        import shutil
        shutil.copy2(os.path.join(ROOT, schema_merge.PROPOSED), SCHEMA_PATH)
        return jsonify(ok=True, applied=["(esquema nuevo)"])
    applied = schema_merge.apply(live, prop, choices)
    try:
        live.save(SCHEMA_PATH)
    except Exception as exc:                                     # noqa: BLE001
        return jsonify(ok=False, error=str(exc)), 400
    return jsonify(ok=True, applied=applied)


@app.route("/schema")
def schema_page():
    if not os.path.exists(SCHEMA_PATH):
        return render_template("schema.html", nav="schema", sections=[], error=(
            "No hay schema.toml todavía. Ve a Fusionar para crearlo a partir de "
            "la propuesta del análisis."))
    schema = SchemaFile.load(SCHEMA_PATH)
    sections = []
    for name in schema.sections():
        entries = [line.as_dict() for line in schema.pairs(name)]
        sections.append({"name": name, "help": SECTION_HELP.get(name, ""),
                         "is_map": name in MAP_SECTIONS, "entries": entries,
                         "n": len(entries),
                         "pending": sum(1 for e in entries if not e["active"])})
    return render_template("schema.html", nav="schema", sections=sections,
                           error=None, info=state.file_info("schema.toml"))


@app.post("/schema/save")
def schema_save():
    """{'set': {section: {key: value}}, 'remove': [[section, key]], 'add': [...]}"""
    payload = request.get_json(silent=True) or {}
    schema = SchemaFile.load(SCHEMA_PATH)
    touched = 0
    for section, entries in (payload.get("set") or {}).items():
        for key, value in entries.items():
            line = schema.get(section, key)
            if line is None:
                schema.add(section, key, value)
            elif line.value != value or not line.active:
                line.set_value(value)
            else:
                continue
            touched += 1
    for section, key in (payload.get("remove") or []):
        touched += bool(schema.remove(section, key))
    for section, key in (payload.get("comment_out") or []):
        line = schema.get(section, key)
        if line is not None and line.active:
            line.comment_out()
            touched += 1

    text = schema.dumps()
    if payload.get("preview"):
        return jsonify(ok=True, touched=touched, diff=_diff(SCHEMA_PATH, text))
    try:
        schema.save(SCHEMA_PATH)
    except Exception as exc:                                     # noqa: BLE001
        return jsonify(ok=False, error="El resultado no es TOML válido: %s" % exc), 400
    return jsonify(ok=True, touched=touched)


def _diff(path, new_text):
    import difflib
    with open(path, encoding="utf-8") as fh:
        old = fh.read()
    return "\n".join(difflib.unified_diff(old.splitlines(), new_text.splitlines(),
                                          "schema.toml", "después", lineterm=""))


@app.route("/report")
def report_page():
    info = state.file_info("report.md")
    if not info["exists"]:
        return render_template("report.html", nav="report", html="", toc=[], info=info)
    with open(os.path.join(ROOT, "report.md"), encoding="utf-8") as fh:
        text = fh.read()
    md = markdown.Markdown(extensions=["tables", "toc", "sane_lists"])
    html = md.convert(text)
    toc = [{"level": t["level"], "id": t["id"], "name": t["name"]}
           for t in md.toc_tokens for t in [t] + t.get("children", [])]
    return render_template("report.html", nav="report", html=html, toc=toc, info=info)


@app.route("/changes")
def changes_page():
    return render_template("changes.html", nav="changes",
                           info=state.file_info("changes.csv"))


# --------------------------------------------------------------------------- api

@app.get("/api/changes")
def api_changes():
    cs = _changeset()
    if cs is None:
        return jsonify(ok=False, error="No hay changes.csv: ejecuta el paso 3."), 404
    f = _filters()
    view = request.args.get("view", "albums")
    page = max(1, int(request.args.get("page", 1)))
    size = min(200, max(5, int(request.args.get("size", 25))))
    payload = {"ok": True, "facets": cs.facets, "counts": cs.counts(**f),
               "dirty": cs.dirty, "view": view, "page": page, "size": size}
    if view == "albums":
        albums = cs.album_list(**f)
        payload["total"] = len(albums)
        payload["albums"] = [_trim(a) for a in albums[(page - 1) * size: page * size]]
    else:
        rows = cs.filter_rows(**f)
        payload["total"] = len(rows)
        payload["rows"] = [cs.row_dict(i) for i in rows[(page - 1) * size: page * size]]
    return jsonify(payload)


def _trim(album):
    album.pop("row_ids", None)
    return album


@app.get("/api/changes/album")
def api_album():
    cs = _changeset()
    if cs is None:
        abort(404)
    key = request.args.get("key", "")
    rows = cs.album_rows(key, **_filters())
    return jsonify(ok=True, rows=[cs.row_dict(i) for i in rows])


@app.post("/api/changes/approve")
def api_approve():
    """Approve/unapprove a set of rows, a whole album, or everything matching."""
    cs = _changeset()
    if cs is None:
        abort(404)
    body = request.get_json(silent=True) or {}
    value = bool(body.get("value"))
    scope = body.get("scope", "rows")
    if scope == "rows":
        indexes = [int(i) for i in body.get("rows", [])]
    elif scope == "album":
        indexes = cs.album_rows(body.get("key", ""), **_filters(body.get("filters")))
    elif scope == "filter":
        indexes = cs.filter_rows(**_filters(body.get("filters")))
    else:
        abort(400, "scope desconocido")
    n = cs.set_approved(indexes, value)
    return jsonify(ok=True, changed=n, counts=cs.counts(**_filters(body.get("filters"))))


@app.post("/api/changes/value")
def api_value():
    cs = _changeset()
    if cs is None:
        abort(404)
    body = request.get_json(silent=True) or {}
    ok = cs.set_new(int(body["row"]), body.get("value", ""))
    return jsonify(ok=True, changed=ok)


@app.post("/api/changes/save")
def api_save_changes():
    cs = _changeset()
    if cs is None:
        abort(404)
    cs.save()
    return jsonify(ok=True, path=os.path.basename(cs.path),
                   counts=cs.counts())


def _changeset():
    try:
        return changes_mod.load()
    except ValueError:
        return None


def _filters(src=None):
    src = src if src is not None else request.args
    get = src.get
    return {"field": get("field", "") or "", "confidence": get("confidence", "") or "",
            "rule": get("rule", "") or "", "q": get("q", "") or "",
            "pending": str(get("pending", "")).lower() in ("1", "true", "on")}


# -- running steps ----------------------------------------------------------

@app.post("/api/run/<step_id>")
def api_run(step_id):
    body = request.get_json(silent=True) or {}
    write = bool(body.get("write"))
    step = BY_ID.get(step_id)
    if step is None:
        abort(404)
    if write and body.get("confirm") != "APLICAR":
        return jsonify(ok=False, error="Escribir en los ficheros necesita confirmación."), 400
    try:
        job = RUNNER.start(step_id, body.get("params") or {}, write)
    except BadRequest as exc:
        return jsonify(ok=False, error=str(exc)), 400
    if step_id in ("propose", "apply", "undo"):
        changes_mod.invalidate()
    return jsonify(ok=True, job=job.as_dict())


@app.get("/api/job")
def api_job():
    job = RUNNER.get(request.args.get("id", "")) or RUNNER.current
    if job is None:
        return jsonify(ok=True, job=None, lines=[], next=0)
    start = int(request.args.get("from", 0))
    lines, total, running = job.follow(start, timeout=float(request.args.get("wait", 0)))
    return jsonify(ok=True, job=job.as_dict(), lines=lines, next=total, running=running)


@app.post("/api/job/stop")
def api_job_stop():
    if RUNNER.current:
        RUNNER.current.stop()
    return jsonify(ok=True)


@app.get("/stream/<job_id>")
def stream(job_id):
    job = RUNNER.get(job_id)
    if job is None:
        abort(404)

    def gen():
        sent = max(0, int(request.args.get("from", 0)))
        while True:
            lines, sent, running = job.follow(sent, timeout=1.0)
            for line in lines:
                yield "data: %s\n\n" % json.dumps(line)
            if not running and not lines:
                yield "event: done\ndata: %s\n\n" % json.dumps(job.as_dict())
                return

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/state")
def api_state():
    return jsonify(ok=True, pipeline=[{k: v for k, v in s.items() if k != "args"}
                                      for s in state.pipeline()],
                   busy=RUNNER.busy(),
                   job=RUNNER.current.as_dict() if RUNNER.current else None)


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--token", nargs="?", const=secrets.token_urlsafe(8),
                    help="exigir ?t=TOKEN (sin valor, se genera uno)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    app.config["TOKEN"] = args.token
    suffix = "/?t=%s" % args.token if args.token else "/"
    hosts = (["localhost"] if args.host in ("127.0.0.1", "localhost") else _lan_ips())
    print("musictags GUI")
    for ip in hosts:
        print("  http://%s:%d%s" % (ip, args.port, suffix))
    if args.token:
        print("  token: %s" % args.token)
    if args.host not in ("127.0.0.1", "localhost"):
        print("\nSi desde otro equipo no abre, es el cortafuegos de DSM: "
              "Panel de control ->\nSeguridad -> Cortafuegos, permite TCP %d. "
              "Sin tocar nada, desde el portátil:\n  ssh -L %d:127.0.0.1:%d %s@%s "
              "   y luego http://localhost:%d%s"
              % (args.port, args.port, args.port, os.environ.get("USER", "usuario"),
                 hosts[0] if hosts else "nas", args.port, suffix))
    threading.Thread(target=_warm, daemon=True).start()
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


def _warm():
    """The first library() pass reads 11k rows; do it before the first page view."""
    try:
        state.library()
    except Exception:                                            # noqa: BLE001
        pass


def _lan_ips():
    """Every LAN address the NAS answers on -- it usually has more than one."""
    import socket
    found = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 1))
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "172.")) and ip not in found:
                found.append(ip)
    except socket.gaierror:
        pass
    return found or ["0.0.0.0"]


if __name__ == "__main__":
    main()
