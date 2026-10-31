"""Albums whose track titles name nothing ('Pista01', 'Track 02'): the work has to come from
the album tag or the folder. Self-contained - the schema is built here, not read from disk:

    python3 -m unittest discover tests -t .
"""
import unittest

from tests import mutagen_stub  # noqa: F401  (must come before anything that imports core)

import classical_genres as cg
import propose_changes as pc
from album_names import is_placeholder, work_of_text
from core import WRITABLE


def cfg(**album):
    """A schema with the standard classical tree and classical album names turned on."""
    opts = dict(enabled=True, scope="classical", format="{composer} - {works} ({performers})",
                composer_name="surname", max_works=3, max_soloists=2, others="etc.")
    opts.update(album)
    return {"general": {}, "artists": {}, "albumartist": {}, "composers": {}, "genres": {},
            "album": opts, "genre_map": {}, "aliases": {}, "sort_overrides": {},
            "classical_genres": {"enabled": True}, "classical_rules": dict(cg.STANDARD_TREE)}


def album(folder, name, titles, composer="Wolfgang Amadeus Mozart", artist="Ferenc Fricsay",
          genre="Classical", **extra):
    out = []
    for i, title in enumerate(titles, 1):
        t = {"title": [title], "album": [name], "artist": [artist], "tracknumber": [str(i)],
             "composer": [composer] if composer else [], "genre": [genre]}
        t.update(extra)
        out.append(("/music/%s/%02d.mp3" % (folder, i), t))
    return out


def run(schema, *albums):
    prop = pc.Proposer(schema)
    tracks = []
    for path, t in [x for a in albums for x in a]:
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


def names(tracks):
    return sorted({ch["album"][0][0] for ch in changes(tracks).values() if "album" in ch})


PISTAS = ["Pista01", "Pista02", "Pista03", "Pista04"]


class Placeholders(unittest.TestCase):
    def test_what_counts_as_a_placeholder(self):
        for t in ("Pista01", "Pista  1", "Track02", "Track 12", "Spur 2", "Piste 3", "Faixa 4",
                  "01", "007", "1-04", "CD2 - Track 05", "Audio Track 3", "Untitled", "Untitled 3",
                  "Sin titulo", "unknown", "Desconocido 2"):
            self.assertTrue(is_placeholder(t), t)

    def test_what_does_not(self):
        for t in ("Don Giovanni", "Symphony No. 5", "1812 Overture", "Prelude", "No. 5",
                  "Pista Final", "Tracks of My Tears", "Vier letzte Lieder", "Trio 2 in B"):
            self.assertFalse(is_placeholder(t), t)


class WorkOfText(unittest.TestCase):
    def test_the_composer_in_front_goes(self):
        self.assertEqual(work_of_text(["Mozart_ Requiem"], ["Wolfgang Amadeus Mozart"]),
                         ("Requiem", ""))
        self.assertEqual(work_of_text(["Mozart Requiem"], ["Wolfgang Amadeus Mozart"]),
                         ("Requiem", ""))

    def test_the_performer_goes_too(self):
        self.assertEqual(work_of_text(["Requiem Solti"], [], ["Georg Solti"]), ("Requiem", ""))

    def test_a_disc_marker_is_taken_off_and_handed_back(self):
        self.assertEqual(work_of_text(["Cello concertos v4"], []), ("Cello concertos", "4"))
        self.assertEqual(work_of_text(["Don Giovanni CD 2"], []), ("Don Giovanni", "2"))

    def test_an_all_lowercase_name_is_title_cased(self):
        self.assertEqual(work_of_text(["sonatas praga"], []), ("Sonatas Praga", ""))

    def test_a_bare_number_is_part_of_the_name(self):
        self.assertEqual(work_of_text(["Symphony 40"], []), ("Symphony 40", ""))
        self.assertEqual(work_of_text(["Don Giovanni 1"], []), ("Don Giovanni 1", ""))

    def test_the_first_text_that_says_something_wins(self):
        self.assertEqual(work_of_text(["CD1", "Sonatas Praga"], []), ("Sonatas Praga", ""))

    def test_a_name_this_tool_wrote_before_is_read_back(self):
        self.assertEqual(work_of_text(["Mozart - Pista01, Pista02, etc. (Fricsay) [Don Giovanni 1]"],
                                      ["Wolfgang Amadeus Mozart"], ["Ferenc Fricsay"]),
                         ("Don Giovanni 1", ""))

    def test_nothing_to_say(self):
        self.assertEqual(work_of_text(["Pista 01"], []), ("", ""))
        self.assertEqual(work_of_text(["CD 2"], []), ("", ""))
        self.assertEqual(work_of_text([""], []), ("", ""))


class AlbumOfPlaceholders(unittest.TestCase):
    def test_the_folder_names_the_work(self):
        tracks = run(cfg(), album("Don Giovanni 1", "Don Giovanni 1", PISTAS))
        self.assertEqual(names(tracks), ["Mozart - Don Giovanni 1 (Ferenc Fricsay)"])

    def test_no_placeholder_reaches_the_album_name_or_the_work_tag(self):
        tracks = run(cfg(), album("Don Giovanni 1", "Don Giovanni 1", PISTAS))
        for ch in changes(tracks).values():
            for field, (new, _, _) in ch.items():
                self.assertFalse(any(is_placeholder(v) for v in new), (field, new))

    def test_the_work_tag_is_proposed_low_from_the_folder(self):
        tracks = run(cfg(), album("Don Giovanni 1", "Don Giovanni 1", PISTAS))
        work = [ch["work"] for ch in changes(tracks).values() if "work" in ch]
        self.assertEqual(len(work), len(PISTAS))
        self.assertEqual(work[0][0], ["Don Giovanni 1"])
        self.assertEqual(work[0][1], "low")
        self.assertIn("placeholder", work[0][2])

    def test_a_title_that_does_name_a_work_is_kept(self):
        tracks = run(cfg(), album("Cello concertos v1", "Cello concertos v1",
                                  ["Pista 01", "Pista 02", "RV 419"]))
        self.assertEqual(names(tracks), ["Mozart - Cello concertos & RV 419 (Ferenc Fricsay)"])

    def test_discs_of_one_set_are_told_apart_by_their_number(self):
        tracks = run(cfg(), album("Concertos vol 1", "Concertos vol 1", PISTAS),
                     album("Concertos vol 2", "Concertos vol 2", PISTAS))
        self.assertEqual(names(tracks), ["Mozart - Concertos (Ferenc Fricsay) [1]",
                                         "Mozart - Concertos (Ferenc Fricsay) [2]"])

    def test_an_album_nothing_can_name_is_left_alone(self):
        tracks = run(cfg(), album("01", "Untitled", PISTAS))
        self.assertEqual(names(tracks), [])

    def test_the_genre_tree_votes_on_the_album_text_not_on_the_placeholders(self):
        # 'Pista01' matches no rule; without the album text the album would land on the root
        tracks = run(cfg(), album("Mozart Requiem", "Mozart Requiem", PISTAS))
        genres = {tuple(ch["genre"][0]) for ch in changes(tracks).values() if "genre" in ch}
        self.assertEqual(genres, {("Clásica\\Religiosa\\Misa",)})

    def test_running_it_again_proposes_nothing(self):
        schema = cfg()
        tracks = run(schema, album("Don Giovanni 1", "Don Giovanni 1", PISTAS))
        applied = []
        for path, t, p, _ in tracks:
            t = dict(t)
            t.update({f: new for f, (new, _, _) in p.items() if f in WRITABLE})
            applied.append((path, t))
        self.assertEqual(changes(run(schema, applied)), {})


class GenrePathSpelling(unittest.TestCase):
    PATH = "Clásica\\Cámara\\Piano Solo"

    def sonatas(self, folder, genre):
        return album(folder, folder, ["Piano Sonata No. 14: I. Adagio",
                                      "Piano Sonata No. 14: II. Allegretto"],
                     composer="Ludwig van Beethoven", artist="Sviatoslav Richter", genre=genre)

    def test_another_spelling_of_the_same_node_is_normalised(self):
        tracks = run(cfg(), self.sonatas("Sonatas", "Clásica\\cámara\\piano Solo"))
        rows = [ch["genre"] for ch in changes(tracks).values() if "genre" in ch]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], [self.PATH])

    def test_the_schema_spelling_makes_no_row(self):
        tracks = run(cfg(), self.sonatas("Sonatas", self.PATH))
        self.assertEqual([ch for ch in changes(tracks).values() if "genre" in ch], [])

    def test_a_node_of_your_own_keeps_its_own_path(self):
        # no rule matches these titles, so the path in the files stays - respelled, not replaced
        schema = cfg()
        schema["classical_rules"]["Clásica\\Cámara\\Piano Sonatas"] = []
        tracks = run(schema, album("Sonatas", "Sonatas", ["Allegro", "Andante"],
                                   composer="Ludwig van Beethoven", artist="Sviatoslav Richter",
                                   genre="Clásica\\cámara\\piano Sonatas"))
        rows = [ch["genre"] for ch in changes(tracks).values() if "genre" in ch]
        self.assertEqual(rows[0][0], ["Clásica\\Cámara\\Piano Sonatas"])
        self.assertEqual(rows[0][1], "high")


if __name__ == "__main__":
    unittest.main()
