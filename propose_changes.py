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

Ctrl-C (or the GUI's "Parar") stops it; the CSV is built in a .part file and only
renamed into place at the end, so an interrupted run leaves the previous
changes.csv exactly as it was.
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

from core import (EXIT_INTERRUPTED, LIST_SEP, TAXONOMY, WRITABLE, Interrupted, band_sort,
                  check_stop, composer_aliases, composer_period, genre_key, handle_interrupts,
                  load_config, name_key, nice_case, person_sort)
from rules import DEFAULT_FEAT, DEFAULT_SPLIT, Canon, CreditSplitter, dedupe
from album_names import (OrchestraCodes, build_name, classify, composer_text, performers_text,
                         short_work, summarize_works, work_of_title)
from classical_genres import Tree, extract_concepts, swap_classical, tree_status

DISC_DIR = re.compile(r"^(?:cd|disc|disk|disco|disque|disc\s*\d+\s*of)\s*\d+\b.*$", re.I)


def album_key(path, t):
    """(folder, album) - CD1/CD2 sub-folders count as one album."""
    d = os.path.dirname(path)
    if DISC_DIR.match(os.path.basename(d)):
        d = os.path.dirname(d)
    return d, (t.get("album") or [""])[0]


def eff(t, p, f):
    """Value after the proposals made so far."""
    return p[f][0] if f in p else t.get(f, [])

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
        self.tree = Tree.from_cfg(cfg)          # None = no hierarchical classical genre

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
            if self.tree and self.tree.is_prior(v):          # Clásica\Orquestal\...: classical_genres() decides
                genres.append("Classical"); continue
            for tok in self.split_genre(v):
                if self.tree and self.tree.is_prior(tok):
                    genres.append("Classical"); continue
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
            key = album_key(item[0], item[1])
            if key[1]:
                groups[key].append(item)
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

    # ------------------------------------------------------------------ album names
    def album_names(self, tracks):
        """Classical albums -> '{composer} - {works} ({performers})'. Also fills CONDUCTOR,
        ENSEMBLE and WORK when they can be read from the credits/titles."""
        cfg = self.cfg.get("album", {})
        if not cfg.get("enabled", False):
            return
        codes = OrchestraCodes(self.cfg.get("orchestra_abbrev", {}))
        groups = defaultdict(list)
        for item in tracks:
            key = album_key(item[0], item[1])
            if key[1]:
                groups[key].append(item)

        planned = {}                                        # group key -> (name, conf, rule, items)
        for key, items in groups.items():
            items = sorted(items, key=lambda x: x[0])
            comps_by_track = [eff(t, p, "composer") for _, t, p, _ in items]
            n = len(items)
            classical = sum("Classical" in eff(t, p, "genre") for _, t, p, _ in items) > n / 2 or \
                all(c and all(self.is_classical_composer(x) for x in c) for c in comps_by_track)
            if cfg.get("scope", "classical") == "classical" and not classical:
                continue
            composers = Counter(x for c in comps_by_track for x in c)
            if not composers:
                continue
            comp_keys = {name_key(x) for x in composers}

            # ---- works ----
            works, hows, pending = [], [], []
            for i, (_, t, p, _) in enumerate(items):
                w = eff(t, p, "work")
                if w:
                    works.append(w[0]); hows.append("tag"); continue
                title = (t.get("title") or [""])[0]
                w, how = work_of_title(title, comps_by_track[i])
                works.append(w); hows.append(how)
                if not w:
                    pending.append(i)
            prefixes = {}
            for i in pending:
                title = (items[i][1].get("title") or [""])[0]
                for c in comps_by_track[i]:
                    title = re.sub(rf"^{re.escape(c.split()[-1])}\s*:\s*", "", title)
                m = re.match(r"^(.{3,}?)\s*:\s*\S", title)
                prefixes[i] = (m.group(1).strip() if m else None, title)
            for i, (pr, title) in prefixes.items():
                if pr:                                        # 'Work: section'
                    works[i], hows[i] = pr, "prefix"
                else:
                    works[i], hows[i] = title, "title"
            for i, (_, t, p, _) in enumerate(items):
                if hows[i] in ("movement", "prefix") and not eff(t, p, "work"):
                    p["work"] = ([works[i]], "low", "work: parsed from title")

            # ---- performers ----
            cond_names = {name_key(x) for _, t, p, _ in items for x in eff(t, p, "conductor")}
            sol, ens, con = Counter(), Counter(), Counter()
            for _, t, p, main in items:
                credits = eff(t, p, "artists") or main or []
                names = list(credits) + eff(t, p, "conductor") + eff(t, p, "ensemble")
                seen, tr_ens, tr_con = set(), [], []
                for raw in names:
                    name, role = classify(raw, cond_names)
                    k = name_key(name)
                    if k in seen or k in comp_keys or self.is_classical_composer(self.canon(name)):
                        continue
                    seen.add(k)
                    name = self.canon(name)
                    {"soloist": sol, "ensemble": ens, "conductor": con}[role][name] += 1
                    (tr_ens if role == "ensemble" else tr_con if role == "conductor" else []).append(name)
                if cfg.get("fill_conductor_ensemble", True):
                    if tr_con and not eff(t, p, "conductor"):
                        p["conductor"] = (tr_con, "medium", "conductor: detected in artist credits")
                    if tr_ens and not eff(t, p, "ensemble"):
                        p["ensemble"] = (tr_ens, "medium", "ensemble: detected in artist credits")

            name = build_name(cfg.get("format", "{composer} - {works} ({performers})"),
                              composer_text(composers, cfg, self.sort_over),
                              summarize_works(works, int(cfg.get("max_works", 3)), cfg.get("others", "etc.")),
                              performers_text(sol, ens, con, codes, cfg, n))
            guessed = any(p.get("composer", (None, "high"))[1] == "low" for _, _, p, _ in items)
            good = all(comps_by_track) and not guessed and all(h in ("tag", "movement", "prefix") for h in hows)
            rule = "album: classical name (composer - works - performers)"
            if guessed:
                rule += "; composer guessed"
            elif not good:
                rule += "; works taken from titles"
            planned[key] = [name, "medium" if good else "low", rule, items]

        # ---- different albums must not end up with the same name ----
        by_name = defaultdict(list)
        for key, v in planned.items():
            by_name[fold_key(v[0])].append(key)
        for keys in by_name.values():
            if len(keys) < 2:
                continue
            years = {k: next((d[0][:4] for _, t, p, _ in planned[k][3] for d in [t.get("date", [])] if d), "")
                     for k in keys}
            distinct_years = len(set(years.values())) == len(keys) and all(years.values())
            for i, k in enumerate(sorted(keys)):
                suffix = years[k] if distinct_years else (k[1] if len({kk[1] for kk in keys}) == len(keys) else str(i + 1))
                planned[k][0] += f" [{suffix}]"
                planned[k][2] += "; disambiguated"

        for key, (name, conf, rule, items) in planned.items():
            for _, t, p, _ in items:
                if t.get("album") != [name]:
                    p["album"] = ([name], conf, rule)

    # ------------------------------------------------------------------ classical genre tree
    def classical_genres(self, tracks):
        """Classical albums: GENRE 'Classical' -> a tree path such as Clásica\\Orquestal\\Sinfonias.
        One path per album, by vote of its distinct works (see classical_genres.Tree)."""
        tree = self.tree
        if not tree:
            return
        groups = defaultdict(list)
        for item in tracks:
            groups[album_key(item[0], item[1])].append(item)
        for items in groups.values():
            items = sorted(items, key=lambda x: x[0])
            classical = [it for it in items if "Classical" in eff(it[1], it[2], "genre")]
            if not classical:
                continue
            works, priors, comps_all = {}, Counter(), []
            for _, t, p, _ in classical:
                comps = eff(t, p, "composer")
                comps_all += [c for c in comps if c not in comps_all]
                periods = dedupe(self.period[c] for c in comps if c in self.period)
                title = (t.get("title") or [""])[0]
                work = (eff(t, p, "work") or [None])[0] or work_of_title(title, comps)[0]
                key = fold_key(short_work(work or title, keep_catalog=False))
                works.setdefault(key, extract_concepts(work=work, title=title, composers=comps, periods=periods))
                priors.update(tree.priors_in(t.get("genre", []), self.split_genre))
            periods = dedupe(self.period[c] for c in comps_all if c in self.period)
            album_text = (classical[0][1].get("album") or [""])[0]
            fallback = extract_concepts(text=album_text, composers=comps_all, periods=periods)
            d = tree.album_decision(works, fallback)
            res = tree.resolve(d, priors)

            for _, t, p, _ in classical:
                genres = list(eff(t, p, "genre"))
                if res is None:                              # leave what the file already says
                    own = tree.priors_in(t.get("genre", []), self.split_genre)
                    if not own:
                        continue                             # flat 'Classical': nothing to refine
                    new = swap_classical(genres, own[0])
                    old = p.get("genre")
                    if new == t.get("genre", []):
                        p.pop("genre", None)
                    else:
                        p["genre"] = (new, old[1] if old else "high", old[2] if old else "genre: kept")
                    continue
                if d is None:
                    how = "no rule matched, album goes to the root"
                elif d.how == "common":
                    how = "mixed album, %d of %d works matched" % (d.n, d.m)
                elif d.how == "album-text":
                    how = "from the album title"
                else:
                    how = "%d of %d works" % (d.n, d.m)
                rule = "genre-tree: %s (%s%s)" % (res.path, how, "; was " + res.was if res.was else "")
                p["genre"] = (swap_classical(genres, res.path), res.conf, rule)


def fold_key(s):
    return name_key(s)


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
    handle_interrupts()

    cfg = load_config(args.schema)
    auto = set(cfg.get("general", {}).get("auto_approve", ["high", "medium"]))
    only = set(args.only.split(",")) if args.only else None
    prop = Proposer(cfg)
    status = tree_status(cfg)
    if status != "ok":
        print({"missing": "note: the schema has no [classical_genres] section: classical tracks keep "
                          "GENRE = Classical (merge it from schema.proposed.toml, or see SCHEMA.md)",
               "disabled": "note: [classical_genres] enabled = false: classical tracks keep GENRE = Classical",
               "empty": "note: [classical_rules] is empty: classical tracks keep GENRE = Classical"}[status])
    for problem in prop.tree.problems if prop.tree else []:
        print("warning: " + problem)

    db = sqlite3.connect(args.db)
    rows = db.execute("SELECT path, tags FROM files WHERE error IS NULL ORDER BY path").fetchall()
    if args.path:
        base = os.path.abspath(args.path)
        rows = [r for r in rows if r[0].startswith(base)]

    tracks = []
    for path, tags in rows:
        check_stop()
        t = json.loads(tags)
        p, main_artists = prop.track(t)
        tracks.append((path, t, p, main_artists))
    prop.albums(tracks)
    prop.album_names(tracks)
    prop.classical_genres(tracks)

    stats, conf_stats, n = Counter(), Counter(), 0
    part = args.out + ".part"
    try:
        with open(part, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "approve", "confidence", "rule", "path", "field", "old", "new"])
            for path, t, p, _ in tracks:
                check_stop()
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
    except BaseException:                    # interrupted, or anything else
        if os.path.exists(part):             # never leave a half-written CSV behind
            os.unlink(part)
        raise
    os.replace(part, args.out)               # atomic: the old CSV until this point
    files = len({path for path, _, p, _ in tracks if p})
    print(f"{n} proposed changes in {files} of {len(tracks)} files -> {args.out}")
    print("  by confidence: " + ", ".join(f"{k} {v}" for k, v in conf_stats.most_common()))
    for k, v in stats.most_common():
        print(f"  {k:16} {v}")


if __name__ == "__main__":
    try:
        main()
    except Interrupted:
        print("\nInterrupted: changes.csv left as it was.", file=sys.stderr)
        sys.exit(EXIT_INTERRUPTED)
