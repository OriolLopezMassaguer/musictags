"""Run the pipeline steps as subprocesses, one at a time, with a live log.

The steps are declared here rather than hard-coded in the templates, so the forms,
the argv and the staleness checks on the dashboard all come from one place.

A job is a *list* of steps, so one code path covers a single step and the whole
chain (CHAINS). It stops at the first failure, and "Parar" asks the running
script to stop at its next safe point (SIGTERM, which core.handle_interrupts
turns into a tidy exit) before escalating to SIGKILL on a second press.

Note on the log: scan_tags.py writes its progress to stderr and its summary to
stdout, so both streams are merged -- keeping them apart loses the progress counter.
"""

import glob
import os
import re
import signal
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT, "gui", "logs")

sys.path.insert(0, ROOT)
from core import EXIT_INTERRUPTED            # noqa: E402  (ROOT must come first)


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

# Running several steps back to back. Step 4 is included as a dry run only:
# writing to the music files stays a separate, explicitly confirmed action.
CHAINS = [
    {
        "id": "all", "label": "Todo seguido", "sh": "./0_all.sh",
        "steps": ["scan", "analyze", "propose", "apply"],
        "desc": "Escanear, analizar, proponer y simular la aplicación, uno detrás de "
                "otro, con las opciones de cada paso de abajo. Se detiene en cuanto "
                "uno falla.",
        "note": "El paso 4 va en simulación: no escribe nada en tus ficheros. "
                "Aplicar de verdad sigue siendo un botón aparte, con confirmación.",
    },
]
BY_CHAIN = {c["id"]: c for c in CHAINS}


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


def build_chain(chain_id, params_by_step):
    """Chain id + {step_id: form values} -> [(step_id, argv)].

    Every argv is built up front: a bad --path must fail now, not three steps in.
    """
    chain = BY_CHAIN.get(chain_id)
    if chain is None:
        raise BadRequest("cadena desconocida: %s" % chain_id)
    params_by_step = params_by_step or {}
    return chain, [(sid, build_argv(sid, params_by_step.get(sid) or {}))
                   for sid in chain["steps"]]


class Job:
    """One run: a single step, or a chain of them. Its lines survive a reload."""

    def __init__(self, plan, write=False, label=None, chain_id=None):
        """plan: [(step_id, argv)], run in order, stopping at the first failure."""
        self.plan = list(plan)
        self.chain_id = chain_id
        self.step_id = self.plan[0][0]                  # the one running right now
        self.label = label or BY_ID[self.step_id]["label"]
        self.id = "%s-%s" % (chain_id or self.step_id, time.strftime("%Y%m%d_%H%M%S"))
        self.write = write
        self.lines = []
        self.returncode = None
        self.index = 0
        self.started = time.time()
        self.finished = None
        self.log_path = os.path.join(LOG_DIR, self.id + ".log")
        self._cond = threading.Condition()
        self._proc = None
        self._stopping = False
        self._forced = False

    @property
    def running(self):
        return self.finished is None

    @property
    def total(self):
        return len(self.plan)

    def command(self):
        """The command line of the step running now."""
        return _pretty(self.plan[self.index][1])

    def start(self):
        os.makedirs(LOG_DIR, exist_ok=True)
        threading.Thread(target=self._pump, daemon=True).start()

    # -- the chain ---------------------------------------------------------

    def _pump(self):
        code = 0
        with open(self.log_path, "w", encoding="utf-8") as fh:
            for i, (step_id, argv) in enumerate(self.plan):
                if self._stopping:
                    self._write(fh, "-- detenido: quedaban %d paso(s) sin lanzar"
                                    % (self.total - i))
                    code = code or EXIT_INTERRUPTED
                    break
                with self._cond:
                    self.index, self.step_id = i, step_id
                if self.total > 1:
                    self._write(fh, "")
                    self._write(fh, "===== %d/%d  %s =====" % (i + 1, self.total, step_id))
                code = self._run_one(fh, argv)
                if code:
                    if self.total > 1 and not self._stopping:
                        self._write(fh, "-- %s ha terminado con el código %d: "
                                        "la cadena se detiene aquí." % (step_id, code))
                    break
        with self._cond:
            self.returncode = code
            self.finished = time.time()
            self._cond.notify_all()

    def _run_one(self, fh, argv):
        self._write(fh, "$ " + _pretty(argv))
        proc = subprocess.Popen(
            argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            # UTF-8 both ways: on Windows the pipe defaults to cp1252 and crashes on e.g. Cyrillic tags.
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            # its own process group, so a stop reaches any grandchild too
            start_new_session=True,
            env=dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
        with self._cond:
            self._proc = proc
        if self._stopping:                  # pressed between two steps
            self._signal(proc, signal.SIGTERM)
        with proc:                          # closes the pipe and waits
            for line in proc.stdout:
                self._write(fh, line.rstrip("\n"))
        return proc.returncode

    def _write(self, fh, line):
        fh.write(line + "\n")
        fh.flush()
        self._emit(line)

    def _emit(self, line):
        with self._cond:
            self.lines.append(line)
            self._cond.notify_all()

    # -- following and stopping -------------------------------------------

    def follow(self, start=0, timeout=0.0):
        """Lines from `start` on, blocking up to `timeout` for the next one."""
        with self._cond:
            if start >= len(self.lines) and self.running and timeout:
                self._cond.wait(timeout)
            return self.lines[start:], len(self.lines), self.running

    def stop(self, force=False):
        """Ask the run to stop. Cancels the rest of the chain either way."""
        with self._cond:
            self._stopping = True
            self._forced = self._forced or force
            proc = self._proc
        if proc is not None and proc.poll() is None:
            self._signal(proc, getattr(signal, "SIGKILL", signal.SIGTERM) if force else signal.SIGTERM)
        return True

    @staticmethod
    def _signal(proc, sig):
        """To the whole group: SIGTERM is a request, SIGKILL is not."""
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (AttributeError, OSError, ProcessLookupError):   # no process groups on Windows
            try:
                proc.send_signal(sig)
            except (OSError, ProcessLookupError):
                pass

    @property
    def stopped(self):
        """Finished because it was asked to, rather than on its own."""
        return not self.running and self._stopping

    def as_dict(self):
        return {"id": self.id, "step": self.step_id, "label": self.label,
                "chain": self.chain_id, "index": self.index, "total": self.total,
                "steps": [sid for sid, _ in self.plan],
                "running": self.running, "write": self.write,
                "returncode": self.returncode, "command": self.command(),
                "stopping": self._stopping, "stopped": self.stopped,
                "forced": self._forced, "started": self.started,
                "elapsed": round((self.finished or time.time()) - self.started, 1),
                "lines": len(self.lines)}


def _pretty(argv):
    return " ".join(["python3" if a == sys.executable else a for a in argv])


class Runner:
    """One job at a time; the last finished one stays readable."""

    def __init__(self):
        self._lock = threading.Lock()
        self.jobs = {}
        self.current = None

    def start(self, step_id, params, write=False):
        if step_id not in BY_ID:
            raise BadRequest("paso desconocido: %s" % step_id)
        argv = build_argv(step_id, params, write)
        return self._launch(Job([(step_id, argv)], write=write))

    def start_chain(self, chain_id, params_by_step):
        chain, plan = build_chain(chain_id, params_by_step)
        return self._launch(Job(plan, label=chain["label"], chain_id=chain["id"]))

    def _launch(self, job):
        with self._lock:
            if self.current is not None and self.current.running:
                raise BadRequest("ya hay algo en marcha: %s" % self.current.label)
            self.jobs[job.id] = job
            self.current = job
        job.start()
        return job

    def busy(self):
        return self.current is not None and self.current.running

    def get(self, job_id):
        return self.jobs.get(job_id)


RUNNER = Runner()
