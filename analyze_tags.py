#!/usr/bin/env python3
"""
Step 2 - analyze_tags.py: study the CURRENT tags and derive a tagging schema from them.

    python analyze_tags.py                       # reads tags.sqlite
    python analyze_tags.py --fuzzy               # also look for near-duplicate names (slower)

Writes:
  report.md              what your library looks like today (fields, genres, names, problems)
  schema.proposed.toml   a schema/config built from YOUR tags: genre map for every genre
                         you use, alias table for every name spelled several ways, list of
                         band names that must not be split, separators to split on...
Review/edit schema.proposed.toml, save it as schema.toml, then run propose_changes.py.
"""
import argparse
import difflib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict

from core import (FIELDS, TAXONOMY, composer_aliases, composer_period, dumps_toml_str,
                  genre_key, name_key, strip_accents, suggest_genre)
from rules import DEFAULT_FEAT, DEFAULT_KEEP, DEFAULT_SPLIT, CreditSplitter

GENRE_SPLIT = ["/", ";", ",", "|"]
SEPARATOR_PROBES = {
    "feat.": r"\bfeat\.?\s", "ft.": r"\bft\.?\s", "featuring": r"\bfeaturing\b",
    " & ": r" & ", " and ": r" and ", ", ": r", ", "; ": r";", " / ": r" / ",
    "/ (no spaces)": r"\S/\S", " x ": r" x ", " vs. ": r" vs\.? ", " with ": r" with ", " + ": r" \+ ",
}


def load(db_path):
    db = sqlite3.connect(db_path)
    rows = []
    for path, fmt, tags, err in db.execute("SELECT path, format, tags, error FROM files"):
        rows.append((path, fmt, json.loads(tags) if tags else {}, err))
    root = (db.execute("SELECT value FROM meta WHERE key='root'").fetchone() or [""])[0]
    return rows, root


def split_genres(raw):
    out = [raw]
    for sep in GENRE_SPLIT:
        out = [p for x in out for p in x.split(sep)]
    return [re.sub(r"^&\s*", "", p).strip() for p in out if p.strip(" &")]


def pick_canonical(variants: Counter) -> str:
    """Most used spelling; ties -> the one with accents, then with 'The'."""
    def score(v):
        accents = sum(1 for a, b in zip(v, strip_accents(v)) if a != b)
        return (variants[v], accents, v.startswith("The "), not v.isupper(), not v.islower())
    return max(variants, key=score)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="tags.sqlite")
    ap.add_argument("--report", default="report.md")
    ap.add_argument("--out", default="schema.proposed.toml")
    ap.add_argument("--fuzzy", action="store_true", help="find near-duplicate names (e.g. typos)")
    ap.add_argument("--min-band", type=int, default=2,
                    help="a 'A & B' credit whose parts never appear alone is kept together "
                         "if it is used on at least this many tracks")
    args = ap.parse_args()

    rows, root = load(args.db)
    ok = [(p, f, t) for p, f, t, e in rows if not e]
    errors = [(p, e) for p, f, t, e in rows if e]
    n = len(ok)
    R = []  # report lines
    R += [f"# Tag analysis of `{root}`", "", f"* Files scanned: **{len(rows)}** (unreadable: {len(errors)})"]

    # ---------------- formats & field usage ----------------
    fmts = Counter(os.path.splitext(p)[1].lower() for p, _, _ in ok)
    R.append("* Formats: " + ", ".join(f"{k} {v}" for k, v in fmts.most_common()))
    R += ["", "## Field usage", "", "| field | tracks with value | % | multi-valued |", "|---|---|---|---|"]
    for f in FIELDS:
        have = sum(1 for _, _, t in ok if t.get(f))
        multi = sum(1 for _, _, t in ok if len(t.get(f, [])) > 1)
        R.append(f"| {f} | {have} | {100 * have / max(n, 1):.0f}% | {multi} |")

    # ---------------- albums ----------------
    albums = defaultdict(list)
    for p, _, t in ok:
        albums[(os.path.dirname(p), (t.get("album") or [""])[0])].append(t)
    no_aa = sum(1 for ts in albums.values() if not any(t.get("albumartist") for t in ts))
    incons = sum(1 for ts in albums.values()
                 if len({name_key((t.get("albumartist") or [""])[0]) for t in ts}) > 1)
    multi_art = sum(1 for ts in albums.values()
                    if len({name_key((t.get("artist") or [""])[0]) for t in ts}) > 1)
    R += ["", "## Albums", "", f"* Albums (folder + album tag): {len(albums)}",
          f"* Without any album artist: {no_aa}", f"* With inconsistent album artist: {incons}",
          f"* With several different track artists (compilations / classical / duets): {multi_art}"]

    # ---------------- separators ----------------
    sep_count = {fld: Counter() for fld in ("artist", "albumartist", "composer", "genre")}
    sep_example = {}
    for _, _, t in ok:
        for fld in sep_count:
            for v in t.get(fld, []):
                for name, rx in SEPARATOR_PROBES.items():
                    if re.search(rx, v, re.I):
                        sep_count[fld][name] += 1
                        sep_example.setdefault((fld, name), v)
    R += ["", "## Separators found inside single values", "",
          "These tell how multiple people/genres are currently packed into one string.", "",
          "| field | separator | values | example |", "|---|---|---|---|"]
    for fld, c in sep_count.items():
        for name, k in c.most_common():
            R.append(f"| {fld} | `{name}` | {k} | {sep_example[(fld, name)]} |")

    # ---------------- band names that must not be split ----------------
    raw_artist = Counter()
    albumartists = set()
    for _, _, t in ok:
        for v in t.get("artist", []):
            raw_artist[v] += 1
        for v in t.get("albumartist", []):
            albumartists.add(name_key(v))
    naive = CreditSplitter(DEFAULT_SPLIT, DEFAULT_FEAT, [])
    standalone = {name_key(v) for v in raw_artist if len(naive.split(v)[0]) == 1 and not naive.split(v)[1]}
    for v in list(raw_artist):
        for f in naive.split(v)[1]:
            standalone.add(name_key(f))
    keep, ambiguous = set(DEFAULT_KEEP), []
    for v, cnt in raw_artist.items():
        main, _ = naive.split(v)
        if len(main) < 2:
            continue
        whole = naive.feat_re.split(v)[0].strip()
        if any(name_key(p) in standalone for p in main):
            continue                                   # e.g. 'Beyoncé & Jay-Z': parts exist alone -> split
        if cnt >= args.min_band or name_key(whole) in albumartists:
            keep.add(whole)                            # e.g. 'Simon & Garfunkel'
        else:
            ambiguous.append((v, cnt))

    # ---------------- names (artists, composers, conductors...) ----------------
    splitter = CreditSplitter(DEFAULT_SPLIT, DEFAULT_FEAT, sorted(keep))
    _ca = composer_aliases()
    comp_split = CreditSplitter(["/", "; ", ";", ", ", " & ", " and "], [], sorted(keep),
                                known=lambda x: name_key(x) in _ca)
    names = defaultdict(Counter)       # name_key -> Counter(spelling)
    role = defaultdict(Counter)        # name_key -> Counter(field)
    composers_raw = Counter()
    for _, _, t in ok:
        for fld in ("artist", "albumartist", "artists", "conductor", "ensemble"):
            for v in t.get(fld, []):
                main, feat = splitter.split(v) if fld != "artists" else ([v], [])
                for x in main + feat:
                    names[name_key(x)][x] += 1
                    role[name_key(x)][fld] += 1
        for v in t.get("composer", []):
            for x in comp_split.split_list(v):
                composers_raw[x] += 1
                names[name_key(x)][x] += 1
                role[name_key(x)]["composer"] += 1

    calias = composer_aliases()
    periods = composer_period()
    aliases = {}
    for k, spellings in names.items():
        if k in calias:
            continue                     # classical composers are handled by the built-in list
        if len(spellings) > 1:
            canon = pick_canonical(spellings)
            for s in spellings:
                if s != canon:
                    aliases[s] = canon
    # surname-only credits ('Lennon/McCartney') -> full name when exactly one full name has that surname
    by_surname = defaultdict(set)
    for k in names:
        if " " in k:
            by_surname[k.split()[-1]].add(k)
    surname_alias = {}
    for k, spellings in names.items():
        if " " in k or k in calias or len(by_surname.get(k, ())) != 1:
            continue
        full = pick_canonical(names[next(iter(by_surname[k]))])
        for s in spellings:
            surname_alias[s] = (full, set(role[k]) == {"composer"})
    R += ["", "## Names spelled in several ways", "",
          f"{len(aliases)} spellings will be unified (case, accents, 'The', '&'/'and', initials).", ""]
    for s, c in sorted(aliases.items(), key=lambda x: x[1].casefold())[:200]:
        R.append(f"* `{s}` -> **{c}**")

    fuzzy = []
    if args.fuzzy:
        keys = sorted(k for k in names if len(k) >= 6 and k not in calias)
        buckets = defaultdict(list)
        for k in keys:
            buckets[k[:2]].append(k)
        for bucket in buckets.values():
            for i, a in enumerate(bucket):
                for b in bucket[i + 1:]:
                    sm = difflib.SequenceMatcher(None, a, b)
                    if sm.real_quick_ratio() >= .9 and sm.quick_ratio() >= .9 and sm.ratio() >= .9:
                        ca, cb = pick_canonical(names[a]), pick_canonical(names[b])
                        na, nb = sum(names[a].values()), sum(names[b].values())
                        fuzzy.append((cb, ca) if na >= nb else (ca, cb))
        R += ["", "## Possible typos (fuzzy matches, NOT applied unless you uncomment them)", ""]
        R += [f"* `{a}` ~ **{b}**" for a, b in fuzzy[:200]]

    # ---------------- composers ----------------
    known = Counter()
    misspelled = {}
    for x, c in composers_raw.items():
        canon = calias.get(name_key(x))
        if canon:
            known[canon] += c
            if x != canon:
                misspelled[x] = canon
    composer_in_artist = Counter()
    for _, _, t in ok:
        for v in t.get("artist", []):
            for x in splitter.split(v)[0]:
                if name_key(x) in calias and not t.get("composer"):
                    composer_in_artist[calias[name_key(x)]] += 1
    R += ["", "## Composers", "",
          f"* Distinct composer names: {len(composers_raw)}; recognised classical composers: {len(known)}",
          f"* Composer spellings that will be normalised to the canonical form: {len(misspelled)}",
          f"* Tracks with a classical composer in ARTIST and empty COMPOSER: {sum(composer_in_artist.values())}"]
    for x, c in list(misspelled.items())[:60]:
        R.append(f"  * `{x}` -> **{c}**")
    for x, c in composer_in_artist.most_common(30):
        R.append(f"  * {x} appears as artist on {c} tracks without composer")
    R += ["", "Most used composers:", ""]
    R += [f"* {x} ({c})" for x, c in composers_raw.most_common(40)]

    # ---------------- genres ----------------
    raw_genres = Counter()
    token_genres = Counter()
    for _, _, t in ok:
        for v in t.get("genre", []):
            raw_genres[v] += 1
            for tok in split_genres(v):
                token_genres[tok] += 1
    gmap, unmapped = {}, []
    for tok, c in token_genres.most_common():
        g, style = suggest_genre(tok)
        k = genre_key(tok)
        if k in {genre_key(x) for x in gmap}:
            continue
        if g:
            gmap[tok] = ([g, style] if style else [g], c)
        else:
            unmapped.append((tok, c))
    classical_tracks = sum(1 for _, _, t in ok if any(
        (suggest_genre(tok)[0] == "Classical") for v in t.get("genre", []) for tok in split_genres(v))
        or any(name_key(x) in calias for v in t.get("composer", []) for x in comp_split.split_list(v)))
    R += ["", "## Genres", "",
          f"* Distinct raw genre values: {len(raw_genres)}; distinct genre tokens: {len(token_genres)}",
          f"* Tokens mapped automatically to the taxonomy: {len(gmap)}; **need your decision: {len(unmapped)}**",
          f"* Tracks that look classical: {classical_tracks} ({100 * classical_tracks / max(n, 1):.0f}%)",
          "", "| raw genre | tracks | -> GENRE | STYLE |", "|---|---|---|---|"]
    for tok, (val, c) in sorted(gmap.items(), key=lambda x: -x[1][1]):
        R.append(f"| {tok} | {c} | {val[0]} | {val[1] if len(val) > 1 else ''} |")
    for tok, c in unmapped:
        R.append(f"| {tok} | {c} | **?** | |")

    if ambiguous:
        R += ["", "## Ambiguous multi-artist credits (will be SPLIT unless you add them to keep_together)", ""]
        R += [f"* {v} ({c})" for v, c in sorted(ambiguous, key=lambda x: -x[1])[:150]]
    if errors:
        R += ["", "## Unreadable files", ""] + [f"* `{p}`: {e}" for p, e in errors[:200]]

    with open(args.report, "w", encoding="utf-8") as fh:
        fh.write("\n".join(R) + "\n")

    # ---------------- schema.proposed.toml ----------------
    q = dumps_toml_str
    classical_heavy = classical_tracks > 0.15 * n
    T = [
        "# Tagging schema derived from your current tags by analyze_tags.py",
        f"# Library: {root}   tracks: {n}   classical-looking: {classical_tracks}",
        "# Review it, then save as schema.toml and run propose_changes.py.",
        "",
        "[general]",
        "id3_version = 4          # 4 = real multi-value frames (recommended). 3 = joined with '; ' for old players",
        'auto_approve = ["high", "medium"]   # confidence levels pre-approved in changes.csv',
        "",
        "[artists]",
        "# ARTIST  = display credit, e.g. 'Daft Punk feat. Pharrell Williams'",
        "# ARTISTS = one value per person/band, e.g. ['Daft Punk', 'Pharrell Williams']",
        f"split_separators = [{', '.join(q(s) for s in DEFAULT_SPLIT)}]",
        f"feat_patterns = [{', '.join(q(s) for s in DEFAULT_FEAT)}]",
        'display_joiner = " & "',
        'feat_joiner = " feat. "',
        "rebuild_display = true        # rewrite ARTIST from the canonical names",
        "feat_from_title = true        # 'Song (feat. X)' adds X to ARTISTS",
        "fill_artistsort = true        # 'The Beatles' -> ARTISTSORT 'Beatles, The'",
        'various_artists = "Various Artists"',
        "# Names that contain a separator but are ONE act. Built from your library:",
        "keep_together = [",
        *[f"    {q(k)}," for k in sorted(keep, key=str.casefold)],
        "]",
        "",
        "[albumartist]",
        "fill_missing = true           # albums without ALBUMARTIST get one",
        "unify = true                  # same ALBUMARTIST on every track of an album",
        f'classical = "{"composer" if classical_heavy else "keep"}"   '
        '# for classical albums with ONE composer: "composer" | "performer" | "keep"',
        "",
        "[composers]",
        'split_separators = ["/", "; ", ";", ", ", " & ", " and "]',
        "use_builtin_classical = true  # ~190 classical composers with canonical spelling + period",
        "fill_composersort = true      # 'Bach, Johann Sebastian'",
        "infer_from_artist = true      # ARTIST is a known composer and COMPOSER empty -> propose (low confidence)",
        "infer_from_title = true       # 'Bach: Cello Suite No. 1 - I. Prelude' -> composer/work/movement",
        "",
        "[genres]",
        "# GENRE = top-level genre from the taxonomy (1-2 values). STYLE = finer sub-genres.",
        f"taxonomy = [{', '.join(q(g) for g in TAXONOMY)}]",
        f"split_separators = [{', '.join(q(s) for s in GENRE_SPLIT)}]",
        "max_genres = 2",
        "write_style = true            # keep the detail in a STYLE tag",
        "style_into_genre = false      # true: put styles in GENRE too (for players that ignore STYLE)",
        'unmapped = "keep"             # unmapped genres: "keep" (low confidence) | "drop" | "style"',
        "classical_period_style = true # Classical tracks with a known composer get STYLE = period (Baroque...)",
        "",
        "[genre_map]",
        "# raw genre (as found in your files) = [GENRE, optional STYLE].  [] = delete this genre",
        "# --- automatically mapped ---",
        *[f"{q(tok)} = [{', '.join(q(x) for x in val)}]   # {c} tracks"
          for tok, (val, c) in sorted(gmap.items(), key=lambda x: -x[1][1])],
        "# --- NOT mapped: decide (uncomment and edit) ---",
        *[f"# {q(tok)} = [\"?\"]   # {c} tracks" for tok, c in unmapped],
        "",
        "[aliases]",
        "# any spelling = canonical name   (applies to artists, album artists, composers, conductors)",
        *[f"{q(s)} = {q(c)}" for s, c in sorted(aliases.items(), key=lambda x: (x[1].casefold(), x[0]))],
    ]
    if surname_alias:
        T += ["# --- surname-only credits matched to a full name (only-in-composer ones are active) ---"]
        T += [f"{'' if safe else '# '}{q(s)} = {q(full)}" for s, (full, safe) in sorted(surname_alias.items())]
    if fuzzy:
        T += ["# --- fuzzy matches: check and uncomment ---"]
        T += [f"# {q(a)} = {q(b)}" for a, b in fuzzy]
    T += ["", "[sort_overrides]", "# name = sort name, e.g.", '# "Prince" = "Prince"', '# "Joan Manuel Serrat" = "Serrat, Joan Manuel"', ""]
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(T))
    print(f"Wrote {args.report} and {args.out}  ({n} tracks, {len(gmap)} genres mapped, "
          f"{len(unmapped)} unmapped, {len(aliases)} aliases, {len(keep)} protected names)")


if __name__ == "__main__":
    main()
