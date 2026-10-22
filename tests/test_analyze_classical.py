"""analyze_tags.py: your classical genre tree against the standard one, on a made-up library:
    python3 -m unittest discover tests -t .
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # pip install tomli

from tests import mutagen_stub  # noqa: F401

import analyze_tags
import classical_genres as cg
from tests.test_propose_classical import album


class Analyze(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def library(self, items):
        db = os.path.join(self.tmp.name, "tags.sqlite")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE files (path TEXT, format TEXT, tags TEXT, error TEXT)")
        con.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        con.execute("INSERT INTO meta VALUES ('root', '/music')")
        for path, t in items:
            con.execute("INSERT INTO files VALUES (?, 'flac', ?, NULL)", (path, json.dumps(t)))
        con.commit()
        con.close()
        return db

    def analyze(self, items, *extra):
        db = self.library(items)
        report, out = (os.path.join(self.tmp.name, n) for n in ("report.md", "schema.proposed.toml"))
        argv = ["analyze_tags.py", "--db", db, "--report", report, "--out", out, *extra]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            analyze_tags.main()
        with open(report, encoding="utf-8") as fh:
            md = fh.read()
        with open(out, "rb") as fh:
            raw = fh.read()
        return md, tomllib.loads(raw.decode("utf-8")), raw.decode("utf-8")

    def yours(self):
        return (album("A", "Beethoven 5", "Ludwig van Beethoven", "Clásica\\Orquestal\\Sinfonias",
                      ["Symphony No. 5: I", "Symphony No. 5: II"])
                + album("B", "Beethoven 7", "Ludwig van Beethoven", "clasica\\orquestal\\sinfonias",
                        ["Symphony No. 7: I"])
                + album("C", "Mozart duos", "Wolfgang Amadeus Mozart", "Clásica\\Cámara\\Dúos", ["Duo: I"])
                + album("D", "Violin", "Wolfgang Amadeus Mozart", "Clásica\\Cámara\\Sonatas Violin Y Piano", ["Sonata: I"])
                + album("E", "Abbey Road", "", "Rock", ["Come Together"], artist="The Beatles"))

    def test_report_compares_with_the_standard_tree(self):
        md, _, _ = self.analyze(self.yours())
        self.assertIn("## Classical genre tree", md)
        self.assertIn("| `Clásica\\Cámara\\Dúos` | 1 | 1 | not in standard |", md)
        self.assertIn("| `Clásica\\Cámara\\Sonatas Violin Y Piano` | 1 | 1 | extends | `Clásica\\Cámara\\Sonatas Violin` |", md)
        self.assertIn("| `Clásica\\Orquestal\\Sinfonias` (also: `clasica\\orquestal\\sinfonias`) | 2 | 3 | same |", md)
        self.assertIn("* `Clásica\\Cámara\\Cuartetos`", md)                        # absent standard node

    def test_rules_are_seeded_in_your_spelling(self):
        _, cfg, raw = self.analyze(self.yours())
        rules = cfg["classical_rules"]
        self.assertEqual(rules["Clásica\\Orquestal\\Sinfonias"], ["symphony"])
        self.assertEqual(rules["Clásica\\Cámara\\Dúos"], [])                        # yours: no rules
        self.assertIn("sonata+violin", rules["Clásica\\Cámara\\Sonatas Violin Y Piano"])   # adopted
        self.assertNotIn("Clásica\\Cámara\\Sonatas Violin", rules)
        self.assertIn("Clásica\\Cámara\\Cuartetos", rules)                          # absent standard node
        self.assertIn('"Clásica\\\\Cámara\\\\Dúos" = []', raw)                       # backslashes doubled
        self.assertIn("# 1 albums · 1 tracks · yours, no rules yet", raw)
        self.assertIn("# 0 tracks (standard)", raw)

    def test_the_proposed_tree_loads_without_problems(self):
        _, cfg, _ = self.analyze(self.yours())
        tree = cg.Tree.from_cfg(cfg)
        self.assertIsNotNone(tree)
        self.assertEqual(tree.problems, [])

    def test_paths_stay_out_of_genre_map(self):
        _, cfg, _ = self.analyze(self.yours())
        keys = list(cfg["genre_map"])
        self.assertFalse([k for k in keys if "\\" in k], keys)
        self.assertIn("Rock", keys)

    def test_options_use_the_dropdown_comment_shape(self):
        _, _, raw = self.analyze(self.yours())
        self.assertIn('existing = "recalc"           # "recalc" | "keep"', raw)
        self.assertIn('no_match = "root"             # "root" | "keep"', raw)

    def test_section_order(self):
        _, _, raw = self.analyze(self.yours())
        order = [raw.index(h) for h in ("[genre_map]", "[classical_genres]", "[classical_rules]", "[album]")]
        self.assertEqual(order, sorted(order))

    def test_library_without_paths_gets_the_standard_tree(self):
        items = album("E", "Abbey Road", "", "Rock", ["Come Together"], artist="The Beatles")
        md, cfg, _ = self.analyze(items)
        self.assertIn("No genre of the form", md)
        self.assertEqual(set(cfg["classical_rules"]), set(cg.STANDARD_TREE))

    def test_classical_root_option(self):
        items = album("E", "Abbey Road", "", "Rock", ["Come Together"], artist="The Beatles")
        _, cfg, _ = self.analyze(items, "--classical-root", "Música Clásica")
        self.assertIn("Música Clásica\\Orquestal\\Sinfonias", cfg["classical_rules"])
        self.assertTrue(all(k.startswith("Música Clásica") for k in cfg["classical_rules"]))

    def test_root_is_detected_from_your_files(self):
        items = album("A", "Beethoven 5", "Ludwig van Beethoven", "Música Clásica\\Orquestal\\Sinfonias", ["Symphony No. 5: I"])
        _, cfg, _ = self.analyze(items)
        self.assertTrue(all(k.startswith("Música Clásica") for k in cfg["classical_rules"]), list(cfg["classical_rules"]))

    def test_non_classical_paths_are_ordinary_genres(self):
        items = album("J", "Kind of Blue", "", "Jazz\\Bebop", ["So What"], artist="Miles Davis")
        md, cfg, _ = self.analyze(items)
        self.assertIn("No genre of the form", md)
        self.assertIn("Jazz\\Bebop", cfg["genre_map"])


class Example(unittest.TestCase):
    """schema.example.toml documents the standard tree: keep the two in step."""

    def test_example_matches_the_standard_tree(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "schema.example.toml"), "rb") as fh:
            cfg = tomllib.load(fh)
        self.assertEqual(cfg["classical_rules"], cg.STANDARD_TREE)
        tree = cg.Tree.from_cfg(cfg)
        self.assertIsNotNone(tree)
        self.assertEqual(tree.problems, [])


if __name__ == "__main__":
    unittest.main()
