"""changes.csv must survive a load/save cycle with only `approve` and `new` touched."""

import csv
import os
import tempfile
import unittest

from gui import changes as C

HEADER = C.COLUMNS
ROWS = [
    # id approve conf    rule                         path                       field         old        new
    ["1", "",  "low",    "album: classical name",     "/m/Bach/CD1/01.m4a",      "album",      "Viejo",   "Bach - Suites"],
    ["2", "y", "high",   "albumartist: all same",     "/m/Bach/CD1/01.m4a",      "albumartist", "",       "Pablo Casals"],
    ["3", "",  "low",    "album: classical name",     "/m/Bach/CD2/02.m4a",      "album",      "Viejo",   "Bach - Suites"],
    ["4", "y", "medium", "genre: mapped",             "/m/Daft/01.mp3",          "genre",      "House",   "Electronic || Dance"],
]


def write_csv(path, rows=ROWS):
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)


class ChangesCsv(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "changes.csv")
        write_csv(self.path)
        C.invalidate()
        C._CACHE.pop("titles", None)
        # no tags.sqlite in the temp dir: grouping falls back to the album column
        C._CACHE["titles"] = (0, {})
        self.cs = C.load(self.path, force=True)

    def test_cd_subfolders_are_one_album(self):
        """album_key() collapses CD1/CD2, so the two Bach rows share one group."""
        self.assertEqual(len(self.cs.albums), 2)
        bach = [a for a in self.cs.album_list() if a["display"] == "Viejo"][0]
        self.assertEqual(bach["tracks"], 2)
        self.assertEqual(bach["new_album"], "Bach - Suites")

    def test_facets_count_every_row(self):
        self.assertEqual(self.cs.facets["confidence"], {"low": 2, "high": 1, "medium": 1})
        self.assertEqual(self.cs.facets["rule"]["album"], 2)

    def test_filters(self):
        self.assertEqual(len(self.cs.filter_rows(confidence="low")), 2)
        self.assertEqual(len(self.cs.filter_rows(field="genre")), 1)
        self.assertEqual(len(self.cs.filter_rows(pending=True)), 2)
        self.assertEqual(len(self.cs.filter_rows(q="casals")), 1)

    def test_lists_split_on_the_csv_separator(self):
        row = self.cs.row_dict(3)
        self.assertEqual(row["new"], ["Electronic", "Dance"])

    def test_saving_touches_only_approve(self):
        with open(self.path, encoding="utf-8-sig") as fh:
            before = fh.read()
        self.cs.set_approved(self.cs.filter_rows(confidence="low"), True)
        self.cs.save(backup=False)
        with open(self.path, newline="", encoding="utf-8-sig") as fh:
            after = list(csv.reader(fh))
        self.assertEqual(after[0], HEADER)
        self.assertEqual([r[1] for r in after[1:]], ["y", "y", "y", "y"])
        for i, row in enumerate(after[1:]):
            for col in range(len(HEADER)):
                if col != 1:
                    self.assertEqual(row[col], ROWS[i][col], "columna %s" % HEADER[col])
        with open(self.path, encoding="utf-8-sig") as fh:
            self.assertNotEqual(before, fh.read())

    def test_approval_tokens_match_apply_changes(self):
        self.assertTrue(C.approved("y"))
        self.assertTrue(C.approved("Sí"))
        self.assertFalse(C.approved(""))
        self.assertFalse(C.approved("n"))

    def test_editing_a_proposed_value(self):
        self.assertTrue(self.cs.set_new(0, "Bach - Cello Suites"))
        self.cs.save(backup=False)
        with open(self.path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[1][7], "Bach - Cello Suites")

    def test_a_csv_with_other_columns_is_rejected(self):
        bad = os.path.join(self.dir, "bad.csv")
        with open(bad, "w", newline="", encoding="utf-8-sig") as fh:
            csv.writer(fh).writerow(["approve", "path"])
        C.invalidate()
        with self.assertRaises(ValueError):
            C.load(bad, force=True)


if __name__ == "__main__":
    unittest.main()
