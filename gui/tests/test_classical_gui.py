"""The classical genre tree in the GUI: backslash keys, merge, album cards, health."""

import csv
import os
import tempfile
import unittest
from unittest import mock

try:
    import tomllib as tomli  # Python 3.11+
except ImportError:
    import tomli  # pip install tomli

from gui import app as A
from gui import changes as C
from gui import schema_merge as M
from gui import state
from gui.schema_edit import SchemaFile

NODE = "Clásica\\Orquestal\\Sinfonias"          # one single backslash per separator
OPTIONS = '''[classical_genres]
enabled = true
existing = "recalc"           # "recalc" | "keep"  (recalc: always recompute)
majority = 0.6               # the winning node needs this share of the works
'''
LIVE = OPTIONS + '''
[classical_rules]
# node path = [rules]
"Clásica" = []
"Clásica\\\\Orquestal\\\\Sinfonias" = ["symphony", "kw:sinfonia"]   # 2 albums · 3 tracks
'''
PROPOSED = OPTIONS + '''
[classical_rules]
# node path = [rules]
"Clásica" = []
"Clásica\\\\Orquestal\\\\Sinfonias" = ["symphony"]   # 2 albums · 3 tracks
"Clásica\\\\Cámara\\\\Cuartetos" = ["quartet"]   # 0 tracks (standard)
'''


class BackslashKeys(unittest.TestCase):
    def test_keys_are_read_with_single_backslashes_and_agree_with_tomli(self):
        schema = SchemaFile.loads(LIVE)
        self.assertEqual(schema.get("classical_rules", NODE).value, ["symphony", "kw:sinfonia"])
        self.assertEqual(schema.to_dict(), tomli.loads(LIVE))

    def test_untouched_file_is_byte_identical(self):
        self.assertEqual(SchemaFile.loads(LIVE).dumps(), LIVE)

    def test_edit_add_and_remove_keep_the_escaping(self):
        schema = SchemaFile.loads(LIVE)
        schema.set("classical_rules", NODE, ["symphony"])
        new = "Clásica\\Escénica\\Ópera"
        schema.add("classical_rules", new, ["opera"], "# new")
        text = schema.dumps()
        self.assertIn('"Clásica\\\\Escénica\\\\Ópera" = ["opera"]   # new', text)
        self.assertEqual(tomli.loads(text)["classical_rules"][new], ["opera"])
        self.assertTrue(schema.remove("classical_rules", NODE))
        self.assertNotIn(NODE, tomli.loads(schema.dumps())["classical_rules"])

    def test_the_options_become_dropdowns(self):
        d = SchemaFile.loads(LIVE).get("classical_genres", "existing").as_dict()
        self.assertEqual((d["type"], d["options"]), ("enum", ["recalc", "keep"]))


class Merge(unittest.TestCase):
    def merged(self, live_text):
        d = tempfile.mkdtemp()
        for name, text in ((M.LIVE, live_text), (M.PROPOSED, PROPOSED)):
            with open(os.path.join(d, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        live, prop = M.load_pair(d)
        M.apply(live, prop, {})
        return live.dumps()

    def test_classical_rules_is_a_map_section(self):
        self.assertIn("classical_rules", M.MAP_SECTIONS)

    def test_new_nodes_are_added_and_your_rules_are_not_touched(self):
        text = self.merged(LIVE)
        rules = tomli.loads(text)["classical_rules"]
        self.assertEqual(rules[NODE], ["symphony", "kw:sinfonia"])          # yours
        self.assertEqual(rules["Clásica\\Cámara\\Cuartetos"], ["quartet"])   # new
        self.assertIn("# 0 tracks (standard)", text)

    def test_a_missing_section_is_copied_whole(self):
        text = self.merged("[general]\nid3_version = 4\n")
        cfg = tomli.loads(text)
        self.assertEqual(cfg["classical_genres"]["existing"], "recalc")
        self.assertIn(NODE, cfg["classical_rules"])


class AlbumCard(unittest.TestCase):
    def load(self, rows):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "changes.csv")
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(C.COLUMNS)
            w.writerows(rows)
        C.invalidate()
        C._CACHE["titles"] = (0, {})
        return C.load(path, force=True)

    def test_summary_carries_the_proposed_genre_path(self):
        cs = self.load([
            ["1", "", "low", "genre-tree: %s (2 of 2 works)" % NODE, "/m/Beethoven/01.flac", "genre",
             "Classical || Baroque", NODE + " || Baroque"],
            ["2", "", "low", "genre-tree: %s (2 of 2 works)" % NODE, "/m/Beethoven/02.flac", "genre",
             "Classical", NODE],
            ["3", "y", "high", "genre: mapped", "/m/Daft/01.mp3", "genre", "House", "Electronic"],
        ])
        cards = {a["folder"]: a for a in cs.album_list()}
        beethoven = cards["/m/Beethoven"]
        self.assertEqual(beethoven["new_genre"], NODE + ", Baroque")
        self.assertEqual(beethoven["old_genre"], "Classical, Baroque")
        self.assertIsNone(cards["/m/Daft"]["new_genre"])        # a plain genre row is not a path
        self.assertEqual(cs.facets["rule"]["genre-tree"], 2)
        self.assertEqual(len(cs.filter_rows(rule="genre-tree")), 2)


class Health(unittest.TestCase):
    def health(self, text):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "schema.toml"), "w", encoding="utf-8") as fh:
            fh.write("[album]\nenabled = true\n[orchestra_abbrev]\n" + text)
        with mock.patch.object(state, "ROOT", d):
            return state.schema_health()["problems"]

    def test_missing_section(self):
        self.assertTrue(any("Falta la sección [classical_genres]" in p for p in self.health("")))

    def test_disabled(self):
        text = "[classical_genres]\nenabled = false\n[classical_rules]\n\"Clásica\" = []\n"
        self.assertTrue(any("enabled = false" in p for p in self.health(text)))

    def test_empty_rules(self):
        text = "[classical_genres]\nenabled = true\n[classical_rules]\n"
        self.assertTrue(any("[classical_rules] está vacía" in p for p in self.health(text)))

    def test_tree_problems_are_listed(self):
        text = ('[classical_genres]\nenabled = true\n[classical_rules]\n'
                '"Clásica\\\\A/B" = ["symphony"]\n')
        problems = self.health(text)
        self.assertTrue(any(p.startswith("[classical_rules]: ") for p in problems), problems)

    def test_a_good_tree_adds_nothing(self):
        text = ('[classical_genres]\nenabled = true\n[classical_rules]\n'
                '"Clásica" = []\n"Clásica\\\\Orquestal\\\\Sinfonias" = ["symphony"]\n')
        self.assertFalse([p for p in self.health(text) if "classical" in p.lower()
                          or "Clásica" in p])


class SchemaPage(unittest.TestCase):
    """Rendering and saving through the real routes (no browser, so only the HTML is checked)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "schema.toml")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(LIVE)
        for patch in (mock.patch.object(A, "SCHEMA_PATH", self.path), mock.patch.object(state, "ROOT", self.dir)):
            patch.start()
            self.addCleanup(patch.stop)
        self.client = A.app.test_client()

    def test_the_row_has_its_key_and_a_well_formed_value_attribute(self):
        html = self.client.get("/schema").get_data(as_text=True)
        self.assertIn('data-key="%s"' % NODE, html)
        self.assertIn('value="[&#34;symphony&#34;, &#34;kw:sinfonia&#34;]"', html)   # was a broken attribute
        self.assertNotIn("dropRow(this,", html)                 # the key is read from the row now
        self.assertIn("<option selected>recalc</option><option >keep</option>", html)

    def test_a_row_with_backslashes_can_be_removed(self):
        r = self.client.post("/schema/save", json={"remove": [["classical_rules", NODE]]})
        self.assertTrue(r.get_json()["ok"])
        with open(self.path, "rb") as fh:
            rules = tomli.load(fh)["classical_rules"]
        self.assertEqual(list(rules), ["Clásica"])

    def test_a_row_with_backslashes_can_be_added(self):
        new = "Clásica\\Escénica\\Ópera"
        r = self.client.post("/schema/save", json={"set": {"classical_rules": {new: ["opera"]}}})
        self.assertTrue(r.get_json()["ok"])
        with open(self.path, "rb") as fh:
            self.assertEqual(tomli.load(fh)["classical_rules"][new], ["opera"])


if __name__ == "__main__":
    unittest.main()
