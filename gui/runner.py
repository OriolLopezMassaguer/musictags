"""Run the pipeline steps as subprocesses, one at a time, with a live log.

The steps are declared here rather than hard-coded in the templates, so the forms,
the argv and the staleness checks on the dashboard all come from one place.

Note on the log: scan_tags.py writes its progress to stderr and its summary to
stdout, so both streams are merged -- keeping them apart loses the progress counter.
"""

import glob
import os
import re
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "gui", "logs")


def music_dir():
    """MUSIC_DIR as config.sh defines it -- one source of truth with the shell steps."""
    try:
        with open(os.path.join(ROOT, "config.sh"), encoding="utf-8") as fh:
            m = re.search(r'^MUSIC_DIR="([^"]*)"', fh.read(), re.M)
        return m.group(1) if m else ""
    except OSError:
        return ""


# Fields propose_changes.py can be restricted to with --only.
ONLY_FIELDS = ["artist", "artists", "artistsort", "albumartist", "albumartistsort",
               "compilation", "composer", "composersort", "conductor", "ensemble",
               "genre", "style", "work", "movementname", "movement", "album"]

STEPS = [
    {
        "id": "scan", "n": 1, "label": "Escanear",
        "script": "scan_tags.py", "sh": "./1_scan.sh",
        "desc": "Lee los tags de cada fichero de la biblioteca.",
        "inputs": [], "outputs": ["tags.sqlite", "tags.csv"],
        "args": [
            {"name": "full", "type": "bool", "default": False, "flag": "--full",
             "label": "Releer todos los ficheros",
             "help": "Por defecto solo relee los que han cambiado de fecha o tamaño."},
            {"name": "workers", "type": "int", "default": 8, "flag": "--workers",
             "label": "Lectores en paralelo", "min": 1, "max": 32,
             "help": "El trabajo es de disco, no de CPU; 8 va bien en el NAS."},
        ],
    },
    {
        "id": "analyze", "n": 2, "label": "Analizar",
        "script": "analyze_tags.py", "sh": "./2_analyze.sh",
        "desc": "Escribe report.md y schema.proposed.toml a partir del escaneo.",
        "inputs": ["tags.sqlite"], "outputs": ["report.md", "schema.proposed.toml"],
        "args": [
            {"name": "fuzzy", "type": "bool", "default": True, "flag": "--fuzzy",
             "label": "Buscar posibles erratas",
             "help": "Nombres casi iguales (parecido ≥ 0,9). 2_analyze.sh lo lleva fijo."},
            {"name": "min_band", "type": "int", "default": 2, "flag": "--min-band",
             "label": "Mínimo de pistas para proteger un nombre", "min": 1, "max": 50,
             "help": "Un crédito 'A & B' cuyas partes nunca van solas se deja entero "
                     "si aparece en al menos estas pistas."},
        ],
    },
    {
        "id": "propose", "n": 3, "label": "Proponer",
        "script": "propose_changes.py", "sh": "./3_propose.sh",
        "desc": "Compara la biblioteca con schema.toml y escribe changes.csv.",
        "inputs": ["tags.sqlite", "schema.toml"], "outputs": ["changes.csv"],
        "args": [
            {"name": "only", "type": "fields", "default": [], "flag": "--only",
             "label": "Solo estos campos", "choices": ONLY_FIELDS,
             "help": "Vacío = todos."},
            {"name": "path", "type": "path", "default": "", "flag": "--path",
             "label": "Solo esta subcarpeta",
             "help": "Ruta dentro de la biblioteca. Vacío = toda."},
        ],
    },
    {
        "id": "apply", "n": 4, "label": "Aplicar",
        "script": "apply_changes.py", "sh": "./4_apply.sh",
        "desc": "Escribe en los ficheros las filas aprobadas. Simulación si no se confirma.",
        "inputs": ["changes.csv"], "outputs": [],
        "writes": True,
        "args": [
            {"name": "limit", "type": "int", "default": 0, "flag": "--limit",
             "label": "Solo los primeros N ficheros", "min": 0, "max": 100000,
             "help": "0 = sin límite. Útil para una primera prueba."},
            {"name": "force", "type": "bool", "default": False, "flag": "--force",
             "label": "Escribir aunque el fichero haya cambiado desde el escaneo",
             "help": "Normalmente esas filas se saltan, que es lo prudente."},
        ],
    },
    {
        "id": "undo", "n": 5, "label": "Deshacer",
        "script": "apply_changes.py", "sh": "./5_undo.sh",
        "desc": "Restaura los valores de un registro undo_*.jsonl.",
        "inputs": [], "outputs": [],
        "writes": True,
        "args": [
            {"name": "log", "type": "undolog", "default": "", "flag": "--undo",
             "label": "Registro a deshacer", "help": ""},
        ],
    },
]

BY_ID = {s["id"]: s for s in STEPS}


def undo_logs():
    return sorted((os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "undo_*.jsonl"))),
                  reverse=True)


class BadRequest(ValueError):
    """A parameter the user sent cannot be turned into a safe command line."""


def build_argv(step_id, params, write=False):
    """Step id + form values -> the argv to run. Raises BadRequest on bad input."""
    step = BY_ID.get(step_id)
    if step is None:
        raise BadRequest("paso desconocido: %s" % step_id)
    argv = [sys.executable, step["script"]]

    if step_id == "scan":
        root = music_dir()
        if not os.path.isdir(root):
            raise BadRequest("la biblioteca no existe: %s" % root)
        argv += [root, "--csv", "tags.csv"]
    elif step_id == "apply":
        argv.append("changes.csv")

    for spec in step["args"]:
        raw = params.get(spec["name"], spec["default"])
        kind = spec["type"]
        if kind == "bool":
            if _truthy(raw):
                argv.append(spec["flag"])
        elif kind == "int":
            n = _int(raw, spec)
            if n:
                argv += [spec["flag"], str(n)]
        elif kind == "fields":
            picked = [f for f in _list(raw) if f in spec["choices"]]
            if picked:
                argv += [spec["flag"], ",".join(picked)]
        elif kind == "path":
            if str(raw).strip():
                argv += [spec["flag"], _safe_path(str(raw).strip())]
        elif kind == "undolog":
            name = os.path.basename(str(raw).strip())
            if name not in undo_logs():
                raise BadRequest("registro no encontrado: %s" % (name or "(ninguno)"))
            argv += [spec["flag"], name]

    if step.get("writes"):
        if write:
            argv.append("--apply")       # otherwise it is a dry run, which is the default
    elif write:
        raise BadRequest("el paso %s no escribe nada" % step_id)
    return argv


def _truthy(v):
    return str(v).lower() in ("1", "true", "on", "yes", "y", "si", "sí")


def _int(v, spec):
    try:
        n = int(str(v).strip() or 0)
    except ValueError:
        raise BadRequest("%s: se esperaba un número, no %r" % (spec["label"], v))
    if n and not (spec.get("min", 0) <= n <= spec.get("max", 10 ** 9)):
        raise BadRequest("%s: fuera de rango (%s-%s)" % (spec["label"],
                                                         spec.get("min"), spec.get("max")))
    return n


def _list(v):
    if isinstance(v, (list, tuple)):
        return list(v)
    return [x for x in str(v).split(",") if x.strip()]


def _safe_path(p):
    """Keep --path inside the library: the GUI is reachable from the LAN."""
    root = os.path.realpath(music_dir())
    full = os.path.realpath(p if os.path.isabs(p) else os.path.join(root, p))
    if full != root and not full.startswith(root + os.sep):
        raise BadRequest("la ruta está fuera de la biblioteca: %s" % p)
    if not os.path.isdir(full):
        raise BadRequest("no es una carpeta: %s" % p)
    return full


class Job:
    """One run of one step. Its lines are kept so the log survives a page reload."""

    def __init__(self, step_id, argv, write):
        self.id = "%s-%s" % (step_id, time.strftime("%Y%m%d_%H%M%S"))
        self.step_id = step_id
        self.argv = argv
        self.write = write
        self.lines = []
        self.returncode = None
        self.started = time.time()
        self.finished = None
        self.log_path = os.path.join(LOG_DIR, self.id + ".log")
        self._cond = threading.Condition()
        self._proc = None

    @property
    def running(self):
        return self.finished is None

    def command(self):
        return " ".join(["python3" if a == sys.executable else a for a in self.argv])

    def start(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        self._emit("$ " + self.command())
        self._proc = subprocess.Popen(
            self.argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, errors="replace",
            env=dict(os.environ, PYTHONUNBUFFERED="1"))
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        with open(self.log_path, "w", encoding="utf-8") as fh:
            fh.write("$ %s\n" % self.command())
            for line in self._proc.stdout:
                line = line.rstrip("\n")
                fh.write(line + "\n")
                fh.flush()
                self._emit(line)
        self._proc.wait()
        with self._cond:
            self.returncode = self._proc.returncode
            self.finished = time.time()
            self._cond.notify_all()

    def _emit(self, line):
        with self._cond:
            self.lines.append(line)
            self._cond.notify_all()

    def follow(self, start=0, timeout=0.0):
        """Lines from `start` on, blocking up to `timeout` for the next one."""
        with self._cond:
            if start >= len(self.lines) and self.running and timeout:
                self._cond.wait(timeout)
            return self.lines[start:], len(self.lines), self.running

    def stop(self):
        if self._proc and self.running:
            self._proc.terminate()

    def as_dict(self):
        return {"id": self.id, "step": self.step_id, "running": self.running,
                "write": self.write, "returncode": self.returncode,
                "command": self.command(), "started": self.started,
                "elapsed": round((self.finished or time.time()) - self.started, 1),
                "lines": len(self.lines)}


class Runner:
    """One job at a time; the last finished one stays readable."""

    def __init__(self):
        self._lock = threading.Lock()
        self.jobs = {}
        self.current = None

    def start(self, step_id, params, write=False):
        argv = build_argv(step_id, params, write)
        with self._lock:
            if self.current is not None and self.current.running:
                raise BadRequest("ya hay un paso en marcha: %s" % self.current.step_id)
            job = Job(step_id, argv, write)
            self.jobs[job.id] = job
            self.current = job
        job.start()
        return job

    def busy(self):
        return self.current is not None and self.current.running

    def get(self, job_id):
        return self.jobs.get(job_id)


RUNNER = Runner()
