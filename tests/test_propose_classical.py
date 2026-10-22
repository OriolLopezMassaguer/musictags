"""propose_changes with the classical genre tree, on made-up albums (mutagen is stubbed when it is
not installed - nothing here touches a file):
    python3 -m unittest discover tests -t .
"""
import copy
import csv
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # pip install tomli

from tests import mutagen_stub  # noqa: F401  (must come before anything that imports core)

import classical_genres as cg
import propose_changes as pc
from core import WRITABLE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYM = "Clásica\\Orquestal\\Sinfonias"


def base_cfg(tree=True, **opts):
    with open(os.path.join(ROOT, "schema.example.toml"), "rb") as fh:
        cfg = tomllib.load(fh)
    cfg.pop("classical_genres", None)
    cfg.pop("classical_rules", None)
    if tree:
        cfg["classical_genres"] = dict(enabled=True, **opts)
        cfg["classical_rules"] = dict(cg.STANDARD_TREE)
    return cfg


def album(folder, name, composer, genre, titles, artist="Berliner Philharmoniker", **extra):
    """-> [(path, tags)] for one album. `titles` may be (title, work) pairs."""
    out = []
    for i, item in enumerate(titles, 1):
        title, work = item if isinstance(item, tuple) else (item, None)
        t = {"title": [title], "album": [name], "artist": [artist], "tracknumber": [str(i)],
             "composer": [composer] if composer else [], "genre": [genre] if isinstance(genre, str) else list(genre)}
        if work:
            t["work"] = [work]
        t.update(extra)
        out.append(("/music/%s/%02d %s.flac" % (folder, i, title.replace("/", "-").replace(":", "-")), t))
    return out


def run(cfg, items):
    prop = pc.Proposer(cfg)
    tracks = []
    for path, t in items:
        p, main = prop.track(t)
        tracks.append((path, t, p, main))
    prop.albums(tracks)
    prop.album_names(tracks)
    prop.classical_genres(tracks)
    return tracks


def changes(tracks):
    """{path: {field: (new, conf, rule)}} - what main() would write to changes.csv."""
    out = {}
    for path, t, p, _ in tracks:
        for f, (new, conf, rule) in p.items():
            if f in WRITABLE and new != t.get(f, []):
                out.setdefault(path, {})[f] = (new, conf, rule)
    return out


def genre_rows(tracks):
    return {path: ch["genre"] for path, ch in changes(tracks).items() if "genre" in ch}


def apply(items, tracks):
    """The items as they would be after applying every proposal."""
    done = {path: p for path, _, p, _ in tracks}
    out = []
    for path, t in items:
        t = copy.deepcopy(t)
        for f, (new, _, _) in done[path].items():
            if f in WRITABLE:
                t[f] = list(new)
        out.append((path, t))
    return out


class Fixtures(unittest.TestCase):
    cfg = None

    def setUp(self):
        self.cfg = base_cfg()

    def only_value(self, tracks, want, conf=None):
        rows = genre_rows(tracks)
        self.assertEqual(len(rows), len(tracks), rows)
        for new, c, rule in rows.values():
            self.assertEqual(new, [want])
            self.assertTrue(rule.startswith("genre-tree: " + want), rule)
            if conf:
                self.assertEqual(c, conf)

    # ---- the albums of the plan ----
    def test_beethoven_5_and_7(self):
        items = album("Beethoven 5&7", "Beethoven: Symphonies Nos. 5 & 7", "Ludwig van Beethoven", "Classical",
                      [("Symphony No. 5 in C minor, Op. 67: I. Allegro con brio", None),
                       ("Symphony No. 5 in C minor, Op. 67: II. Andante con moto", None),
                       ("Symphony No. 7 in A major, Op. 92: I. Poco sostenuto", None),
                       ("Symphony No. 7 in A major, Op. 92: II. Allegretto", None)])
        tracks = run(self.cfg, items)
        self.only_value(tracks, SYM, "medium")
        for path, ch in changes(tracks).items():
            self.assertEqual(ch["style"][0], ["Classical Period"])           # the period stays in STYLE
            self.assertIn("2 of 2 works", ch["genre"][2])

    def test_dvorak_cello_concerto(self):
        items = album("Dvorak", "Dvořák: Cello Concerto", "Antonín Dvořák", "Classical",
                      ["Cello Concerto in B minor, Op. 104: I. Allegro", "Cello Concerto in B minor, Op. 104: II. Adagio"],
                      artist="Pablo Casals")
        self.only_value(run(self.cfg, items), "Clásica\\Conciertos\\Cello", "medium")

    def test_mozart_requiem_from_a_raw_german_genre(self):
        items = album("Requiem", "Mozart: Requiem", "Wolfgang Amadeus Mozart", "Klassik",
                      [("Requiem in D minor, K. 626: Introitus", None), ("Kyrie", "Requiem in D minor, K. 626"),
                       ("Dies irae", "Requiem in D minor, K. 626"), ("Lacrimosa", "Requiem in D minor, K. 626")])
        self.only_value(run(self.cfg, items), "Clásica\\Religiosa\\Misa")

    def test_josquin_motets_are_early_music(self):
        items = album("Josquin", "Josquin: Motets", "Josquin des Prez", "Classical",
                      ["Ave Maria", "Miserere mei, Deus", "Absalon fili mi"], artist="The Tallis Scholars")
        self.only_value(run(self.cfg, items), "Clásica\\Antigua")

    def test_bach_cello_suites(self):
        titles = [("Prélude", "Cello Suite No. %d in G major, BWV 100%d" % (n, n + 6)) for n in (1, 2, 3)]
        items = album("Casals", "Bach: Cello Suites", "Johann Sebastian Bach", "Classical", titles, artist="Pablo Casals")
        self.only_value(run(self.cfg, items), "Clásica\\Cámara\\Sonatas Cello")

    def test_mixed_disc_goes_to_varios_with_low_confidence(self):
        items = album("Mix", "Beethoven", "Ludwig van Beethoven", "Classical",
                      [("Piano Concerto No. 5: I. Allegro", None), ("Piano Concerto No. 5: II. Adagio", None),
                       ("Symphony No. 5: I. Allegro", None), ("Symphony No. 5: II. Andante", None)])
        tracks = run(self.cfg, items)
        self.only_value(tracks, "Clásica\\Varios", "low")

    def test_the_vote_is_per_album_not_per_track(self):
        # one 'Overture' among symphony movements must not split the album
        items = album("Sym", "Brahms: Symphonies", "Johannes Brahms", "Classical",
                      ["Symphony No. 1: I. Un poco sostenuto", "Symphony No. 1: II. Andante sostenuto",
                       "Symphony No. 2: I. Allegro non troppo", "Symphony No. 3: I. Allegro con brio",
                       "Symphony No. 4: I. Allegro non troppo"])
        tracks = run(self.cfg, items)
        self.assertEqual({v[0][0] for v in genre_rows(tracks).values()}, {SYM})

    def test_no_composer_no_work_uses_the_album_title(self):
        items = album("Tit", "Sinfonía n.º 9", "Ludwig van Beethoven", "Classical", ["I. Allegro", "II. Scherzo"])
        tracks = run(self.cfg, items)
        new, conf, rule = next(iter(genre_rows(tracks).values()))
        self.assertEqual((new, conf), ([SYM], "low"))
        self.assertIn("from the album title", rule)

    def test_nothing_matches_goes_to_the_root(self):
        items = album("Satie-ish", "Boléro", "Maurice Ravel", "Classical", ["Boléro"])
        tracks = run(self.cfg, items)
        new, conf, rule = next(iter(genre_rows(tracks).values()))
        self.assertEqual((new, conf), (["Clásica"], "low"))

    def test_no_match_keep_leaves_classical_alone(self):
        cfg = base_cfg(no_match="keep")
        items = album("Satie-ish", "Boléro", "Maurice Ravel", "Classical", ["Boléro"])
        self.assertEqual(genre_rows(run(cfg, items)), {})

    # ---- what the file already says ----
    def test_already_correct_path_makes_no_row(self):
        items = album("Ok", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", SYM,
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"], style=["Classical Period"])
        tracks = run(self.cfg, items)
        self.assertEqual(genre_rows(tracks), {})
        self.assertFalse(any("style" in ch for ch in changes(tracks).values()))     # nothing demoted to STYLE

    def test_other_spelling_of_the_same_path_is_normalised(self):
        items = album("Sp", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "clasica\\orquestal\\sinfonias",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        rows = genre_rows(run(self.cfg, items))
        self.assertEqual({v[0][0] for v in rows.values()}, {SYM})

    def test_wrong_path_is_replaced_with_low_and_was(self):
        items = album("Wrong", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Clásica\\Cámara\\Cuartetos",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        for new, conf, rule in genre_rows(run(self.cfg, items)).values():
            self.assertEqual((new, conf), ([SYM], "low"))
            self.assertIn("was Clásica\\Cámara\\Cuartetos", rule)

    def test_foreign_path_is_kept_and_not_demoted_to_style(self):
        items = album("Duo", "Mozart: Duos", "Wolfgang Amadeus Mozart", "Clásica\\Cámara\\Dúos",
                      ["Duo for Violin and Viola in G, K. 423: I. Allegro", "Duo for Violin and Viola in G, K. 423: II. Adagio"])
        tracks = run(self.cfg, items)
        self.assertEqual(genre_rows(tracks), {})
        self.assertFalse(any("style" in ch and "Clásica" in "".join(ch["style"][0]) for ch in changes(tracks).values()))

    def test_flat_classical_root_is_refined_with_the_decision_confidence(self):
        items = album("Flat", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Clásica",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        for new, conf, rule in genre_rows(run(self.cfg, items)).values():
            self.assertEqual((new, conf), ([SYM], "medium"))
            self.assertNotIn("was", rule)

    def test_a_more_specific_prior_than_the_decision_is_kept(self):
        items = album("Spec", "Strauss: Poems", "Richard Strauss", "Clásica\\Orquestal\\Otros\\Poemas",
                      ["Overture to Egmont: I. Sostenuto", "Overture to Egmont: II. Allegro"])
        self.assertEqual(genre_rows(run(self.cfg, items)), {})

    def test_existing_keep_trusts_the_file(self):
        cfg = base_cfg(existing="keep")
        items = album("Keep", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Clásica\\Cámara\\Cuartetos",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        self.assertEqual(genre_rows(run(cfg, items)), {})

    def test_id3v23_packed_value_keeps_the_other_genre(self):
        items = album("Packed", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Clásica\\Cámara\\Cuartetos; Jazz",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        for new, _, _ in genre_rows(run(self.cfg, items)).values():
            self.assertEqual(new, [SYM, "Jazz"])

    # ---- everything else ----
    def test_non_classical_is_untouched(self):
        items = album("Rock", "Abbey Road", "", "Rock", ["Come Together", "Something"], artist="The Beatles")
        tracks = run(self.cfg, items)
        self.assertEqual(genre_rows(tracks), {})

    def test_a_classical_album_with_one_rock_track(self):
        items = album("Sym", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Classical",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        items += album("Sym", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Rock", ["Roll Over Beethoven"])
        rows = genre_rows(run(self.cfg, items))
        self.assertEqual(len(rows), 2)                                         # the Rock track is left alone

    def test_two_albums_in_one_folder_are_voted_separately(self):
        items = album("Same", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Classical",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        items += album("Same", "Beethoven: Piano Concerto No. 5", "Ludwig van Beethoven", "Classical",
                       ["Piano Concerto No. 5: I. Allegro", "Piano Concerto No. 5: II. Adagio"])
        got = {v[0][0] for v in genre_rows(run(self.cfg, items)).values()}
        self.assertEqual(got, {SYM, "Clásica\\Conciertos\\Piano"})

    def test_cd_subfolders_are_one_album(self):
        a = album("Box/CD1", "Beethoven: Symphonies", "Ludwig van Beethoven", "Classical",
                  ["Symphony No. 1: I. Adagio", "Symphony No. 1: II. Andante"])
        b = album("Box/CD2", "Beethoven: Symphonies", "Ludwig van Beethoven", "Classical",
                  ["Symphony No. 2: I. Adagio", "Symphony No. 2: II. Larghetto"])
        self.assertEqual({v[0][0] for v in genre_rows(run(self.cfg, a + b)).values()}, {SYM})

    def test_empty_album_tag_groups_by_folder(self):
        items = album("NoAlbum", "", "Ludwig van Beethoven", "Classical", ["Symphony No. 5: I. Allegro"])
        items += album("Other", "", "Ludwig van Beethoven", "Classical", ["Piano Concerto No. 5: I. Allegro"])
        got = {v[0][0] for v in genre_rows(run(self.cfg, items)).values()}
        self.assertEqual(got, {SYM, "Clásica\\Conciertos\\Piano"})

    def test_style_keeps_the_composer_period(self):
        items = album("P", "Bach: Cello Suites", "Johann Sebastian Bach", "Classical",
                      [("Prélude", "Cello Suite No. 1 in G major, BWV 1007")], artist="Pablo Casals")
        for ch in changes(run(self.cfg, items)).values():
            self.assertEqual(ch["style"][0], ["Baroque"])


class Disabled(unittest.TestCase):
    """No tree = the output of the version without it."""

    def cfg(self, **kw):
        cfg = base_cfg(**kw)
        cfg["genre_map"]["Clásica\\Cámara\\Dúos"] = ["Classical", "Cámara\\Dúos"]     # an old-style entry
        return cfg

    def items(self):
        return (album("A", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Classical",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
                + album("B", "Duos", "Wolfgang Amadeus Mozart", "Clásica\\Cámara\\Dúos", ["Duo: I. Allegro"])
                + album("C", "Abbey Road", "", "Rock", ["Come Together"], artist="The Beatles"))

    def test_missing_section_is_the_old_flattening(self):
        cfg = self.cfg(tree=False)
        ch = changes(run(cfg, self.items()))
        self.assertNotIn("/music/A/01 Symphony No. 5- I. Allegro.flac", [p for p, c in ch.items() if "genre" in c])
        duo = ch["/music/B/01 Duo- I. Allegro.flac"]
        self.assertEqual(duo["genre"][0], ["Classical"])                 # what the Android player then shows
        self.assertEqual(duo["style"][0], ["Cámara\\Dúos"])             # ...with the path demoted to STYLE
        self.assertFalse(any(c["genre"][2].startswith("genre-tree") for c in ch.values() if "genre" in c))

    def test_disabled_and_empty_equal_missing(self):
        want = changes(run(self.cfg(tree=False), self.items()))
        off = self.cfg(); off["classical_genres"]["enabled"] = False
        empty = self.cfg(); empty["classical_rules"] = {}
        self.assertEqual(changes(run(off, self.items())), want)
        self.assertEqual(changes(run(empty, self.items())), want)

    def test_with_the_tree_the_path_is_not_demoted(self):
        ch = changes(run(self.cfg(), self.items()))
        duo = ch["/music/B/01 Duo- I. Allegro.flac"]
        self.assertNotIn("genre", duo)                                   # the foreign path is kept...
        self.assertEqual(duo["style"][0], ["Classical Period"])          # ...and STYLE is the composer's period


class Idempotence(unittest.TestCase):
    def items(self):
        return (album("Beethoven 5&7", "Beethoven: Symphonies Nos. 5 & 7", "Ludwig van Beethoven", "Classical",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 7: I. Poco sostenuto"])
                + album("Dvorak", "Dvořák: Cello Concerto", "Antonín Dvořák", "Klassik",
                        ["Cello Concerto in B minor: I. Allegro"], artist="Pablo Casals")
                + album("Mix", "Beethoven", "Ludwig van Beethoven", "Classical",
                        ["Piano Concerto No. 5: I. Allegro", "Symphony No. 5: I. Allegro"])
                + album("Wrong", "Beethoven: Symphony No. 3", "Ludwig van Beethoven", "Clásica\\Cámara\\Cuartetos",
                        ["Symphony No. 3: I. Allegro"])
                + album("Duo", "Mozart: Duos", "Wolfgang Amadeus Mozart", "Clásica\\Cámara\\Dúos", ["Duo: I. Allegro"])
                + album("Flat", "Boléro", "Maurice Ravel", "Clásica", ["Boléro"])
                + album("Bare", "Boléro", "Maurice Ravel", "", ["Boléro"])
                + album("Rock", "Abbey Road", "", "Rock", ["Come Together"], artist="The Beatles"))

    def test_second_run_proposes_no_genre_or_style(self):
        cfg = base_cfg()
        first = self.items()
        again = apply(first, run(cfg, first))
        rows = changes(run(cfg, again))
        for path, ch in rows.items():
            self.assertNotIn("genre", ch, path)
            self.assertNotIn("style", ch, path)

    def test_title_of_the_album_does_not_matter_after_the_rename(self):
        # propose renames the album; the genre must not depend on the new name
        cfg = base_cfg()
        items = album("X", "Greatest hits", "Ludwig van Beethoven", "Classical",
                      ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"])
        once = run(cfg, items)
        self.assertEqual(genre_rows(run(cfg, apply(items, once))), {})


class Main(unittest.TestCase):
    """The wiring in main(): warnings, changes.csv, --only."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "tags.sqlite")
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE files (path TEXT, tags TEXT, error TEXT)")
        for path, t in album("Beethoven 5", "Beethoven: Symphony No. 5", "Ludwig van Beethoven", "Classical",
                             ["Symphony No. 5: I. Allegro", "Symphony No. 5: II. Andante"]):
            con.execute("INSERT INTO files VALUES (?,?,NULL)", (path, json.dumps(t)))
        con.commit()
        con.close()

    def schema(self, extra="", example_tree=False):
        """schema.example.toml, without its own tree sections unless `example_tree`, plus `extra`."""
        with open(os.path.join(ROOT, "schema.example.toml"), encoding="utf-8") as fh:
            text = fh.read()
        if not example_tree:
            text = re.sub(r"(?ms)^\[classical_genres\].*?^(?=\[album\])", "", text)
        text += "\n" + extra
        path = os.path.join(self.tmp.name, "schema.toml")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def tree_toml(self, **opts):
        lines = ["[classical_genres]"] + ["%s = %s" % (k, json.dumps(v)) for k, v in opts.items()]
        lines += ["", "[classical_rules]"]
        lines += ["%s = %s" % (json.dumps(k, ensure_ascii=False), json.dumps(v, ensure_ascii=False))
                  for k, v in cg.STANDARD_TREE.items()]
        return "\n".join(lines) + "\n"

    def run_main(self, schema, *extra):
        out = os.path.join(self.tmp.name, "changes.csv")
        argv = ["propose_changes.py", "--db", self.db, "--schema", schema, "--out", out, *extra]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print") as pr:
            pc.main()
        printed = "\n".join(str(a[0][0]) if a[0] else "" for a in pr.call_args_list)
        with open(out, newline="", encoding="utf-8-sig") as fh:
            return printed, list(csv.DictReader(fh))

    def test_backslash_keys_survive_toml(self):
        printed, rows = self.run_main(self.schema(self.tree_toml()))
        self.assertNotIn("warning", printed)
        genre = [r for r in rows if r["field"] == "genre"]
        self.assertEqual({r["new"] for r in genre}, {SYM})
        self.assertEqual({r["confidence"] for r in genre}, {"medium"})
        self.assertEqual({r["approve"] for r in genre}, {"y"})
        self.assertTrue(all(r["rule"].startswith("genre-tree:") for r in genre))

    def test_the_example_schema_works_as_it_is(self):
        printed, rows = self.run_main(self.schema(example_tree=True))
        self.assertNotIn("warning", printed)
        self.assertNotIn("note:", printed)
        genre = [r for r in rows if r["field"] == "genre"]
        self.assertEqual({r["new"] for r in genre}, {SYM})

    def test_only_genre(self):
        _, rows = self.run_main(self.schema(self.tree_toml()), "--only", "genre")
        self.assertEqual({r["field"] for r in rows}, {"genre"})

    def test_missing_section_prints_a_note(self):
        printed, rows = self.run_main(self.schema())
        self.assertIn("no [classical_genres] section", printed)
        self.assertFalse(any(r["rule"].startswith("genre-tree") for r in rows))

    def test_disabled_prints_a_note(self):
        printed, _ = self.run_main(self.schema(self.tree_toml(enabled=False)))
        self.assertIn("enabled = false", printed)

    def test_problems_are_printed(self):
        printed, _ = self.run_main(self.schema(self.tree_toml(existing="sometimes")))
        self.assertIn("warning: [classical_genres] existing", printed)


if __name__ == "__main__":
    unittest.main()
