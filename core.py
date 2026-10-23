"""
core.py - shared code for the music tagging toolkit.

* Canonical field set and per-format mapping (ID3 / Vorbis / MP4)
* read_tags(path) -> {field: [values]}
* write_tags(path, {field: [values]})   ([] deletes the field)
* name / genre normalisation helpers
* cooperative interruption: handle_interrupts() / check_stop()
* built-in seed data: classical composers and genre keywords
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import unicodedata
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # pip install tomli

import mutagen
from mutagen.id3 import ID3, ID3NoHeaderError, Frames, TXXX
from mutagen.mp4 import MP4, MP4FreeForm

# --------------------------------------------------------------------------- #
# Cooperative interruption                                                     #
# --------------------------------------------------------------------------- #
# Ctrl-C (SIGINT) and the GUI's "Parar" button (SIGTERM) must never kill a step
# in the middle of a tag write or a database commit: a half-written file is the
# one damage this toolkit cannot undo. So the handler does nothing but raise a
# flag; the long loops ask check_stop() (or stopping()) where stopping is safe,
# and main() turns that into a normal summary and exit code 130. The handler
# then steps aside, so signalling a second time still kills a wedged run.

EXIT_INTERRUPTED = 130


class Interrupted(Exception):
    """Raised by check_stop() once a stop was asked for, at a safe point."""


_STOP = False


def handle_interrupts(note="\nStopping at the next safe point "
                           "(signal again to force)..."):
    """Install the SIGINT/SIGTERM handlers. Call it first thing in main()."""
    def ask_stop(signum, _frame):
        global _STOP
        _STOP = True
        signal.signal(signum, signal.SIG_DFL)      # a second one kills us
        if note:
            print(note, file=sys.stderr, flush=True)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, ask_stop)
        except ValueError:                         # not the main thread
            pass


def stopping():
    """True once a stop was asked for -- for loops that clean up themselves."""
    return _STOP


def check_stop():
    """Raise Interrupted if a stop was asked for. Safe points only."""
    if _STOP:
        raise Interrupted()


AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".m4b"}
LIST_SEP = " || "  # how lists are shown in CSV files

# --------------------------------------------------------------------------- #
# Canonical fields                                                             #
# --------------------------------------------------------------------------- #
# field: (ID3 frame, Vorbis key, MP4 atom)
FIELD_MAP = {
    "title":           ("TIT2", "TITLE", "\xa9nam"),
    "artist":          ("TPE1", "ARTIST", "\xa9ART"),
    "artists":         ("TXXX:ARTISTS", "ARTISTS", "----:com.apple.iTunes:ARTISTS"),
    "albumartist":     ("TPE2", "ALBUMARTIST", "aART"),
    "album":           ("TALB", "ALBUM", "\xa9alb"),
    "artistsort":      ("TSOP", "ARTISTSORT", "soar"),
    "albumartistsort": ("TSO2", "ALBUMARTISTSORT", "soaa"),
    "composer":        ("TCOM", "COMPOSER", "\xa9wrt"),
    "composersort":    ("TSOC", "COMPOSERSORT", "soco"),
    "conductor":       ("TPE3", "CONDUCTOR", "----:com.apple.iTunes:CONDUCTOR"),
    "ensemble":        ("TXXX:ENSEMBLE", "ENSEMBLE", "----:com.apple.iTunes:ENSEMBLE"),
    "genre":           ("TCON", "GENRE", "\xa9gen"),
    "style":           ("TXXX:STYLE", "STYLE", "----:com.apple.iTunes:STYLE"),
    "work":            ("TXXX:WORK", "WORK", "\xa9wrk"),
    "movementname":    ("MVNM", "MOVEMENTNAME", "\xa9mvn"),
    "movement":        ("MVIN", "MOVEMENT", "\xa9mvi"),
    "date":            ("TDRC", "DATE", "\xa9day"),
    "compilation":     ("TCMP", "COMPILATION", "cpil"),
}
FIELDS = list(FIELD_MAP)
# Fields the toolkit is allowed to change. Everything else is read-only context.
WRITABLE = {"album", "artist", "artists", "albumartist", "artistsort", "albumartistsort",
            "composer", "composersort", "conductor", "ensemble", "genre", "style",
            "work", "movementname", "movement", "compilation"}


def load_config(path: str | os.PathLike) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


PAD_HEADROOM = 16 * 1024      # bytes of free space left after a tag that had to grow


def _kind(audio) -> str:
    if isinstance(audio, MP4):
        return "mp4"
    if isinstance(audio.tags, ID3) or getattr(audio, "mime", [""])[0] == "audio/mp3":
        return "id3"
    return "vorbis"


def open_audio(path):
    audio = mutagen.File(path)
    if audio is None:
        raise ValueError("unsupported or unreadable file")
    return audio


# --------------------------------------------------------------------------- #
# Reading                                                                      #
# --------------------------------------------------------------------------- #
def _clean(values) -> list[str]:
    out = []
    for v in values:
        s = str(v).replace("\x00", "").strip()
        if s:
            out.append(s)
    return out


def read_tags(path) -> tuple[str, dict[str, list[str]]]:
    """Return (format, {field: [values]}) for every canonical field present."""
    audio = open_audio(path)
    kind = _kind(audio)
    tags = audio.tags
    result: dict[str, list[str]] = {}
    if tags is None:
        return kind, result
    for field, (id3k, vk, mp4k) in FIELD_MAP.items():
        vals: list[str] = []
        if kind == "id3":
            for frame in tags.getall(id3k):
                if id3k == "TCON":
                    vals += frame.genres            # resolves "(17)" -> "Rock"
                elif id3k == "TCMP":
                    vals += [str(t) for t in frame.text]
                else:
                    vals += [str(t) for t in frame.text]
        elif kind == "vorbis":
            vals = list(tags.get(vk, [])) or list(tags.get(vk.lower(), []))
        else:  # mp4
            raw = tags.get(mp4k, [])
            if isinstance(raw, bool):
                raw = ["1" if raw else "0"]
            for v in raw if isinstance(raw, list) else [raw]:
                if isinstance(v, bytes):
                    v = v.decode("utf-8", "replace")
                elif isinstance(v, bool):
                    v = "1" if v else "0"
                vals.append(str(v))
        vals = _clean(vals)
        if vals:
            result[field] = vals
    return kind, result


# --------------------------------------------------------------------------- #
# Writing                                                                      #
# --------------------------------------------------------------------------- #
def _padding(info) -> int:
    """mutagen padding callback: info.padding < 0 means the new tag does not fit."""
    return info.padding if info.padding >= 0 else PAD_HEADROOM


def write_tags(path, changes: dict[str, list[str]], id3_version: int = 4) -> None:
    """Apply {field: [values]} to a file. An empty list removes the field."""
    for f in changes:
        if f not in WRITABLE:
            raise ValueError(f"field '{f}' is not writable by this toolkit")
    audio = open_audio(path)
    kind = _kind(audio)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags

    for field, values in changes.items():
        id3k, vk, mp4k = FIELD_MAP[field]
        values = [v for v in values if v != ""]
        if kind == "id3":
            tags.delall(id3k)
            if not values:
                continue
            if id3k.startswith("TXXX:"):
                tags.add(TXXX(encoding=3, desc=id3k[5:], text=values))
            else:
                tags.add(Frames[id3k](encoding=3, text=values))
        elif kind == "vorbis":
            for k in (vk, vk.lower()):
                if k in tags:
                    del tags[k]
            if values:
                tags[vk] = values
        else:
            if mp4k in tags:
                del tags[mp4k]
            if not values:
                continue
            if mp4k.startswith("----:"):
                tags[mp4k] = [MP4FreeForm(v.encode("utf-8")) for v in values]
            elif mp4k == "\xa9mvi":
                tags[mp4k] = [int(values[0].split("/")[0])]
            elif mp4k == "cpil":
                tags[mp4k] = values[0] in ("1", "true", "True")
            else:
                tags[mp4k] = values

    # Padding policy: mutagen only edits in place when the new tag fits the existing padding,
    # otherwise it rewrites the whole audio file. Keep whatever padding there is (never trim it,
    # the default trims big padding and forces a rewrite next time) and, when the tag has to grow,
    # leave generous headroom so later edits are in place. Ogg/Opus .save() takes no padding.
    pad = {"padding": _padding} if kind in ("id3", "mp4") or hasattr(audio, "pictures") else {}
    if kind == "id3":
        if id3_version == 3:
            audio.save(v2_version=3, v23_sep="; ", **pad)
        else:
            audio.save(v2_version=4, **pad)
    else:
        audio.save(**pad)


# --------------------------------------------------------------------------- #
# Normalisation helpers                                                        #
# --------------------------------------------------------------------------- #
def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def fold(s: str) -> str:
    """Case/accent/whitespace-insensitive form."""
    return re.sub(r"\s+", " ", strip_accents(s).casefold()).strip()


def name_key(s: str) -> str:
    """Matching key for people/bands: 'The Beatles' == 'beatles' == 'BEATLES',
    'J. S. Bach' == 'JS Bach', 'Beyoncé' == 'Beyonce', '&' == 'and'."""
    s = fold(s)
    s = re.sub(r"^the\s+", "", s)
    s = re.sub(r",\s*the$", "", s)
    s = s.replace("&", " and ").replace("+", " and ")
    s = re.sub(r"[^\w\s]", " ", s)
    toks = s.split()
    out, buf = [], ""
    for t in toks:                      # glue initials: "j s bach" -> "js bach"
        if len(t) == 1 and t.isalpha():
            buf += t
        else:
            if buf:
                out.append(buf); buf = ""
            out.append(t)
    if buf:
        out.append(buf)
    return " ".join(out)


def genre_key(s: str) -> str:
    s = fold(s).replace("-", " ").replace("_", " ").replace("’", "'")
    s = re.sub(r"[^\w\s&']", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def nice_case(s: str) -> str:
    """Title-case a free text value only if it is all lower or all upper."""
    if s.islower() or (s.isupper() and any(len(w) > 4 for w in re.findall(r"[A-Za-z]+", s))):
        small = {"and", "of", "the", "in", "de", "la", "y", "n"}
        words = s.lower().split()
        return " ".join(w if (i and w in small) else w[:1].upper() + w[1:]
                        for i, w in enumerate(words))
    return s


PARTICLES = {"van", "von", "de", "di", "da", "del", "della", "des", "du", "la", "le",
             "y", "der", "den", "ten", "zu", "dos", "das"}
SUFFIXES = {"ii", "iii", "jr", "jr.", "sr", "sr.", "the elder", "the younger"}


def person_sort(name: str) -> str:
    """'Ludwig van Beethoven' -> 'Beethoven, Ludwig van'; 'Johann Strauss II' -> 'Strauss II, Johann'."""
    toks = name.split()
    if len(toks) < 2:
        return name
    suffix = ""
    if toks[-1].lower().strip(",") in SUFFIXES:
        suffix = " " + toks.pop()
    if len(toks) < 2:
        return name
    surname = toks.pop()
    particles = []
    while toks and toks[-1].lower() in PARTICLES and len(toks) > 1:
        particles.insert(0, toks.pop())
    given = " ".join(toks + particles)
    return f"{surname}{suffix}, {given}"


ARTICLES = ("The ", "A ", "An ", "Los ", "Las ", "Els ", "Les ", "La ", "El ", "Die ")


def band_sort(name: str) -> str:
    """'The Beatles' -> 'Beatles, The'. Leaves other names untouched."""
    for a in ARTICLES:
        if name.startswith(a) and len(name) > len(a) + 1:
            return f"{name[len(a):]}, {a.strip()}"
    return name


# --------------------------------------------------------------------------- #
# Seed data: classical composers                                               #
# --------------------------------------------------------------------------- #
COMPOSERS = {
    "Medieval": ["Hildegard von Bingen", "Guillaume de Machaut", "Pérotin", "Léonin"],
    "Renaissance": ["Josquin des Prez", "Giovanni Pierluigi da Palestrina", "Thomas Tallis",
                    "William Byrd", "Tomás Luis de Victoria", "Orlande de Lassus",
                    "John Dowland", "Cristóbal de Morales", "Francisco Guerrero",
                    "Carlo Gesualdo", "Luis de Milán"],
    "Baroque": ["Johann Sebastian Bach", "George Frideric Handel", "Antonio Vivaldi",
                "Henry Purcell", "Claudio Monteverdi", "Jean-Philippe Rameau",
                "Arcangelo Corelli", "Georg Philipp Telemann", "Domenico Scarlatti",
                "Alessandro Scarlatti", "François Couperin", "Jean-Baptiste Lully",
                "Dietrich Buxtehude", "Johann Pachelbel", "Tomaso Albinoni",
                "Giovanni Battista Pergolesi", "Marc-Antoine Charpentier",
                "Heinrich Biber", "Gaspar Sanz", "Antonio Soler", "Marin Marais",
                "Heinrich Schütz", "Alessandro Marcello", "Giuseppe Tartini"],
    "Classical Period": ["Wolfgang Amadeus Mozart", "Joseph Haydn", "Ludwig van Beethoven",
                         "Christoph Willibald Gluck", "Luigi Boccherini", "Antonio Salieri",
                         "Muzio Clementi", "Fernando Sor", "Johann Nepomuk Hummel",
                         "Carl Philipp Emanuel Bach", "Johann Christian Bach",
                         "Mauro Giuliani", "Juan Crisóstomo Arriaga"],
    "Romantic": ["Franz Schubert", "Robert Schumann", "Clara Schumann", "Felix Mendelssohn",
                 "Frédéric Chopin", "Franz Liszt", "Johannes Brahms", "Richard Wagner",
                 "Giuseppe Verdi", "Pyotr Ilyich Tchaikovsky", "Antonín Dvořák",
                 "Edvard Grieg", "Gustav Mahler", "Anton Bruckner", "Hector Berlioz",
                 "Camille Saint-Saëns", "Gabriel Fauré", "Georges Bizet", "Giacomo Puccini",
                 "Gioachino Rossini", "Gaetano Donizetti", "Vincenzo Bellini",
                 "Modest Mussorgsky", "Nikolai Rimsky-Korsakov", "Alexander Borodin",
                 "César Franck", "Bedřich Smetana", "Johann Strauss II", "Richard Strauss",
                 "Isaac Albéniz", "Enrique Granados", "Pablo de Sarasate", "Edward Elgar",
                 "Jean Sibelius", "Sergei Rachmaninoff", "Carl Nielsen", "Niccolò Paganini",
                 "Carl Maria von Weber", "Jules Massenet", "Hugo Wolf", "Francisco Tárrega",
                 "Ruggero Leoncavallo", "Pietro Mascagni", "Max Bruch", "Ruperto Chapí",
                 "Tomás Bretón", "Federico Chueca"],
    "Modern": ["Claude Debussy", "Maurice Ravel", "Erik Satie", "Igor Stravinsky",
               "Sergei Prokofiev", "Dmitri Shostakovich", "Béla Bartók", "Arnold Schoenberg",
               "Alban Berg", "Anton Webern", "Manuel de Falla", "Joaquín Rodrigo",
               "Federico Mompou", "Heitor Villa-Lobos", "George Gershwin", "Aaron Copland",
               "Leonard Bernstein", "Benjamin Britten", "Ralph Vaughan Williams",
               "Gustav Holst", "Samuel Barber", "Olivier Messiaen", "Francis Poulenc",
               "Paul Hindemith", "Leoš Janáček", "Alexander Scriabin", "Ottorino Respighi",
               "Carl Orff", "Darius Milhaud", "Charles Ives", "Astor Piazzolla",
               "Xavier Montsalvatge", "Joaquín Turina", "Agustín Barrios",
               "Frederick Delius", "Jean Françaix", "Witold Lutosławski"],
    "Contemporary": ["Philip Glass", "Steve Reich", "John Adams", "Arvo Pärt",
                     "Henryk Górecki", "John Cage", "Karlheinz Stockhausen", "György Ligeti",
                     "Pierre Boulez", "Luciano Berio", "Max Richter", "John Tavener",
                     "Morton Feldman", "Terry Riley", "Tōru Takemitsu", "Kaija Saariaho",
                     "Krzysztof Penderecki", "Thomas Adès", "Jóhann Jóhannsson",
                     "Leo Brouwer", "Osvaldo Golijov"],
}
EXTRA_COMPOSER_ALIASES = {
    "Pyotr Ilyich Tchaikovsky": ["Tschaikowsky", "Tchaikowsky", "Chaikovsky", "Peter Tchaikovsky",
                                 "Piotr Ilyich Tchaikovsky", "Pyotr Tchaikovsky"],
    "Sergei Rachmaninoff": ["Rachmaninov", "Rakhmaninov", "Sergei Rachmaninov", "Serguei Rachmaninov"],
    "Sergei Prokofiev": ["Prokofieff", "Serge Prokofiev"],
    "Dmitri Shostakovich": ["Schostakowitsch", "Chostakovitch", "Dmitry Shostakovich"],
    "Igor Stravinsky": ["Strawinsky"],
    "Modest Mussorgsky": ["Moussorgsky", "Musorgsky"],
    "George Frideric Handel": ["Händel", "Haendel", "Georg Friedrich Händel", "Georg Friedrich Handel"],
    "Joseph Haydn": ["Franz Joseph Haydn"],
    "Alexander Scriabin": ["Skryabin", "Scriabine"],
    "Arnold Schoenberg": ["Schönberg", "Arnold Schönberg"],
    "Felix Mendelssohn": ["Mendelssohn Bartholdy", "Felix Mendelssohn Bartholdy", "Mendelssohn-Bartholdy"],
    "Frédéric Chopin": ["Fryderyk Chopin"],
    "Orlande de Lassus": ["Orlando di Lasso", "Lasso", "Lassus"],
    "Josquin des Prez": ["Josquin"],
    "Johann Strauss II": ["Johann Strauss Jr.", "Johann Strauss (Son)", "Johann Strauss"],
    "Wolfgang Amadeus Mozart": ["W. A. Mozart"],
}
# when a bare surname is ambiguous, who does it mean (None = don't guess)
SURNAME_PREFERENCE = {"bach": "Johann Sebastian Bach", "schumann": "Robert Schumann",
                      "scarlatti": "Domenico Scarlatti", "strauss": None}


def composer_period() -> dict[str, str]:
    return {name: period for period, names in COMPOSERS.items() for name in names}


def composer_aliases() -> dict[str, str]:
    """name_key(variant) -> canonical composer name."""
    aliases: dict[str, str] = {}
    surnames: dict[str, list[str]] = {}
    for name in composer_period():
        sort = person_sort(name)
        surname, _, given = sort.partition(", ")
        variants = {name, sort}
        gtoks = [t for t in given.split() if t.lower() not in PARTICLES]
        parts = [t for t in given.split() if t.lower() in PARTICLES]
        if gtoks:
            initials = ".".join(t[0] for t in gtoks) + "."
            tail = " ".join(parts + [surname])
            variants |= {f"{initials} {tail}", f"{surname}, {initials}"}
            if parts:
                variants.add(tail)                      # "de Falla", "van Beethoven"
        for v in variants | set(EXTRA_COMPOSER_ALIASES.get(name, [])):
            aliases[name_key(v)] = name
        surnames.setdefault(name_key(surname.split()[0] if " II" in surname else surname), []).append(name)
    for sk, names in surnames.items():
        if sk in SURNAME_PREFERENCE:
            if SURNAME_PREFERENCE[sk]:
                aliases[sk] = SURNAME_PREFERENCE[sk]
            elif sk in aliases and len(names) > 1:
                aliases.pop(sk, None)
        elif len(names) == 1:
            aliases.setdefault(sk, names[0])
    return aliases


# --------------------------------------------------------------------------- #
# Seed data: genre taxonomy                                                    #
# --------------------------------------------------------------------------- #
TAXONOMY = ["Blues", "Classical", "Country", "Electronic", "Folk", "Hip-Hop", "Jazz",
            "Latin", "Metal", "Pop", "R&B & Soul", "Reggae", "Rock", "Soundtrack",
            "Spoken Word", "World", "Religious", "Children's", "Holiday"]

# keyword (genre_key form) -> top-level genre. Checked in order; first hit wins.
GENRE_KEYWORDS = [
    ("soundtrack", "Soundtrack"), ("score", "Soundtrack"), ("ost", "Soundtrack"),
    ("musical", "Soundtrack"), ("film", "Soundtrack"), ("game", "Soundtrack"), ("bso", "Soundtrack"),
    ("christmas", "Holiday"), ("navidad", "Holiday"), ("nadal", "Holiday"), ("villancico", "Holiday"),
    ("children", "Children's"), ("kids", "Children's"), ("infantil", "Children's"),
    ("audiobook", "Spoken Word"), ("spoken", "Spoken Word"), ("comedy", "Spoken Word"),
    ("podcast", "Spoken Word"), ("poetry", "Spoken Word"),
    ("gospel", "Religious"), ("christian", "Religious"), ("sacred", "Religious"),
    ("metal", "Metal"), ("grindcore", "Metal"), ("djent", "Metal"),
    ("hip hop", "Hip-Hop"), ("hiphop", "Hip-Hop"), ("rap", "Hip-Hop"), ("trap", "Hip-Hop"), ("grime", "Hip-Hop"),
    ("r&b", "R&B & Soul"), ("rnb", "R&B & Soul"), ("r and b", "R&B & Soul"), ("rhythm and blues", "R&B & Soul"),
    ("soul", "R&B & Soul"), ("funk", "R&B & Soul"), ("motown", "R&B & Soul"), ("disco", "R&B & Soul"),
    ("jazz", "Jazz"), ("swing", "Jazz"), ("bebop", "Jazz"), ("bop", "Jazz"), ("big band", "Jazz"),
    ("fusion", "Jazz"), ("dixieland", "Jazz"),
    ("blues", "Blues"),
    ("reggae", "Reggae"), ("ska", "Reggae"), ("dancehall", "Reggae"), ("dub", "Reggae"),
    ("rocksteady", "Reggae"),
    ("classical", "Classical"), ("clasica", "Classical"), ("classica", "Classical"),
    ("klassik", "Classical"), ("classique", "Classical"), ("clasico", "Classical"),
    ("ballet", "Classical"), ("barock", "Classical"), ("oper", "Classical"), ("operetta", "Classical"),
    ("baroque", "Classical"), ("barroco", "Classical"), ("opera", "Classical"),
    ("symphon", "Classical"), ("chamber", "Classical"), ("orchestral", "Classical"),
    ("romantic", "Classical"), ("renaissance", "Classical"), ("medieval", "Classical"),
    ("choral", "Classical"), ("concerto", "Classical"), ("sonata", "Classical"),
    ("minimalism", "Classical"), ("zarzuela", "Classical"), ("lied", "Classical"),
    ("avant garde", "Classical"), ("early music", "Classical"), ("piano", "Classical"),
    ("salsa", "Latin"), ("bossa", "Latin"), ("tango", "Latin"), ("flamenco", "Latin"),
    ("rumba", "Latin"), ("cumbia", "Latin"), ("bolero", "Latin"), ("latin", "Latin"),
    ("latino", "Latin"), ("samba", "Latin"), ("reggaeton", "Latin"), ("bachata", "Latin"),
    ("merengue", "Latin"), ("son cubano", "Latin"), ("mpb", "Latin"), ("copla", "Latin"),
    ("ranchera", "Latin"), ("trova", "Latin"),
    ("country", "Country"), ("bluegrass", "Country"), ("americana", "Country"), ("honky", "Country"),
    ("folk", "Folk"), ("singer songwriter", "Folk"), ("cantautor", "Folk"), ("celtic", "Folk"),
    ("acoustic", "Folk"), ("canco", "Folk"),
    ("electro", "Electronic"), ("techno", "Electronic"), ("house", "Electronic"),
    ("trance", "Electronic"), ("ambient", "Electronic"), ("dubstep", "Electronic"),
    ("drum and bass", "Electronic"), ("drum & bass", "Electronic"), ("dnb", "Electronic"),
    ("edm", "Electronic"), ("idm", "Electronic"), ("synth", "Electronic"), ("dance", "Electronic"),
    ("downtempo", "Electronic"), ("trip hop", "Electronic"), ("chillout", "Electronic"),
    ("chill out", "Electronic"), ("lounge", "Electronic"), ("breakbeat", "Electronic"),
    ("garage", "Electronic"), ("industrial", "Electronic"), ("new age", "Electronic"),
    ("punk", "Rock"), ("grunge", "Rock"), ("indie", "Rock"), ("alternative", "Rock"),
    ("shoegaze", "Rock"), ("emo", "Rock"), ("hard rock", "Rock"), ("psychedelic", "Rock"),
    ("prog", "Rock"), ("rock", "Rock"), ("new wave", "Rock"), ("post punk", "Rock"),
    ("britpop", "Rock"),
    ("pop", "Pop"), ("chanson", "Pop"), ("schlager", "Pop"), ("easy listening", "Pop"),
    ("vocal", "Pop"), ("oldies", "Pop"), ("k pop", "Pop"), ("j pop", "Pop"),
    ("world", "World"), ("african", "World"), ("afro", "World"), ("fado", "World"),
    ("ethnic", "World"), ("traditional", "World"), ("international", "World"),
    ("indian", "World"), ("arab", "World"), ("balkan", "World"), ("klezmer", "World"),
]


# raw genres that just NAME the top-level genre (other language/spelling): no STYLE kept
GENRE_SYNONYMS = {"klassik", "classique", "clasica", "classica", "clasico", "musica clasica",
                  "hiphop", "hip hop", "rnb", "r&b", "r and b", "rhythm and blues", "electronica",
                  "electronic music", "musica electronica", "latino", "rock music", "pop music",
                  "jazz music", "bso", "ost", "original soundtrack", "banda sonora"}


def suggest_genre(raw: str) -> tuple[str | None, str | None]:
    """Map a raw genre string to (top-level genre, style) or (None, None)."""
    k = genre_key(raw)
    for g in TAXONOMY:
        if genre_key(g) == k:
            return g, None
    padded = f" {k} "
    for kw, g in GENRE_KEYWORDS:
        if len(kw) <= 4:
            hit = f" {kw} " in padded          # short keywords must be whole words
        else:
            hit = kw in k
        if hit:
            style = nice_case(raw.strip())
            if genre_key(style) == genre_key(g) or k in GENRE_SYNONYMS:
                style = None
            return g, style
    return None, None


def dumps_toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def iter_audio_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "@eaDir", "#recycle"))]
        for fn in filenames:
            if Path(fn).suffix.lower() in AUDIO_EXTENSIONS and not fn.startswith("._"):
                yield os.path.join(dirpath, fn)
