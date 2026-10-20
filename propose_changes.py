#!/usr/bin/env python3
"""
Step 3 - propose_changes.py: compare current tags with the schema and list the changes.

    python propose_changes.py                          # tags.sqlite + schema.toml -> changes.csv
    python propose_changes.py --only genre,style       # restrict to some fields
    python propose_changes.py --path "/volume1/music/Jazz"   # restrict to a sub-folder

Nothing is written to your music files. changes.csv has one row per (file, field):
    approve | confidence | rule | path | field | old | new
Rows with approve = y will be applied by apply_changes.py. Edit the CSV freely
(change 'new', blank out 'approve'), e.g. in LibreOffice/Excel. Lists use ' || '.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict

from core import (LIST_SEP, TAXONOMY, WRITABLE, band_sort, composer_aliases, composer_period,
                  genre_key, load_config, name_key, nice_case, person_sort)
from rules import DEFAULT_FEAT, DEFAULT_SPLIT, Canon, CreditSplitter, dedupe

ROMAN = r"(?:[IVXLC]+|\d+)"


class Proposer:
    def __init__(self, cfg):
        self.cfg = cfg
        a, c, g = cfg.get("artists", {}), cfg.get("composers", {}), cfg.get("genres", {})
        self.a, self.c, self.g = a, c, g
        self.aa = cfg.get("albumartist", {})
        keep = a.get("keep_together", [])
        self.split = CreditSplitter(a.get("split_separators", DEFAULT_SPLIT),
                                    a.get("feat_patterns", DEFAULT_FEAT), keep)
        self.builtin = composer_aliases() if c.get("use_builtin_classical", True) else {}
        self.period = composer_period()
        builtin_named = {}
        for k, v in self.builtin.items():
            builtin_named[k] = v
        self.canon = Canon(cfg.get("aliases", {}))
        self.canon.map.update({k: v for k, v in builtin_named.items() if k not in self.canon.map})
        self.csplit = CreditSplitter(c.get("split_separators", ["/", ";", ", ", " & "]), [], keep,
                                     known=self.canon.known)
        self.split.known = self.canon.known
        self.sort_over = {name_key(k): v for k, v in cfg.get("sort_overrides", {}).items()}
        self.gmap = {genre_key(k): v for k, v in cfg.get("genre_map", {}).items()}
        self.tax = {genre_key(x): x for x in g.get("taxonomy", TAXONOMY)}
        self.gsep = g.get("split_separators", ["/", ";", ","])

    # ------------------------------------------------------------------ helpers
    def is_classical_composer(self, name):
        return name in self.period

    def sortname(self, name, person=False):
        o = self.sort_over.get(name_key(name))
        if o:
            return o
        if person or name in self.period:
            return person_sort(name)
        return band_sort(name)

    def split_genre(self, raw):
        parts = [raw]
        for sep in self.gsep:
            parts = [p for x in parts for p in x.split(sep)]
        return [re.sub(r"^&\s*", "", p).strip() for p in parts if p.strip(" &")]

    # ------------------------------------------------------------------ per track
    def track(self, t):
        """Return {field: (new_values, confidence, rule)} for one track."""
        out = {}
        cur = lambda f: t.get(f, [])

        # ---- artists ----
        main, feat, split_used = [], [], False
        for v in cur("artist"):
            m, f = self.split.split(v)
            split_used |= len(m) > 1
            main += m; feat += f
        main = dedupe(self.canon(x) for x in main)
        feat = [x for x in dedupe(self.canon(x) for x in feat) if name_key(x) not in {name_key(m) for m in main}]
        title_feat = []
        if self.a.get("feat_from_title", True):
            title_feat = [self.canon(x) for x in self.split.title_feat((cur("title") or [""])[0])]
        everyone = dedupe(main + feat + title_feat)
        if main:
            if self.a.get("rebuild_display", True):
                j = self.a.get("display_joiner", " & ")
                disp = j.join(main) + (self.a.get("feat_joiner", " feat. ") + j.join(feat) if feat else "")
                if [disp] != cur("artist"):
                    out["artist"] = ([disp], "medium" if split_used else "high", "artist: canonical names / credit format")
            if len(everyone) > 1 or (cur("artists") and cur("artists") != everyone):
                if everyone != cur("artists"):
                    out["artists"] = (everyone, "medium" if split_used else "high", "artists: one value per artist")
            if self.a.get("fill_artistsort", True) and not cur("artistsort"):
                disp = out.get("artist", ([cur("artist")[0]],))[0][0]
                s0 = self.sortname(main[0])
                if s0 != main[0] and disp.startswith(main[0]):
                    out["artistsort"] = ([s0 + disp[len(main[0]):]], "medium", "artistsort: from canonical name")

        # ---- composers ----
        comps = dedupe(self.canon(x) for v in cur("composer") for x in self.csplit.split_list(v))
        comp_rule, comp_conf = "composer: canonical names, one value each", "high"
        title = (cur("title") or [""])[0]
        if not comps and self.c.get("infer_from_title", True):
            m = re.match(r"^\s*([^:]{2,60}?)\s*:\s*(.+)$", title)
            if m and self.is_classical_composer(self.canon(m.group(1))):
                comps = [self.canon(m.group(1))]
                comp_rule, comp_conf = "composer: inferred from title 'Composer: Work'", "medium"
                rest = m.group(2)
                mv = re.match(rf"^(.+?)\s*(?:[-–:,]\s*)({ROMAN})\.\s+(.+)$", rest)
                if mv and not cur("work"):
                    out["work"] = ([mv.group(1).strip()], "low", "work: parsed from title")
                    out["movementname"] = ([mv.group(3).strip()], "low", "movement: parsed from title")
                    num = mv.group(2)
                    out["movement"] = ([str(roman_to_int(num)) if not num.isdigit() else num],
                                       "low", "movement number: parsed from title")
                elif not cur("work"):
                    out["work"] = ([rest.strip()], "low", "work: parsed from title")
        if not comps and self.c.get("infer_from_artist", True):
            cands = [x for x in main if self.is_classical_composer(x)]
            if len(cands) == 1:
                comps = cands
                comp_rule, comp_conf = "composer: ARTIST is a known composer (set the performer by hand)", "low"
        if comps and comps != cur("composer"):
            out["composer"] = (comps, comp_conf, comp_rule)
        if comps and self.c.get("fill_composersort", True):
            sorts = [self.sortname(x, person=True) for x in comps]
            if sorts != cur("composersort") and (not cur("composersort") or "composer" in out):
                out["composersort"] = (sorts, "medium", "composersort: 'Surname, Given names'")

        # ---- conductor / ensemble ----
        for f in ("conductor", "ensemble"):
            vals = dedupe(self.canon(x) for x in cur(f))
            if vals and vals != cur(f):
                out[f] = (vals, "high", f"{f}: canonical names")

        # ---- genres ----
        genres, styles, conf, rules = [], [], "high", []
        for v in cur("genre"):
            for tok in self.split_genre(v):
                k = genre_key(tok)
                if k in self.gmap:
                    m = self.gmap[k]
                    if not m:
                        rules.append(f"drop '{tok}'"); continue
                    genres.append(m[0]); styles += m[1:]
                elif k in self.tax:
                    genres.append(self.tax[k])
                else:
                    pol = self.g.get("unmapped", "keep")
                    if pol == "drop":
                        rules.append(f"drop unmapped '{tok}'")
                    elif pol == "style":
                        styles.append(nice_case(tok)); conf = "low"; rules.append(f"unmapped '{tok}' -> style")
                    else:
                        genres.append(nice_case(tok)); conf = "low"; rules.append(f"unmapped '{tok}' kept")
        if not genres and comps and any(self.is_classical_composer(x) for x in comps):
            genres = ["Classical"]; conf = "medium"; rules.append("classical composer")
        if "Classical" in genres and self.g.get("classical_period_style", True) and not styles and not cur("style"):
            ps = dedupe(self.period[x] for x in comps if x in self.period)
            if len(ps) == 1:
                styles.append(ps[0]); rules.append("period from composer")
        genres = dedupe(genres)[: int(self.g.get("max_genres", 2))]
        styles = dedupe(styles + cur("style")) if self.g.get("write_style", True) else []
        styles = [s for s in styles if name_key(s) not in {name_key(x) for x in genres}]
        if self.g.get("style_into_genre", False):
            genres = dedupe(genres + styles)
        if genres and genres != cur("genre"):
            out["genre"] = (genres, conf, "genre: " + ("; ".join(rules) or "mapped to taxonomy"))
        if self.g.get("write_style", True) and styles and styles != cur("style"):
            out["style"] = (styles, conf, "style: sub-genre kept from original genre")
        return out, main

    # ------------------------------------------------------------------ per album
    def albums(self, tracks):
        """tracks: list of (path, tags, proposals, main_artists). Adds album-artist proposals."""
        groups = defaultdict(list)
        for item in tracks:
            path, t = item[0], item[1]
            album = (t.get("album") or [""])[0]
            if album:
                groups[(os.path.dirname(path), album)].append(item)
        va = self.a.get("various_artists", "Various Artists")
        for items in groups.values():
            existing = Counter(self.canon(t["albumartist"][0]) for _, t, _, _ in items if t.get("albumartist"))
            target, conf, rule, comp = None, "high", "", False
            if existing and self.aa.get("unify", True):
                target = existing.most_common(1)[0][0]
                rule = "albumartist: canonical / same on all tracks"
            elif not existing and self.aa.get("fill_missing", True):
                disp = Counter((p.get("artist", ([None],))[0][0] or (t.get("artist") or [None])[0])
                               for _, t, p, _ in items)
                firsts = Counter(m[0] for _, _, _, m in items if m)
                comps = Counter(tuple(p.get("composer", (t.get("composer", []),))[0]) for _, t, p, _ in items)
                genres = Counter(g for _, t, p, _ in items for g in p.get("genre", (t.get("genre", []),))[0])
                classical = genres.get("Classical", 0) > len(items) / 2
                if len(disp) == 1 and None not in disp:
                    target, conf, rule = next(iter(disp)), "high", "albumartist: all tracks same artist"
                elif len(firsts) == 1:
                    target, conf, rule = next(iter(firsts)), "medium", "albumartist: common main artist"
                elif classical and len(comps) == 1 and len(next(iter(comps))) == 1 \
                        and self.aa.get("classical", "keep") == "composer":
                    target, conf, rule = next(iter(comps))[0], "medium", "albumartist: classical album, single composer"
                elif len(items) >= 3:
                    target, conf, rule, comp = va, "medium", "albumartist: several artists -> compilation", True
            if not target:
                continue
            for path, t, p, _ in items:
                if t.get("albumartist") != [target]:
                    p["albumartist"] = ([target], conf, rule)
                if comp and t.get("compilation") != ["1"]:
                    p["compilation"] = (["1"], conf, "compilation flag for Various Artists")
                if self.a.get("fill_artistsort", True) and not t.get("albumartistsort"):
                    s = self.sortname(target, person=target in self.period)
                    if s != target:
                        p["albumartistsort"] = ([s], "medium", "albumartistsort: from canonical name")


def roman_to_int(s):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total = prev = 0
    for ch in reversed(s.upper()):
        v = vals.get(ch, 0)
        total += -v if v < prev else v
        prev = max(prev, v)
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="tags.sqlite")
    ap.add_argument("--schema", default="schema.toml")
    ap.add_argument("--out", default="changes.csv")
    ap.add_argument("--only", help="comma separated fields to propose (default: all)")
    ap.add_argument("--path", help="only files under this folder")
    args = ap.parse_args()

    cfg = load_config(args.schema)
    auto = set(cfg.get("general", {}).get("auto_approve", ["high", "medium"]))
    only = set(args.only.split(",")) if args.only else None
    prop = Proposer(cfg)

    db = sqlite3.connect(args.db)
    rows = db.execute("SELECT path, tags FROM files WHERE error IS NULL ORDER BY path").fetchall()
    if args.path:
        base = os.path.abspath(args.path)
        rows = [r for r in rows if r[0].startswith(base)]

    tracks = []
    for path, tags in rows:
        t = json.loads(tags)
        p, main_artists = prop.track(t)
        tracks.append((path, t, p, main_artists))
    prop.albums(tracks)

    stats, conf_stats, n = Counter(), Counter(), 0
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "approve", "confidence", "rule", "path", "field", "old", "new"])
        for path, t, p, _ in tracks:
            for field in sorted(p):
                if field not in WRITABLE or (only and field not in only):
                    continue
                new, conf, rule = p[field]
                if new == t.get(field, []):
                    continue
                n += 1
                stats[rule.split(":")[0]] += 1
                conf_stats[conf] += 1
                w.writerow([n, "y" if conf in auto else "", conf, rule, path, field,
                            LIST_SEP.join(t.get(field, [])), LIST_SEP.join(new)])
    files = len({path for path, _, p, _ in tracks if p})
    print(f"{n} proposed changes in {files} of {len(tracks)} files -> {args.out}")
    print("  by confidence: " + ", ".join(f"{k} {v}" for k, v in conf_stats.most_common()))
    for k, v in stats.most_common():
        print(f"  {k:16} {v}")


if __name__ == "__main__":
    main()
