"""The editor must re-emit an untouched file byte for byte."""

import difflib
import os
import unittest

from gui.schema_edit import (SchemaFile, enum_options, parse_value, render_value,
                             split_comment, split_items)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REAL = ["schema.toml", "schema.proposed.toml", "schema.example.toml"]


class RoundTrip(unittest.TestCase):
    def test_real_schemas_survive_a_parse_and_dump(self):
        for name in REAL:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                self.skipTest("%s not on disk" % name)
            with open(path, encoding="utf-8") as fh:
                original = fh.read()
            got = SchemaFile.loads(original, path).dumps()
            if got != original:
                diff = "\n".join(list(difflib.unified_diff(
                    original.splitlines(), got.splitlines(),
                    "original", "re-dumped", lineterm=""))[:40])
                self.fail("%s changed:\n%s" % (name, diff))

    def test_the_model_agrees_with_tomli(self):
        """A byte-exact dump is not enough: the values must be understood too."""
        import tomli
        for name in REAL:
            path = os.path.join(ROOT, name)
            if not os.path.exists(path):
                self.skipTest("%s not on disk" % name)
            with open(path, "rb") as fh:
                ref = tomli.load(fh)
            self.assertEqual(SchemaFile.load(path).to_dict(), ref, name)

    def test_no_trailing_newline_is_kept(self):
        self.assertEqual(SchemaFile.loads("[a]\nb = 1").dumps(), "[a]\nb = 1")


class Parsing(unittest.TestCase):
    def test_hash_inside_a_string_is_not_a_comment(self):
        self.assertEqual(split_comment('"a#b"   # real'), ('"a#b"', "   ", "# real"))

    def test_values(self):
        self.assertIs(parse_value("true"), True)
        self.assertEqual(parse_value("2"), 2)
        self.assertEqual(parse_value("0.5"), 0.5)
        self.assertEqual(parse_value('["Rock", "Hard Rock"]'), ["Rock", "Hard Rock"])
        self.assertEqual(parse_value("[]"), [])
        self.assertEqual(parse_value('" & "'), " & ")

    def test_comma_inside_a_string_does_not_split_an_array(self):
        self.assertEqual(split_items('"a, b", "c"'), ['"a, b"', ' "c"'])

    def test_enum_options_come_from_the_comment(self):
        self.assertEqual(enum_options('# "keep" | "drop" | "style"'),
                         ["keep", "drop", "style"])
        self.assertEqual(enum_options("# just prose"), [])

    def test_render_round_trips_a_regex_string(self):
        src = r"\s+(?:feat\.?|ft\.?|featuring)\s+"
        self.assertEqual(parse_value(render_value(src)), src)


class Editing(unittest.TestCase):
    def setUp(self):
        self.src = (
            "[genres]\n"
            "max_genres = 2\n"
            'unmapped = "keep"             # unmapped: "keep" | "drop" | "style"\n'
            "\n"
            "[genre_map]\n"
            '"Rock" = ["Rock"]   # 3 tracks\n'
            '# "Other" = ["?"]   # 1 tracks\n'
        )
        self.s = SchemaFile.loads(self.src)

    def test_only_the_edited_line_changes(self):
        self.s.set("genres", "max_genres", 1)
        out = self.s.dumps().splitlines()
        self.assertEqual(out[1], "max_genres = 1")
        self.assertEqual(out[2], self.src.splitlines()[2])  # comment untouched

    def test_the_trailing_comment_survives_an_edit(self):
        self.s.set("genre_map", "Rock", ["Rock", "Classic Rock"])
        self.assertIn('"Rock" = ["Rock", "Classic Rock"]   # 3 tracks',
                      self.s.dumps())

    def test_a_commented_entry_is_a_pending_row_that_can_be_activated(self):
        other = self.s.get("genre_map", "Other")
        self.assertFalse(other.active)
        self.assertNotIn("Other", self.s.to_dict()["genre_map"])
        other.set_value(["Classical", "Moderna"])
        self.assertIn('"Other" = ["Classical", "Moderna"]   # 1 tracks',
                      self.s.dumps())

    def test_prose_with_an_equals_sign_stays_a_comment(self):
        s = SchemaFile.loads("[x]\n# raw genre = [GENRE, optional STYLE].  [] = delete\n")
        self.assertEqual([l.kind for l in s.lines], ["section", "comment"])

    def test_add_and_remove(self):
        self.s.add("genre_map", "Jazz", ["Jazz"], "# new")
        self.assertIn('"Jazz" = ["Jazz"]   # new', self.s.dumps())
        self.assertTrue(self.s.remove("genre_map", "Jazz"))
        self.assertNotIn("Jazz", self.s.dumps())

    def test_a_multiline_array_keeps_its_layout(self):
        src = '[artists]\nkeep_together = [\n    "AC/DC",\n    "Hall & Oates",\n]\n'
        s = SchemaFile.loads(src)
        self.assertEqual(s.to_dict()["artists"]["keep_together"],
                         ["AC/DC", "Hall & Oates"])
        self.assertEqual(s.dumps(), src)
        s.set("artists", "keep_together", ["AC/DC"])
        self.assertEqual(s.dumps(),
                         '[artists]\nkeep_together = [\n    "AC/DC",\n]\n')

    def test_typed_view_for_the_ui(self):
        self.assertEqual(self.s.get("genres", "max_genres").as_dict()["type"], "int")
        d = self.s.get("genres", "unmapped").as_dict()
        self.assertEqual(d["type"], "enum")
        self.assertEqual(d["options"], ["keep", "drop", "style"])


if __name__ == "__main__":
    unittest.main()
