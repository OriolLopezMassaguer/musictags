"""
classical_genres.py - hierarchical GENRE for classical music:  Clásica\\Orquestal\\Sinfonias

The tree is DATA, in schema.toml:

    [classical_genres]   options (enabled, existing, no_match, majority, min_coverage)
    [classical_rules]    "Clásica\\Orquestal\\Sinfonias" = ["symphony"]     one key per node

A rule is a '+'-joined AND of concepts; the list elements are ORed; [] = a valid node that no
rule leads to (it can still be reached as a parent / 'Varios' / 'Otros' fallback).

Concepts (see extract_concepts): a form (symphony, concerto, sonata, quartet, mass...), ONE
instrument (piano, violin, cello...), multi, solo, period:<baroque>, composer:<surname>,
kw:<text> (substring of the work text).

Dependency-free on purpose (re / unicodedata / collections only): importing it must not need
mutagen, so the GUI and the tests can use it anywhere.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, OrderedDict, namedtuple

SEP = "\\"
BAD_CHARS = "/;,|"                 # would be split by [genres] split_separators
SUFFIXES = {"ii", "iii", "jr", "jr.", "sr", "sr."}


# --------------------------------------------------------------------------- #
# Keys                                                                         #
# --------------------------------------------------------------------------- #
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s.casefold()).strip()


def path_key(s: str) -> str:
    """Segment-wise fold: 'Clásica\\Cámara' -> 'clasica\\camara'.  Unlike core.genre_key it
    does NOT turn the backslash into a space, so 'Clásica\\Cámara' and 'Clásica Cámara' differ."""
    return SEP.join(x for x in (_fold(p) for p in (s or "").split(SEP)) if x)


def parent_of(path: str) -> str:
    return path.rsplit(SEP, 1)[0] if SEP in path else ""


def leaf_of(path: str) -> str:
    return path.rsplit(SEP, 1)[-1]


def is_ancestor(a_key: str, b_key: str) -> bool:
    """a is a proper ancestor of b (both path_keys)."""
    return bool(a_key) and b_key.startswith(a_key + SEP)


# --------------------------------------------------------------------------- #
# Concepts                                                                     #
# --------------------------------------------------------------------------- #
# Everything is matched against accent-folded, lower-cased text.
FORMS = OrderedDict([
    ("tone_poem", r"tone poems?|symphonic poems?|poemas? sinfonic[oa]s?|poemes? symphoniques?|"
                  r"tondichtung(?:en)?|sinfonische dichtung(?:en)?"),
    ("symphony", r"symphon(?:y|ies|ie|ia)|sinfon(?:ia|ias|ie|ien|ies)|simfon(?:ia|ies)"),
    ("concerto_grosso", r"concertos? grosso|concerti grossi|concertos? grossos?"),
    ("concerto", r"concertos?|concerti|conciertos?|\w*konzerte?|concertinos?|concertstuck|concertante|"
                 r"concerts? (?:for|pour|per|fur|en|in)"),
    ("sonata", r"sonatas?|\w*sonaten?|sonatinas?|sonatine|sonatinen"),
    ("partita", r"partitas?|partiten"),
    ("orchsuite", r"orchestral suites?|suites? for orchestra|suites? orchestrales?|orchestersuiten?|"
                  r"suites? para orquesta|suites? orquestales?|suites? per orchestra"),
    ("suite", r"suites?|suiten"),
    ("quartet", r"quartets?|quatuors?|cuartetos?|quartett(?:e|s)?|quartetti|quartetto|"
                r"streichquartett(?:e)?"),
    ("trio", r"trios?|trii|klaviertrio|streichtrio|terzetto"),
    ("quintet", r"quintets?|quintettes?|quintetos?|quintett(?:e|s)?|quintetti|quintetto|"
                r"streichquintett(?:e)?"),
    ("chamber", r"sextets?|sextuors?|sextetos?|sextett|septets?|septuors?|septetos?|septett|"
                r"octets?|octuors?|octetos?|oktett|nonets?|chamber music|musica de camara|"
                r"kammermusik|musique de chambre"),
    ("requiem", r"requiem|messe des morts|misa de difuntos"),
    ("mass", r"mass(?:es)?|misas?|messes?|messa|missa(?:e|s)?"),
    ("sacred", r"motets?|motetes?|motette[ns]?|magnificat|te deum|stabat mater|oratorios?|oratorien|"
               r"passions?|pasion(?:es)?|passio|psalms?|salmos?|psaumes?|psalmen|kyrie|credo|sanctus|"
               r"agnus dei|laudate|miserere|ave maria|ave verum|vespers|vesperae|vespro|vepres|"
               r"lamentations?|lamentaciones|responsor(?:y|ies|io|ios)|chorales?|hymns?|himnos?|"
               r"litany|litanies|tenebrae|nunc dimittis|salve regina|regina caeli|alleluia|aleluya|"
               r"sacred|sacra|sagrad[oa]s?|geistlich\w*"),
    ("opera", r"operas?|opern|opera comique|opera buffa|opera seria|operetta|singspiel|oper"),
    ("zarzuela", r"zarzuelas?"),
    ("ballet", r"ballets?|balletti|balletto"),
    ("lied", r"lieder|lied|liederkreis|liederzyklus|art songs?|song cycles?|winterreise|"
             r"schone mullerin|schwanengesang|dichterliebe|frauenliebe und leben"),
    ("overture", r"overtures?|ouvertures?|oberturas?|ouverturen|ouvertura"),
    ("serenade", r"serenades?|serenatas?|serenaden|divertimentos?|divertimenti|divertissements?|"
                 r"cassations?|notturno"),
    ("cantata", r"cantatas?|kantaten?|cantates?"),
    ("variations", r"variations?|variaciones|variationen|variazioni"),
    ("keyboard_form", r"nocturnes?|etudes?|impromptus?|mazurkas?|polonaises?|bagatelles?|gymnopedies?|"
                      r"gnossiennes?|klavierstucke?|arabesques?|barcarolles?|moments? musicaux|"
                      r"songs? without words|kinderszenen|scenes? d'enfants"),
])
INSTRUMENTS = OrderedDict([
    ("piano", r"pianos?|pianoforte|fortepiano|klavier"),
    ("violin", r"violins?|violino|violine|violon|geige"),
    ("viola", r"viola(?! da gamba)|bratsche"),
    ("cello", r"cellos?|celo|violoncell?[eo]s?|violonchelo|violoncelle"),
    ("flute", r"flutes?|flautas?|flauto|flote"),
    ("oboe", r"oboes?|oboi|oboen|hautbois"),
    ("clarinet", r"clarinets?|clarinetes?|clarinetto|clarinette|klarinette"),
    ("bassoon", r"bassoons?|fagot|fagotto|basson"),
    ("horn", r"horns?|trompa|waldhorn"),
    ("trumpet", r"trumpets?|trompetas?|trompete|tromba|trompette"),
    ("harp", r"harps?|arpa|harfe|harpe"),
    ("guitar", r"guitars?|guitarras?|gitarre|guitare|chitarra"),
    ("organ", r"organs?|organo|orgel|orgue"),
    ("harpsichord", r"harpsichords?|clave|clavecin|cembalo|clavicembalo"),
    ("lute", r"lutes?|laud|laute|luth|liuto"),
    ("saxophone", r"saxophones?|saxofon(?:es)?|saxofono|saxophon"),
])
# German compounds name the instrument in front of the form: Klavierkonzert, Cellosonate
_COMPOUND = r"(?:konzert|sonate|trio|quartett|quintett|suite|variationen|stucke?)\w*"
for _name, _stem in (("piano", "klavier"), ("violin", "violin"), ("cello", "cello|violoncello"),
                     ("flute", "floten?"), ("oboe", "oboen?"), ("clarinet", "klarinetten?"),
                     ("bassoon", "fagott"), ("horn", "horn"), ("trumpet", "trompeten?"),
                     ("harp", "harfen?"), ("guitar", "gitarren?"), ("organ", "orgel"),
                     ("harpsichord", "cembalo"), ("lute", "lauten?")):
    INSTRUMENTS[_name] += r"|(?:%s)%s" % (_stem, _COMPOUND)
OTHER_CONCEPTS = {"multi", "solo"}
CONCEPT_NAMES = set(FORMS) | set(INSTRUMENTS) | OTHER_CONCEPTS
CONCEPT_PREFIXES = ("period:", "composer:", "kw:")

_SOLO = re.compile(r"\bsolos?\b")
# 'Symphony Orchestra', 'Orquesta Sinfónica', 'symphonique': an ensemble, not a form
_NOISE = re.compile(
    r"\b(?:symphon\w*|sinfon\w*|simfon\w*)\s+(?:orch\w*|orqu\w*|band|chorus|choir|chor)\b|"
    r"\b(?:orch\w*|orqu\w*)\s+(?:de\s+|of\s+|della\s+)?(?:symphon\w*|sinfon\w*|simfon\w*)\b|"
    r"\b(?:sinfonic[oa]s?|symphoniques?|symphonischer?|sinfonisch\w*|simfonic[oa]s?)\b")
_FORM_RX = {k: re.compile(r"\b(?:%s)\b" % v) for k, v in FORMS.items()}
_INST_RX = {k: re.compile(r"\b(?:%s)\b" % v) for k, v in INSTRUMENTS.items()}


class Concepts:
    """What one work is: a set of concept tags plus its folded text (for 'kw:' rules)."""
    __slots__ = ("tags", "text")

    def __init__(self, tags=(), text=""):
        self.tags, self.text = frozenset(tags), text

    def has(self, term: str) -> bool:
        if term.startswith("kw:"):
            return term[3:] in self.text
        return term in self.tags

    def __repr__(self):
        return "Concepts(%s)" % ", ".join(sorted(self.tags))


def extract_concepts(work=None, title=None, composers=(), periods=(), text=None) -> Concepts:
    """Concepts of ONE work. Source text is WORK, else the title, else `text` (album fallback);
    artist / album-artist credits are never passed in, so 'Berlin Symphony Orchestra' cannot
    make an album a symphony."""
    src = _fold(work or title or text or "")
    tags = set()
    if src:
        body = _NOISE.sub(" ", src)
        for name, rx in _FORM_RX.items():
            if rx.search(src if name == "tone_poem" else body):
                tags.add(name)
        if "zarzuela" in tags:                    # a stage work as well
            tags.add("opera")
        if "concerto_grosso" in tags:             # also a concerto, only less specific
            tags.add("concerto")
        found = {n: m.start() for n, rx in _INST_RX.items() for m in [rx.search(body)] if m}
        order = sorted(found, key=found.get)
        if "concerto" in tags and len(order) >= 2:
            tags.add("multi")                     # double / triple concerto
        elif order:                               # first-named instrument; piano only if alone
            tags.add(next((i for i in order if i != "piano"), "piano"))
        if _SOLO.search(body):
            tags.add("solo")
    for c in composers:
        toks = _fold(c).split()
        while len(toks) > 1 and toks[-1] in SUFFIXES:
            toks.pop()
        if toks:
            tags.add("composer:" + toks[-1])
    for p in periods:
        w = _fold(p).split()
        if w:
            tags.add("period:" + w[0])            # 'Classical Period' -> period:classical
    return Concepts(tags, src)


# --------------------------------------------------------------------------- #
# The tree                                                                     #
# --------------------------------------------------------------------------- #
Decision = namedtuple("Decision", "path conf how n m")    # how: unanimous | majority | common | album-text
Result = namedtuple("Result", "path conf was")            # what to write for an album (was = old path)

DEFAULTS = {"enabled": True, "existing": "recalc", "no_match": "root",
            "majority": 0.6, "min_coverage": 0.5}
ENUMS = {"existing": ("recalc", "keep"), "no_match": ("root", "varios", "keep")}
FALLBACK_CHILDREN = ("varios", "otros", "various", "others", "other")


def tree_status(cfg: dict) -> str:
    """'ok' | 'missing' | 'disabled' | 'empty' - why Tree.from_cfg returned None."""
    sec = cfg.get("classical_genres")
    if not isinstance(sec, dict):
        return "missing"
    if not sec.get("enabled", True):
        return "disabled"
    rules = cfg.get("classical_rules")
    return "ok" if isinstance(rules, dict) and rules else "empty"


def _term(t: str) -> str:
    t = t.strip()
    if ":" in t:
        prefix, _, value = t.partition(":")
        return prefix.strip().lower() + ":" + _fold(value)
    return t.lower()


def _valid_term(t: str) -> bool:
    if t.startswith(CONCEPT_PREFIXES):
        return bool(t.partition(":")[2])
    return t in CONCEPT_NAMES


class Tree:
    """The genre tree of a schema: nodes (path -> rules), the album vote and the guards."""

    def __init__(self, nodes, opts, problems):
        self.nodes = nodes                                    # spelled path -> [tuple of terms]
        self.opts = opts
        self.problems = problems
        self.keys = {path_key(p): p for p in nodes}           # path_key -> spelled path
        roots = Counter(path_key(p).split(SEP)[0] for p in nodes)
        self.root_keys = set(roots)
        top = roots.most_common(1)[0][0]
        self.root = next(p.split(SEP)[0].strip() for p in nodes if path_key(p).split(SEP)[0] == top)

    # ---- building -------------------------------------------------------
    @classmethod
    def from_cfg(cls, cfg: dict):
        """None when the section is missing / disabled / has no rules (= today's behaviour)."""
        if tree_status(cfg) != "ok":
            return None
        opts, problems = dict(DEFAULTS), []
        for k, v in cfg["classical_genres"].items():
            if k in ENUMS and v not in ENUMS[k]:
                problems.append("[classical_genres] %s = %r: use one of %s" % (k, v, ", ".join(ENUMS[k])))
            elif k in ("majority", "min_coverage"):
                if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 < v <= 1:
                    problems.append("[classical_genres] %s = %r: use a number in (0, 1]" % (k, v))
                    continue
                opts[k] = float(v)
            else:
                opts[k] = v
        nodes, seen = OrderedDict(), {}
        for key, val in cfg["classical_rules"].items():
            segs = [s.strip() for s in key.split(SEP)]
            if not key.strip() or not all(segs):
                problems.append("[classical_rules] %r: empty path segment" % key)
                continue
            bad = [c for c in BAD_CHARS if c in key]
            if bad:
                problems.append("[classical_rules] %r contains %s, which the genre splitter would "
                                "cut in two" % (key, " ".join(bad)))
            pk = path_key(key)
            if pk in seen:
                problems.append("[classical_rules] %r and %r are the same node once accents and "
                                "case are ignored" % (seen[pk], key))
                continue
            seen[pk] = key
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                problems.append("[classical_rules] %r: the value must be a list of rule strings" % key)
                val = []
            rules = []
            for raw in val:
                terms = tuple(_term(t) for t in raw.split("+") if t.strip())
                wrong = [t for t in terms if not _valid_term(t)]
                if not terms or wrong:
                    problems.append("[classical_rules] %r: rule %r has %s" % (
                        key, raw, "unknown concept " + ", ".join(repr(w) for w in wrong) if wrong
                        else "no concept"))
                    continue
                rules.append(terms)
            nodes[key.strip()] = rules
        if not nodes:
            return None
        return cls(nodes, opts, problems)

    # ---- single values --------------------------------------------------
    def lookup(self, raw: str):
        """The tree's spelling of a genre value, or None when it is not a node."""
        return self.keys.get(path_key(raw))

    def is_foreign(self, raw: str) -> bool:
        """A path under one of the tree's roots that the tree does not list (your own nodes)."""
        if any(c in raw for c in BAD_CHARS):                  # 'a\\b; c' is packed: split it first
            return False
        k = path_key(raw)
        return SEP in k and k not in self.keys and k.split(SEP)[0] in self.root_keys

    def is_prior(self, raw: str) -> bool:
        """Already part of the hierarchy: a node, a foreign path under the root, or the bare root."""
        k = path_key(raw)
        return k in self.keys or k in self.root_keys or self.is_foreign(raw)

    def priors_in(self, values, split) -> list:
        """The hierarchy paths (as written in the file) among a track's GENRE values; `split`
        cuts a packed value ('a; b', written by ID3v2.3) into tokens."""
        out = []
        for v in values:
            if self.is_prior(v):
                out.append(v.strip())
            else:
                out += [tok for tok in split(v) if self.is_prior(tok)]
        return out

    # ---- one work -> a node ---------------------------------------------
    def classify(self, concepts: Concepts):
        """The best node for one work: most '+' terms first, then file order. None = no rule."""
        best = None
        for order, (path, rules) in enumerate(self.nodes.items()):
            for terms in rules:
                if all(concepts.has(t) for t in terms):
                    cand = (-len(terms), order)
                    if best is None or cand < best[0]:
                        best = (cand, path)
        return best[1] if best else None

    # ---- an album -------------------------------------------------------
    def decide(self, votes, total: int):
        """votes: one node per distinct work that matched a rule; total: distinct works on the album.
        Too few matched works -> None; a clear majority -> that node; otherwise the lowest common
        ancestor's Varios / Otros child (else the ancestor itself)."""
        n = len(votes)
        if not n or not total or n / total < self.opts["min_coverage"]:
            return None
        counts = Counter(path_key(v) for v in votes)
        top, top_n = min(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if top_n / n >= self.opts["majority"]:
            sure = top_n == n and n / total >= 0.8
            return Decision(self.keys[top], "medium" if sure else "low",
                            "unanimous" if top_n == n else "majority", top_n, total)
        path = self._common(list(counts))
        return Decision(path, "low", "common", n, total) if path else None

    def _common(self, keys):
        parts = [k.split(SEP) for k in keys]
        prefix = []
        for level in zip(*parts):
            if len(set(level)) != 1:
                break
            prefix.append(level[0])
        lca = SEP.join(prefix)
        if not lca:
            return None
        for child in FALLBACK_CHILDREN:
            if lca + SEP + child in self.keys:
                return self.keys[lca + SEP + child]
        while lca and lca not in self.keys:
            lca = SEP.join(lca.split(SEP)[:-1])
        return self.keys.get(lca)

    def _varios(self):
        """The root's Varios / Otros child (else the root itself)."""
        rk = path_key(self.root)
        for child in FALLBACK_CHILDREN:
            if rk + SEP + child in self.keys:
                return self.keys[rk + SEP + child]
        return self.root

    def album_decision(self, works, fallback=None):
        """works: {work key: Concepts}. fallback: Concepts of the album text, tried only when the
        works alone decide nothing (no rule matched, or too few works matched)."""
        votes = [p for c in works.values() for p in [self.classify(c)] if p]
        d = self.decide(votes, len(works))
        if d is None and fallback is not None:
            p = self.classify(fallback)
            if p:
                return Decision(p, "low", "album-text", 1, 1)
        return d

    def resolve(self, decision, priors):
        """Decision + the album's current hierarchy paths (Counter) -> Result, or None = leave
        the tags alone."""
        prior = min(priors.items(), key=lambda kv: (-kv[1], path_key(kv[0])))[0] if priors else None
        pk = path_key(prior) if prior else ""
        if self.opts["existing"] == "keep" and SEP in pk:
            return None                                      # a real path is there: keep it
        if decision is None:
            mode = self.opts["no_match"]
            if mode == "varios":                             # never leave an album on the bare root
                if prior and SEP in pk:
                    return Result(self.keys[pk], "high", None) if pk in self.keys and prior != self.keys[pk] else None
                return Result(self._varios(), "low", None)
            if prior or mode != "root":
                return None
            return Result(self.root, "low", None)
        new, nk = decision.path, path_key(decision.path)
        if not pk or nk == pk or is_ancestor(pk, nk):
            return Result(new, decision.conf, None)          # first path / spelling / refinement
        if is_ancestor(nk, pk):
            return None                                      # the file already says more
        return Result(new, "low", prior)                     # the tags disagree: you decide


def swap_classical(genres, path):
    """Replace the first 'Classical' in a GENRE list by the path (order kept, no repeats)."""
    out, done = [], False
    for g in genres:
        if g == "Classical":
            if done:
                continue
            g, done = path, True
        if g not in out:
            out.append(g)
    return out


# --------------------------------------------------------------------------- #
# The standard tree                                                            #
# --------------------------------------------------------------------------- #
# (path, rules). Spelling follows the common Spanish player convention; analyze_tags re-roots
# it and re-spells the nodes you already have. Nodes marked (std) are not in every library.
STANDARD_TREE = OrderedDict([
    ("Clásica", []),
    ("Clásica\\Antigua", ["period:medieval", "period:renaissance"]),
    ("Clásica\\Conciertos\\Piano", ["concerto+piano"]),
    ("Clásica\\Conciertos\\Violin", ["concerto+violin"]),
    ("Clásica\\Conciertos\\Cello", ["concerto+cello"]),
    ("Clásica\\Conciertos\\Clarinete", ["concerto+clarinet"]),
    ("Clásica\\Conciertos\\Clave", ["concerto+harpsichord"]),
    ("Clásica\\Conciertos\\Varios", ["concerto"]),
    ("Clásica\\Cámara\\Clave Solo", ["harpsichord", "composer:scarlatti", "composer:couperin"]),
    ("Clásica\\Cámara\\Sonatas Violin", ["sonata+violin", "partita+violin"]),
    ("Clásica\\Cámara\\Sonatas Cello", ["sonata+cello", "suite+cello"]),
    ("Clásica\\Cámara\\Piano Solo", ["sonata+piano", "keyboard_form", "piano+solo"]),
    ("Clásica\\Cámara\\Cuartetos", ["quartet"]),
    ("Clásica\\Cámara\\Tríos", ["trio"]),
    ("Clásica\\Cámara\\Quinteto De Cuerda", ["quintet"]),
    ("Clásica\\Cámara\\Otros", ["chamber"]),
    ("Clásica\\Orquestal\\Sinfonias", ["symphony"]),
    ("Clásica\\Orquestal\\Barroco", ["period:baroque+symphony", "concerto_grosso+period:baroque",
                                     "period:baroque+orchsuite"]),
    ("Clásica\\Orquestal\\Otros", ["overture", "tone_poem", "orchsuite", "serenade"]),
    ("Clásica\\Escénica\\Ópera", ["opera"]),
    ("Clásica\\Escénica\\Ballet", ["ballet"]),
    ("Clásica\\Vocal\\Lied", ["lied"]),
    ("Clásica\\Religiosa\\Misa", ["mass", "requiem"]),
    ("Clásica\\Religiosa\\Otros", ["sacred"]),
    ("Clásica\\Varios", []),
])
STANDARD_ROOT = "Clásica"


def rebase(root: str, nodes=None) -> "OrderedDict":
    """The standard tree under another root name ('Clásica' -> 'Música Clásica')."""
    out = OrderedDict()
    for path, rules in (nodes or STANDARD_TREE).items():
        out[root + path[len(STANDARD_ROOT):] if path.startswith(STANDARD_ROOT) else path] = list(rules)
    return out


def detect_root(library) -> str:
    """The first path segment most of your tracks use (spelling of its most common form)."""
    weight, spell = Counter(), {}
    for path, (_, tracks) in library.items():
        seg = path.split(SEP)[0].strip()
        weight[path_key(seg)] += tracks
        spell.setdefault(path_key(seg), seg)
    return spell[weight.most_common(1)[0][0]] if weight else STANDARD_ROOT


Comparison = namedtuple("Comparison", "rows absent seed root")


def compare(library, root=None, standard=None) -> Comparison:
    """Your tree against the standard one.

    library: {path as written: (albums, tracks)}.
    rows:    [(path, albums, tracks, status, standard path or None)] with status
             'same' | 'accents/case' | 'extends' | 'not in standard'.
    absent:  standard nodes your library has no match for.
    seed:    [(path, rule strings, origin, albums, tracks)] - the [classical_rules] to write:
             standard nodes in your spelling, then your own nodes (no rules), then the rest."""
    root = root or detect_root(library)
    std = rebase(root, standard or STANDARD_TREE)
    std_by_key = {path_key(p): p for p in std}
    lib_by_key = {path_key(p): p for p in library}
    matched, status = {}, {}                                   # std key -> library path / library path -> (status, std)
    for lk, lp in lib_by_key.items():
        if lk in std_by_key:
            matched[lk] = lp
            status[lp] = ("same" if lp == std_by_key[lk] else "accents/case", std_by_key[lk])
    for lk, lp in sorted(lib_by_key.items()):                  # 'Sonatas Violin Y Piano' extends 'Sonatas Violin'
        if lp in status:
            continue
        parent, leaf = path_key(parent_of(lp)), path_key(leaf_of(lp))
        best = None
        for sk, sp in std_by_key.items():
            sleaf = path_key(leaf_of(sp))
            if sk not in matched and path_key(parent_of(sp)) == parent and leaf.startswith(sleaf + " ") \
                    and (best is None or len(sleaf) > len(best[1])):
                best = (sk, sleaf)
        if best:
            matched[best[0]] = lp
            status[lp] = ("extends", std_by_key[best[0]])
        else:
            status[lp] = ("not in standard", None)

    rows = [(p, *library[p], *status[p]) for p in sorted(library, key=path_key)]
    absent = [p for k, p in std_by_key.items() if k not in matched]
    seed = []
    for k, sp in std_by_key.items():
        if k in matched:
            lp = matched[k]
            seed.append((lp, std[sp], "std", *library[lp]))
    own = [p for p in library if status[p][0] == "not in standard"]
    for p in sorted(own, key=lambda p: (-library[p][1], path_key(p))):
        seed.append((p, [], "mine", *library[p]))
    seed += [(p, std[p], "absent", 0, 0) for p in absent]
    return Comparison(rows, absent, seed, root)
