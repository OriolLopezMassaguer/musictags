"""
album_names.py - classical album naming:

    {composer} - {works} ({performers})

    Bach - Cello Suites Nos. 1–6 (Pablo Casals)
    Beethoven - Symphonies Nos. 5 & 7 (BPhO / Herbert von Karajan)
    Beethoven - Violin Concerto, Op. 61 (Anne-Sophie Mutter; BPhO / Herbert von Karajan)

* performers: soloist(s) by name; orchestra/ensemble as a 4-letter code + conductor
* works: summary of the works on the album (grouped by type and number)
"""
from __future__ import annotations

import re
from collections import Counter

from core import fold, name_key, nice_case, person_sort

# --------------------------------------------------------------------------- #
# Who is who                                                                   #
# --------------------------------------------------------------------------- #
# substrings (accent/case folded) that identify an orchestra / ensemble / choir
ENSEMBLE_SUBSTR = [
    "orchest", "orquest", "orkest", "philharm", "filharm", "filarm", "symphon", "sinfon",
    "simfon", "ensemble", "consort", "quartet", "quatuor", "cuarteto", "quintet", "sextet",
    "choir", "chorus", "chorale", "kammer", "chamber", "camerata", "academy", "akademie",
    "academia", "players", "kapelle", "capella", "cappella", "collegium", "musici", "solisti",
    "soloists", "virtuosi", "sinfonietta", "gewandhaus", "concertgebouw", "concert des",
    "concerto koln", "concerto italiano", "armonico", "petite bande", "hesperion",
    "arts florissants", "musica antiqua", "le concert", "english concert", "concert spirituel", "banda municipal", "escolania", "singers", "voices",
]
ENSEMBLE_WORDS = {"chor", "coro", "cor", "trio", "band", "opera", "orfeo", "orfeon"}

KNOWN_CONDUCTORS = [
    "Herbert von Karajan", "Leonard Bernstein", "Claudio Abbado", "Georg Solti", "Daniel Barenboim",
    "Simon Rattle", "Riccardo Muti", "Zubin Mehta", "Seiji Ozawa", "Sergiu Celibidache",
    "Wilhelm Furtwängler", "Arturo Toscanini", "Otto Klemperer", "Karl Böhm", "Carlos Kleiber",
    "Erich Kleiber", "Bernard Haitink", "John Eliot Gardiner", "Nikolaus Harnoncourt", "Jordi Savall",
    "Riccardo Chailly", "Gustavo Dudamel", "Valery Gergiev", "Mariss Jansons", "Christian Thielemann",
    "Andris Nelsons", "Kirill Petrenko", "Eugene Ormandy", "George Szell", "Fritz Reiner",
    "Lorin Maazel", "Pierre Boulez", "Roger Norrington", "Trevor Pinnock", "Christopher Hogwood",
    "Ton Koopman", "Philippe Herreweghe", "René Jacobs", "Marc Minkowski", "William Christie",
    "Teodor Currentzis", "Esa-Pekka Salonen", "Michael Tilson Thomas", "André Previn",
    "Neville Marriner", "Colin Davis", "Paavo Järvi", "Neeme Järvi", "Daniele Gatti",
    "Antonio Pappano", "Yannick Nézet-Séguin", "Myung-whun Chung", "Josep Pons",
    "Rafael Frühbeck de Burgos", "Antoni Ros-Marbà", "Ataúlfo Argenta", "Jesús López Cobos",
    "Klaus Mäkelä", "Iván Fischer", "Adam Fischer", "Fabio Luisi", "Franz Welser-Möst",
    "Bruno Walter", "Eugen Jochum", "Rafael Kubelík", "Evgeny Mravinsky", "Yevgeny Mravinsky",
    "Günter Wand", "Kurt Masur", "Charles Dutoit", "Pablo Heras-Casado", "Gustavo Gimeno",
    "Jaime Martín", "Víctor Pablo Pérez", "Juanjo Mena", "Edmon Colomer", "Vasily Petrenko",
    "Riccardo Minasi", "Giovanni Antonini", "Fabio Biondi", "Rinaldo Alessandrini",
]
KNOWN_CONDUCTOR_KEYS = {name_key(n) for n in KNOWN_CONDUCTORS}
CONDUCTOR_MARK = re.compile(r"\b(?:cond(?:uctor|\.)?|dir(?:ector|\.|igent|igida|igido)?|"
                            r"conducted by|leitung|direcci[oó]n|direcci[oó])\b", re.I)
ROLE_PAREN = re.compile(r"\s*[\(\[]([^\)\]]+)[\)\]]\s*$")


def strip_role(name: str) -> tuple[str, str]:
    """'Pablo Casals (cello)' -> ('Pablo Casals', 'cello')."""
    m = ROLE_PAREN.search(name)
    if m:
        return name[:m.start()].strip(), m.group(1).strip()
    m = re.match(r"^(?:cond\.|dir\.|conducted by)\s+(.+)$", name.strip(), re.I)
    if m:
        return m.group(1).strip(), "conductor"
    return name.strip(), ""


def is_ensemble(name: str) -> bool:
    f = fold(name)
    if any(s in f for s in ENSEMBLE_SUBSTR):
        return True
    return bool(set(re.findall(r"\w+", f)) & ENSEMBLE_WORDS)


def classify(name: str, conductors: set[str]) -> tuple[str, str]:
    """-> (clean name, 'conductor' | 'ensemble' | 'soloist')"""
    clean, role = strip_role(name)
    if CONDUCTOR_MARK.search(role) or name_key(clean) in conductors or name_key(clean) in KNOWN_CONDUCTOR_KEYS:
        return clean, "conductor"
    if is_ensemble(clean):
        return clean, "ensemble"
    return clean, "soloist"


# --------------------------------------------------------------------------- #
# 4-letter orchestra codes                                                     #
# --------------------------------------------------------------------------- #
BUILTIN_CODES = {
    "Berliner Philharmoniker": "BPhO", "Berlin Philharmonic Orchestra": "BPhO",
    "Berlin Philharmonic": "BPhO",
    "Wiener Philharmoniker": "WPhO", "Vienna Philharmonic Orchestra": "WPhO", "Vienna Philharmonic": "WPhO",
    "Wiener Symphoniker": "WSym", "Vienna Symphony Orchestra": "WSym",
    "London Symphony Orchestra": "LSyO", "London Philharmonic Orchestra": "LPhO",
    "Royal Philharmonic Orchestra": "RPhO", "Philharmonia Orchestra": "PhiO",
    "Royal Concertgebouw Orchestra": "RCGO", "Koninklijk Concertgebouworkest": "RCGO",
    "Concertgebouw Orchestra": "RCGO", "Concertgebouw Orchestra of Amsterdam": "RCGO",
    "Chicago Symphony Orchestra": "CSyO", "New York Philharmonic": "NYPh",
    "Boston Symphony Orchestra": "BSyO", "The Philadelphia Orchestra": "Phla",
    "Philadelphia Orchestra": "Phla", "The Cleveland Orchestra": "Clev", "Cleveland Orchestra": "Clev",
    "Staatskapelle Dresden": "SKDr", "Sächsische Staatskapelle Dresden": "SKDr",
    "Staatskapelle Berlin": "SKBe", "Gewandhausorchester Leipzig": "GWHL",
    "Gewandhausorchester": "GWHL", "Leipzig Gewandhaus Orchestra": "GWHL",
    "Symphonieorchester des Bayerischen Rundfunks": "BRSO",
    "Bavarian Radio Symphony Orchestra": "BRSO", "Orchestre de Paris": "OdPa",
    "Orquestra Simfònica de Barcelona i Nacional de Catalunya": "OBNC",
    "Orquesta Sinfónica de Barcelona y Nacional de Cataluña": "OBNC",
    "Orquesta Nacional de España": "ONdE", "Orquesta Sinfónica de RTVE": "ORTV",
    "Orquesta y Coro Nacionales de España": "OCNE",
    "Academy of St Martin in the Fields": "ASMF", "Academy of St. Martin in the Fields": "ASMF",
    "English Baroque Soloists": "EBSo", "Orchestra of the Age of Enlightenment": "OAEn",
    "Le Concert des Nations": "CdNa", "Mahler Chamber Orchestra": "MChO",
    "Chamber Orchestra of Europe": "COEu", "Israel Philharmonic Orchestra": "IPhO",
    "Budapest Festival Orchestra": "BFeO", "Orchestre Révolutionnaire et Romantique": "ORRo",
    "Les Arts Florissants": "ArFl", "Il Giardino Armonico": "GiAr", "Hespèrion XXI": "HXXI",
    "Freiburger Barockorchester": "FBaO", "Mariinsky Orchestra": "Mari",
    "Orchestra Mozart": "OMoz", "Lucerne Festival Orchestra": "LFeO",
    "Los Angeles Philharmonic": "LAPh", "San Francisco Symphony": "SFSy",
    "St. Petersburg Philharmonic Orchestra": "SPPh", "Academy of Ancient Music": "AAMu",
    "The English Concert": "EnCo", "Akademie für Alte Musik Berlin": "AAMB",
    "Orquesta Sinfónica de Galicia": "OSGa", "Orquesta de Cadaqués": "OCad",
}
STOP = {"of", "the", "de", "del", "dels", "la", "le", "les", "des", "di", "della", "du", "fur",
        "and", "und", "et", "y", "i", "a", "l", "d", "der", "das", "die", "st", "san", "saint"}


def generate_code(name: str) -> str:
    words = [w for w in re.findall(r"[^\W\d_]+|\d+", name) if fold(w) not in STOP] or [name]
    if len(words) >= 4:
        code = "".join(w[0] for w in words[:4])
        return code[0].upper() + code[1:].upper()
    if len(words) == 3:
        return words[0][:2].capitalize() + words[1][0].upper() + words[2][0].upper()
    if len(words) == 2:
        return words[0][:2].capitalize() + words[1][:2].capitalize()
    return words[0][:4].capitalize()


class OrchestraCodes:
    def __init__(self, user_table: dict[str, str] | None = None):
        self.table = {name_key(k): v for k, v in BUILTIN_CODES.items()}
        self.table.update({name_key(k): v for k, v in (user_table or {}).items()})

    def __call__(self, name: str) -> str:
        return self.table.get(name_key(name)) or generate_code(name)

    def unique_table(self, names) -> dict[str, str]:
        """Codes for a set of names, made unique (used by analyze_tags)."""
        out, used = {}, {}
        for n in names:
            code = self(n)
            if code in used and used[code] != name_key(n) and name_key(n) not in self.table:
                letters = re.sub(r"[^\w]", "", n)
                for i in range(2, len(letters)):
                    alt = (code[:3] + letters[i]).capitalize() if code[:1].isupper() else code[:3] + letters[i]
                    if alt not in used:
                        code = alt
                        break
            used.setdefault(code, name_key(n))
            out[n] = code
        return out


# --------------------------------------------------------------------------- #
# Works                                                                        #
# --------------------------------------------------------------------------- #
ROMAN = r"(?:[IVXLC]+|\d+)"
_ACC = r"(?:[- ]?(?:flat|sharp|b[eé]mol|sostenido|dièse|♭|♯)|is|es)?"
KEY_RE = re.compile(
    r",?\s+(?i:in|en|em)\s+(?:[A-Ha-h]" + _ACC + r"[- ](?i:major|minor|mayor|menor|dur|moll|majeur|mineur|maggiore|minore)"
    r"|(?i:do|re|mi|fa|sol|la|si)" + _ACC + r"\s+(?i:mayor|menor|majeur|mineur|maggiore|minore)"
    r"|[A-H]" + _ACC + r")\b")
KEY_DE = re.compile(r",?\s+[A-Ha-h](?:is|es|s)?-(?:Dur|Moll|dur|moll)\b")
CATALOG_RE = re.compile(r"(?:,\s*|\s+)\b(?:Op|Opus|BWV|KV|K|Hob|D|RV|HWV|WoO|S|L|TWV|BuxWV|Sz|M|FS|JW|B)"
                        r"\.?\s*(?:[IVX]+\s*:\s*)?\d+[a-z]?(?:\s*(?:No\.?|Nr\.?)\s*\d+)?\s*$", re.I)
NUM_RE = re.compile(r"^(?P<type>.+?)\s+(?:No\.?|Nr\.?|N[º°o]\.?|n\.?º|núm\.?|num\.?|#)\s*(?P<num>\d+)\b(?P<rest>.*)$", re.I)
MVT_RE = re.compile(rf"^(?P<work>.+?)\s*(?:[:\-–—/]|,)\s*(?:{ROMAN}|[a-z])\s*[\.\)]\s+(?P<mvt>.+)$")


def short_work(w: str, keep_catalog: bool) -> str:
    s = KEY_DE.sub("", KEY_RE.sub("", w)).strip(" ,")
    if not keep_catalog:
        prev = None
        while prev != s:
            prev, s = s, CATALOG_RE.sub("", s).strip(" ,")
    return re.sub(r"\s{2,}", " ", s)


def plural(t: str) -> str:
    m = re.search(r"\s+(?:for|para|pour|für|per)\s+", t)
    head, tail = (t[:m.start()], t[m.start():]) if m else (t, "")
    words = head.split()
    if not words:
        return t
    w = words[-1]
    if re.search(r"[^aeiou]y$", w):
        w = w[:-1] + "ies"
    elif re.search(r"(s|x|z|ch|sh)$", w):
        w = w + "es" if not w.endswith("s") else w
    else:
        w = w + "s"
    return " ".join(words[:-1] + [w]) + tail


def _numbers(nums: list[int]) -> str:
    nums = sorted(set(nums))
    if len(nums) == 2:
        return f"{nums[0]} & {nums[1]}"
    parts, start = [], nums[0]
    for a, b in zip(nums, nums[1:] + [None]):
        if b != a + 1:
            parts.append(str(start) if start == a else f"{start}–{a}")
            start = b
    return ", ".join(parts)


def strip_composer(text: str, composers, bare: bool = False) -> str:
    """'Bach: Cello Suite No. 1' -> 'Cello Suite No. 1' (also 'J.S. Bach - ...'). With `bare`,
    a composer at the head of a folder name goes too ('Mozart Requiem' -> 'Requiem'): the album
    name prints the composer itself, so keeping it there would say it twice."""
    t = text.strip()
    for c in composers:                               # 'Bach: ...' / 'J.S. Bach - ...'
        if not c.strip():
            continue
        for n in sorted({c, c.split()[-1], person_sort(c).split(",")[0]}, key=len, reverse=True):
            m = re.match(rf"^{re.escape(n)}\s*[:\-–]\s*(.+)$", t, re.I)
            if m:
                return m.group(1).strip()
            if bare:
                m = re.match(rf"^{re.escape(n)}\b[\s_]+(\S.{{2,}})$", t, re.I)
                if m:
                    return m.group(1).strip()
    return t


def work_of_title(title: str, composers: list[str]) -> tuple[str | None, str]:
    """Return (work, how) from a track title, or (None, '')."""
    t = strip_composer(title, composers)
    m = MVT_RE.match(t)
    if m:
        return m.group("work").strip(), "movement"
    return None, ""


# --------------------------------------------------------------------------- #
# Titles that name nothing                                                     #
# --------------------------------------------------------------------------- #
# What a ripper writes when the CD had no metadata: 'Pista01', 'Track 02', '1-04',
# 'Untitled 3'. They are numbering, not names, so they must never become a work, a WORK
# tag or a vote in the genre tree -- the album or its folder is then all there is to go on.
TRACK_WORD = (r"(?:pistas?|pistes?|tracks?|traccia|tracce|faixas?|spur(?:en)?|titel|t[ií]tulos?|"
              r"audio\s*track|cdda?\s*track|audiotrack|tema|corte|nummer|st[uü]ck|trk|tr)")
DISC_WORD = r"(?:cd|cds|disc|disco|disque|disk|dvd|vol(?:ume|umen)?|v)"
PLACEHOLDER_TITLE = re.compile(rf"""^\s*
    (?:{DISC_WORD}\s*\.?\s*\d{{1,2}}\s*[-_.:]?\s*)?    # optional 'CD2 - ' prefix
    (?:
        {TRACK_WORD}\s*[-_.#]?\s*\d{{1,3}}[a-z]?       # Pista01 / Track 2 / Spur-3
      | \d{{1,3}}\s*[-_.]?\s*{TRACK_WORD}              # 01 Track
      | \d{{1,3}}(?:\s*[-_.]\s*\d{{1,3}})?             # 07 / 1-04
      | (?:un)?titled\s*\d*
      | sin\s*t[ií]tulo\s*\d*
      | (?:no|without)\s*(?:title|name)\s*\d*
      | (?:unknown|desconocid[oa])(?:\s*(?:track|pista))?\s*\d*
    )
    \s*$""", re.I | re.X)
DISC_ONLY = re.compile(rf"^\s*{DISC_WORD}\s*\.?\s*\d{{0,3}}\s*$", re.I)
# an explicit disc / volume marker at the end of an album or folder name: ' CD 2', ' Vol. 3', ' v1'
DISC_TAIL = re.compile(rf"""[\s,;:._/(\[-]+{DISC_WORD}\.?\s*
                           (\d{{1,2}})(?:\s*(?:of|de|/)\s*\d{{1,2}})?[)\]]*\s*$""", re.I | re.X)


def is_placeholder(title: str) -> bool:
    """True for a title that names nothing: 'Pista01', 'Track 2', '05', 'Untitled'."""
    return bool(title and PLACEHOLDER_TITLE.match(title))


def _tidy(s: str) -> str:
    s = re.sub(r"\s*[\(\[]\s*[\)\]]", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip(" ,;:-–_/.")


def _forms(name: str):
    """The spellings of a person to look for in a free text: full name and surname."""
    parts = name.split()
    return {f for f in {name, person_sort(name).split(",")[0], parts[-1] if parts else name}
            if len(f) >= 4}                           # 'Ax', 'LSO': too short to match safely


def _drop_names(text: str, names) -> str:
    """Remove performer names ('Requiem Solti' -> 'Requiem'), never emptying the text."""
    for n in names:
        for form in _forms(n):
            cut = re.sub(rf"(?<!\w){re.escape(form)}(?!\w)", " ", text, flags=re.I)
            if _tidy(cut):
                text = cut
    return text


def _only_names(text: str, names) -> bool:
    """True for '(Fricsay)' / '(Karajan 1958)': nothing but performers and years."""
    t = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    for n in names:
        for form in _forms(n):
            t = re.sub(rf"(?<!\w){re.escape(form)}(?!\w)", " ", t, flags=re.I)
    return not _tidy(t)


def _clean_work(text: str, composers, performers) -> tuple[str, str]:
    """One candidate text -> (work, disc number) or ('', '')."""
    s = strip_composer(text.strip(), composers, bare=True)
    m = re.search(r"\s*\(([^()]*)\)\s*$", s)               # trailing '(Fricsay)' / '(1958)'
    if m and _only_names(m.group(1), performers) and _tidy(s[:m.start()]):
        s = _tidy(s[:m.start()])
    # drop our own 'Pista01, Pista02, etc.' if this text was built by a previous run
    parts = [x for x in re.split(r"\s*,\s*", s)
             if not is_placeholder(x) and fold(x).strip(". ") not in ("etc", "")]
    s = _tidy(", ".join(parts))
    m = DISC_TAIL.search(s)
    disc = m.group(1) if m else ""
    if m and _tidy(s[:m.start()]):
        s = _tidy(s[:m.start()])
    s = _tidy(_drop_names(s, performers))
    if len(s) >= 3 and not is_placeholder(s) and not DISC_ONLY.match(s):
        return nice_case(s), disc
    return "", ""


def work_of_text(texts, composers=(), performers=()) -> tuple[str, str]:
    """The work of an album whose titles say nothing, read from the folder name or the album
    tag -- the only places left that can still name it:

        'Don Giovanni 1'          -> ('Don Giovanni 1', '')
        'Mozart_ Requiem Solti'   -> ('Requiem', '')
        'Cello concertos Vol. 4'  -> ('Cello concertos', '4')

    Returns ('', '') when none of `texts` says anything either. The second value is the disc /
    volume number taken off the end, which album_names uses to tell the discs of a set apart.
    A bare trailing number is left in place: 'Symphony 40' is a name, not a disc number.
    """
    for raw in texts:
        if not raw or DISC_ONLY.match(raw):
            continue
        s = re.sub(r"_(?=\s|$)", ":", raw.strip())            # iTunes writes ':' as '_'
        bracket = ""
        m = re.search(r"\s*\[([^\[\]]*)\]\s*$", s)            # a name we wrote before: '... [X]'
        if m:
            bracket = m.group(1)                              # the last thing to try
            s = _tidy(s[:m.start()]) or s
        for cand in (s, bracket):
            work, disc = _clean_work(cand, composers, performers) if cand else ("", "")
            if work:
                return work, disc
    return "", ""


def summarize_works(works: list[str], max_items: int = 3, others: str = "etc.") -> str:
    """`works` may hold None for a track whose title named no work ('Pista01')."""
    works = [w for w in dict.fromkeys(w.strip() for w in works if w) if w]
    if not works:
        return ""
    if len(works) == 1:
        return short_work(works[0], keep_catalog=True)
    groups: dict[str, list[int]] = {}
    order: list[str] = []
    for w in works:
        s = short_work(w, keep_catalog=False)
        m = NUM_RE.match(s)
        key = m.group("type").strip() if m else s
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(int(m.group("num")) if m else 0)   # 0 = unnumbered occurrence
    items = []
    for key in order:
        nums = [n for n in groups[key] if n]
        if not nums and len(groups[key]) > 1:
            items.append(plural(key))
        elif len(set(nums)) > 1:
            items.append(f"{plural(key)} Nos. {_numbers(nums)}")
        elif nums:
            items.append(f"{key} No. {nums[0]}")
        else:
            items.append(key)
    if len(items) > max_items:
        return ", ".join(items[: max_items - 1]) + f", {others}"
    if len(items) == 2:
        return f"{items[0]} & {items[1]}"
    return ", ".join(items[:-1]) + f" & {items[-1]}" if len(items) > 1 else items[0]


# --------------------------------------------------------------------------- #
# Album name                                                                   #
# --------------------------------------------------------------------------- #
def short_person(name: str, mode: str, sort_overrides: dict | None = None) -> str:
    if mode == "full":
        return name
    s = (sort_overrides or {}).get(name_key(name)) or person_sort(name)
    return s.split(",")[0].strip()


def performers_text(soloists: Counter, ensembles: Counter, conductors: Counter, codes: OrchestraCodes,
                    cfg: dict, n_tracks: int) -> str:
    """'Anne-Sophie Mutter; BPhO / Herbert von Karajan'"""
    min_share = float(cfg.get("min_share", 0.5))
    keep = lambda c: [n for n, k in c.most_common() if k >= max(1, min_share * n_tracks)] or \
        [n for n, _ in c.most_common(1)]
    sol = keep(soloists) if soloists else []
    ens = keep(ensembles) if ensembles else []
    con = keep(conductors) if conductors else []
    max_sol = int(cfg.get("max_soloists", 2))
    if len(sol) > max_sol:
        sol = sol[:max_sol] + [cfg.get("others", "etc.")]
    smode = cfg.get("soloist_name", "full")
    cmode = cfg.get("conductor_name", "full")
    parts = [", ".join(short_person(s, smode) if s != cfg.get("others", "etc.") else s for s in sol)] if sol else []
    group = " / ".join(x for x in (", ".join(codes(e) for e in ens[:2]),
                                   ", ".join(short_person(c, cmode) for c in con[:1])) if x)
    if group:
        parts.append(group)
    return "; ".join(parts)


def composer_text(composers: Counter, cfg: dict, sort_overrides=None) -> str:
    names = [n for n, _ in composers.most_common()]
    if not names:
        return ""
    if len(names) > int(cfg.get("max_composers", 3)):
        return cfg.get("various_composers", "Varios")
    return ", ".join(short_person(n, cfg.get("composer_name", "surname"), sort_overrides) for n in names)


def build_name(fmt: str, composer: str, works: str, performers: str) -> str:
    s = fmt.format(composer=composer, works=works, performers=performers)
    s = re.sub(r"\s*[\(\[]\s*[\)\]]", "", s)               # empty "()"
    s = re.sub(r"^\s*[-–:]\s*|\s*[-–:]\s*$", "", s)         # dangling separators
    return re.sub(r"\s{2,}", " ", s).strip()
