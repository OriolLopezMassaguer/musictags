"""The merge must add what the analysis found and keep what you decided."""

import os
import tempfile
import unittest

import tomli

from gui import schema_merge as M
from gui.schema_edit import SchemaFile

LIVE = '''[general]
id3_version = 4
auto_approve = ["high", "medium"]

[genres]
max_genres = 1                # lo bajé yo a mano
unmapped = "drop"

[genre_map]
"Rock" = ["Rock"]   # 3 tracks
"Moderna" = ["Classical", "Modern"]   # decidido por mí
"Vieja" = ["Classical"]   # ya no está en la biblioteca

[artists]
keep_together = [
    "AC/DC",
    "Joe Smith, Associated Performer, Violin, Main Artist - Some Orchestra, Orchestra",
]
'''

PROPOSED = '''[general]
id3_version = 4
auto_approve = ["high", "medium"]

[genres]
max_genres = 2
unmapped = "keep"

[genre_map]
"Rock" = ["Rock"]   # 3 tracks
"Moderna" = ["?"]   # 85 tracks
"Jazz" = ["Jazz"]   # 12 tracks

[artists]
keep_together = [
    "AC/DC",
    "Simon & Garfunkel",
]

[album]
# Nombres de álbum clásicos
enabled = true
min_share = 0.5

[orchestra_abbrev]
"Berliner Philharmoniker" = "BPhO"   # 9 tracks
'''


class Merge(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for name, text in ((M.LIVE, LIVE), (M.PROPOSED, PROPOSED)):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
                fh.write(text)
        self.live, self.prop = M.load_pair(self.dir)
        self.diffs = M.compare(self.live, self.prop)

    def by_id(self, key):
        return next(d for d in self.diffs if d.id == key)

    def test_missing_sections_default_to_being_added(self):
        for section in ("album", "orchestra_abbrev"):
            d = self.by_id("%s::*" % section)
            self.assertEqual((d.kind, d.default), ("section", "theirs"), section)

    def test_an_option_you_changed_defaults_to_yours(self):
        d = self.by_id("genres::max_genres")
        self.assertEqual((d.mine, d.theirs, d.default), (1, 2, "mine"))

    def test_a_new_map_entry_defaults_to_being_added(self):
        self.assertEqual(self.by_id("genre_map::Jazz").default, "theirs")

    def test_an_entry_you_decided_is_not_reset_to_the_proposals_question_mark(self):
        d = self.by_id("genre_map::Moderna")
        self.assertEqual(d.mine, ["Classical", "Modern"])
        self.assertEqual(d.default, "mine")

    def test_an_entry_no_longer_in_the_library_is_kept(self):
        d = self.by_id("genre_map::Vieja")
        self.assertEqual((d.default, d.theirs), ("mine", None))

    def test_applying_the_defaults(self):
        M.apply(self.live, self.prop, {})
        path = os.path.join(self.dir, M.LIVE)
        self.live.save(path, backup=False)
        with open(path, "rb") as fh:
            out = tomli.load(fh)
        self.assertEqual(out["album"]["enabled"], True)            # sección añadida
        self.assertIn("Berliner Philharmoniker", out["orchestra_abbrev"])
        self.assertEqual(out["genres"]["max_genres"], 1)           # lo mío, conservado
        self.assertEqual(out["genres"]["unmapped"], "drop")
        self.assertEqual(out["genre_map"]["Moderna"], ["Classical", "Modern"])
        self.assertEqual(out["genre_map"]["Jazz"], ["Jazz"])       # añadido
        self.assertIn("Vieja", out["genre_map"])                   # conservado

    def test_the_copied_section_keeps_its_comments(self):
        M.apply(self.live, self.prop, {})
        self.assertIn("# Nombres de álbum clásicos", self.live.dumps())

    def test_a_long_list_offers_mine_theirs_or_the_union(self):
        d = self.by_id("artists::keep_together")
        self.assertEqual(d.kind, "list")
        self.assertEqual(d.extra["only_theirs"], ["Simon & Garfunkel"])
        self.assertEqual(d.extra["shared"], 1)
        M.apply(self.live, self.prop, {d.id: "union"})
        self.assertEqual(
            sorted(self.live.to_dict()["artists"]["keep_together"]),
            sorted(d.extra["union"]))

    def test_choosing_theirs_replaces_the_junk_list(self):
        M.apply(self.live, self.prop, {"artists::keep_together": "theirs"})
        self.assertEqual(self.live.to_dict()["artists"]["keep_together"],
                         ["AC/DC", "Simon & Garfunkel"])


if __name__ == "__main__":
    unittest.main()
