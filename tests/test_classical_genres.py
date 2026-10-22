"""classical_genres.py is dependency-free, so these run anywhere:
    python3 -m unittest discover tests -t .
"""
import unittest
from collections import Counter, OrderedDict

import classical_genres as cg
from classical_genres import (STANDARD_TREE, Tree, compare, detect_root, extract_concepts, path_key,
                              rebase, swap_classical, tree_status)


def tree(rules=None, **opts):
    cfg = {"classical_genres": dict(opts), "classical_rules": dict(rules or STANDARD_TREE)}
    return Tree.from_cfg(cfg)


def works(*items):
    """('Symphony No. 5', composer) ... -> {work: Concepts} the way propose_changes builds it."""
    return {w: extract_concepts(work=w, composers=c) for w, c in items}


class PathKey(unittest.TestCase):
    def test_backslash_is_kept(self):
        self.assertNotEqual(path_key("Clásica\\Cámara"), path_key("Clásica Cámara"))
        self.assertEqual(path_key("Clásica\\Cámara"), "clasica\\camara")

    def test_accents_case_and_spaces_fold(self):
        self.assertEqual(path_key(" CLASICA \\ Camara "), path_key("Clásica\\Cámara"))

    def test_empty_segments_vanish(self):
        self.assertEqual(path_key("Clásica\\\\Cámara\\"), "clasica\\camara")


class TreeBuilding(unittest.TestCase):
    def test_status(self):
        self.assertEqual(tree_status({}), "missing")
        self.assertEqual(tree_status({"classical_genres": {"enabled": False}}), "disabled")
        self.assertEqual(tree_status({"classical_genres": {}}), "empty")
        self.assertEqual(tree_status({"classical_genres": {}, "classical_rules": {"A": []}}), "ok")

    def test_none_when_not_usable(self):
        self.assertIsNone(Tree.from_cfg({}))
        self.assertIsNone(Tree.from_cfg({"classical_genres": {"enabled": False},
                                         "classical_rules": {"A": []}}))
        self.assertIsNone(Tree.from_cfg({"classical_genres": {}, "classical_rules": {}}))

    def test_standard_tree_has_no_problems(self):
        t = tree()
        self.assertEqual(t.problems, [])
        self.assertEqual(t.root, "Clásica")

    def test_duplicate_by_path_key(self):
        t = tree({"Clásica": [], "Clásica\\Cámara": [], "clasica\\CAMARA": ["quartet"]})
        self.assertTrue(any("same node" in p for p in t.problems))
        self.assertEqual(len(t.nodes), 2)

    def test_separators_inside_a_node(self):
        t = tree({"Clásica": [], "Clásica\\Dúos/Tríos": []})
        self.assertTrue(any("cut in two" in p for p in t.problems))

    def test_bad_values(self):
        t = tree({"Clásica": [], "Clásica\\A": "symphony", "Clásica\\B": ["nonsense"],
                  "Clásica\\C": ["symphony+"], "Clásica\\\\D": []})
        text = "\n".join(t.problems)
        self.assertIn("list of rule strings", text)
        self.assertIn("unknown concept", text)
        self.assertIn("empty path segment", text)

    def test_bad_options(self):
        t = tree(existing="sometimes", majority=1.5, no_match="root")
        text = "\n".join(t.problems)
        self.assertIn("existing", text)
        self.assertIn("majority", text)
        self.assertEqual(t.opts["existing"], "recalc")          # the default survives
        self.assertEqual(t.opts["majority"], 0.6)

    def test_prefixed_terms_are_valid(self):
        t = tree({"Clásica": [], "Clásica\\X": ["composer:Dvořák", "kw:Misa", "period:Baroque+symphony"]})
        self.assertEqual(t.problems, [])
        self.assertIn(("composer:dvorak",), t.nodes["Clásica\\X"])


class SingleValues(unittest.TestCase):
    def setUp(self):
        self.t = tree()

    def test_lookup_respells(self):
        self.assertEqual(self.t.lookup("clasica\\orquestal\\SINFONIAS"), "Clásica\\Orquestal\\Sinfonias")
        self.assertIsNone(self.t.lookup("Classical"))

    def test_is_prior(self):
        for ok in ("Clásica", "Clásica\\Orquestal\\Sinfonias", "Clásica\\Cámara\\Dúos"):
            self.assertTrue(self.t.is_prior(ok), ok)
        for no in ("Classical", "Rock", "Jazz\\Bebop", "Clásica Cámara"):
            self.assertFalse(self.t.is_prior(no), no)

    def test_foreign_is_a_path_under_your_root_only(self):
        self.assertTrue(self.t.is_foreign("Clásica\\Cámara\\Dúos"))
        self.assertFalse(self.t.is_foreign("Clásica"))                    # bare root is not a path
        self.assertFalse(self.t.is_foreign("Clásica\\Orquestal\\Sinfonias"))

    def test_packed_value_is_not_foreign(self):
        self.assertFalse(self.t.is_foreign("Clásica\\Orquestal\\Sinfonias; Baroque"))

    def test_priors_in_unpacks_id3v23_values(self):
        split = lambda raw: [x.strip() for x in raw.split(";")]
        got = self.t.priors_in(["Clásica\\Orquestal\\Sinfonias; Baroque", "Rock", "Clásica"], split)
        self.assertEqual(got, ["Clásica\\Orquestal\\Sinfonias", "Clásica"])


class Extractor(unittest.TestCase):
    def tags(self, work, composers=(), periods=()):
        return extract_concepts(work=work, composers=composers, periods=periods).tags

    def test_forms_in_several_languages(self):
        cases = {
            "Symphony No. 5 in C minor, Op. 67": "symphony",
            "Sinfonía n.º 9": "symphony",
            "Sinfonie Nr. 3 Es-Dur": "symphony",
            "Symphonie fantastique": "symphony",
            "Concerto for Violin in D major": "concerto",
            "Concierto de Aranjuez": "concerto",
            "Klavierkonzert Nr. 5": "concerto",
            "Violinkonzert D-Dur": "concerto",
            "Requiem in D minor, K. 626": "requiem",
            "Missa Pange lingua": "mass",
            "Misa en si menor": "mass",
            "String Quartet No. 14": "quartet",
            "Cuarteto de cuerda": "quartet",
            "Piano Trio in B-flat": "trio",
            "Don Giovanni": None,
            "Overture to Egmont": "overture",
            "Obertura de Rienzi": "overture",
            "Cello Suite No. 1": "suite",
            "Ballet: Swan Lake": "ballet",
        }
        for work, form in cases.items():
            if form is None:
                continue
            self.assertIn(form, self.tags(work), work)

    def test_orchestra_names_are_not_forms(self):
        for text in ("Berlin Symphony Orchestra", "Orquesta Sinfónica de Barcelona",
                     "Orchestre Symphonique de Montréal"):
            self.assertNotIn("symphony", extract_concepts(text=text).tags, text)
        self.assertIn("symphony", extract_concepts(work="Symphony No. 1", text="x").tags)

    def test_source_is_work_then_title_then_text(self):
        self.assertIn("symphony", extract_concepts(work="Symphony No. 5", title="Requiem").tags)
        self.assertNotIn("requiem", extract_concepts(work="Symphony No. 5", title="Requiem").tags)
        self.assertIn("requiem", extract_concepts(title="Requiem", text="Symphony").tags)
        self.assertIn("mass", extract_concepts(text="Missa solemnis").tags)

    def test_instrument_policy(self):
        self.assertIn("cello", self.tags("Cello Suite No. 1"))
        self.assertIn("violin", self.tags("Sonata for Violin and Piano"))       # first non-piano
        self.assertNotIn("piano", self.tags("Sonata for Violin and Piano"))
        self.assertIn("piano", self.tags("Piano Sonata No. 14"))                # alone
        self.assertIn("piano", self.tags("Piano Concerto No. 21"))

    def test_german_compounds_carry_the_instrument(self):
        self.assertTrue({"concerto", "piano"} <= self.tags("Klavierkonzert Nr. 5"))
        self.assertTrue({"sonata", "cello"} <= self.tags("Cellosonate in d-moll"))
        self.assertIn("violin", self.tags("Violinkonzert D-Dur"))

    def test_double_concerto_is_multi(self):
        t = self.tags("Concerto for Violin and Cello in A minor")
        self.assertIn("multi", t)
        self.assertNotIn("violin", t)
        self.assertNotIn("cello", t)

    def test_composer_and_period(self):
        t = self.tags("Symphony No. 9", ["Antonín Dvořák", "Johann Strauss Jr."],
                      ["Romantic", "Classical Period"])
        self.assertIn("composer:dvorak", t)
        self.assertIn("composer:strauss", t)                  # 'Jr.' is not the surname
        self.assertIn("period:romantic", t)
        self.assertIn("period:classical", t)

    def test_concerto_grosso_is_also_a_concerto(self):
        t = self.tags("Concerto grosso Op. 6 No. 8")
        self.assertIn("concerto_grosso", t)
        self.assertIn("concerto", t)

    def test_kw_matches_the_folded_text(self):
        c = extract_concepts(work="Música acuática, HWV 348")
        self.assertTrue(c.has("kw:musica acuatica"))
        self.assertFalse(c.has("kw:fireworks"))

    def test_empty(self):
        self.assertEqual(extract_concepts().tags, frozenset())


class Classify(unittest.TestCase):
    def setUp(self):
        self.t = tree()

    def node(self, work, composers=(), periods=()):
        return self.t.classify(extract_concepts(work=work, composers=composers, periods=periods))

    def test_standard_examples(self):
        cases = [
            (("Symphony No. 5", ["Ludwig van Beethoven"], ["Classical Period"]), "Clásica\\Orquestal\\Sinfonias"),
            (("Cello Concerto in B minor, Op. 104", ["Antonín Dvořák"], ["Romantic"]), "Clásica\\Conciertos\\Cello"),
            (("Piano Concerto No. 20", ["Wolfgang Amadeus Mozart"], ["Classical Period"]), "Clásica\\Conciertos\\Piano"),
            (("Requiem in D minor", ["Wolfgang Amadeus Mozart"], ["Classical Period"]), "Clásica\\Religiosa\\Misa"),
            (("Cello Suite No. 1 in G major, BWV 1007", ["Johann Sebastian Bach"], ["Baroque"]), "Clásica\\Cámara\\Sonatas Cello"),
            (("String Quartet No. 14", ["Franz Schubert"], ["Romantic"]), "Clásica\\Cámara\\Cuartetos"),
            (("The Nutcracker, ballet in two acts", ["Pyotr Ilyich Tchaikovsky"], ["Romantic"]), "Clásica\\Escénica\\Ballet"),
            (("Overture to Egmont", ["Ludwig van Beethoven"], ["Classical Period"]), "Clásica\\Orquestal\\Otros"),
        ]
        for (work, comps, periods), want in cases:
            self.assertEqual(self.node(work, comps, periods), want, work)

    def test_period_beats_form_only_by_specificity(self):
        # 'period:baroque+symphony' has two terms, so it outranks the one-term 'symphony'.
        self.assertEqual(self.node("Symphony No. 1", ["Johann Christian Bach"], ["Baroque"]),
                         "Clásica\\Orquestal\\Barroco")
        self.assertEqual(self.node("Symphony No. 1", ["Joseph Haydn"], ["Classical Period"]),
                         "Clásica\\Orquestal\\Sinfonias")

    def test_early_music_by_period(self):
        self.assertEqual(self.node("Missa Pange lingua", ["Josquin des Prez"], ["Renaissance"]),
                         "Clásica\\Antigua")

    def test_file_order_breaks_ties(self):
        rules = OrderedDict([("Clásica", []), ("Clásica\\B", ["symphony"]), ("Clásica\\A", ["symphony"])])
        self.assertEqual(tree(rules).classify(extract_concepts(work="Symphony No. 1")), "Clásica\\B")

    def test_specificity_beats_file_order(self):
        rules = OrderedDict([("Clásica", []), ("Clásica\\Any", ["concerto"]),
                             ("Clásica\\Piano", ["concerto+piano"])])
        self.assertEqual(tree(rules).classify(extract_concepts(work="Piano Concerto No. 1")),
                         "Clásica\\Piano")

    def test_no_match(self):
        self.assertIsNone(self.node("Boléro", ["Maurice Ravel"], ["Modern"]))
        self.assertEqual(self.node("Gymnopédie No. 1", ["Erik Satie"], ["Modern"]),     # keyboard_form
                         "Clásica\\Cámara\\Piano Solo")


class Decide(unittest.TestCase):
    def setUp(self):
        self.t = tree()
        self.sym = "Clásica\\Orquestal\\Sinfonias"

    def test_unanimous_and_covered_is_medium(self):
        d = self.t.decide([self.sym, self.sym], 2)
        self.assertEqual((d.path, d.conf, d.how, d.n, d.m), (self.sym, "medium", "unanimous", 2, 2))

    def test_unanimous_but_barely_covered_is_low(self):
        d = self.t.decide([self.sym, self.sym], 3)                # 2/3 < 0.8
        self.assertEqual((d.path, d.conf), (self.sym, "low"))

    def test_majority_is_low(self):
        con = "Clásica\\Conciertos\\Piano"
        d = self.t.decide([self.sym, self.sym, self.sym, con], 4)
        self.assertEqual((d.path, d.conf, d.how), (self.sym, "low", "majority"))

    def test_never_high(self):
        for votes, total in (([self.sym], 1), ([self.sym] * 9, 9)):
            self.assertNotEqual(self.t.decide(votes, total).conf, "high")

    def test_coverage_below_threshold_is_none(self):
        self.assertIsNone(self.t.decide([self.sym], 3))           # 1/3 < 0.5
        self.assertIsNone(self.t.decide([], 3))
        self.assertIsNone(self.t.decide([self.sym], 0))

    def test_coverage_threshold_is_configurable(self):
        t = tree(min_coverage=0.3)
        self.assertEqual(t.decide([self.sym], 3).path, self.sym)

    def test_mixed_goes_to_the_common_varios(self):
        d = self.t.decide([self.sym, "Clásica\\Conciertos\\Piano"], 2)
        self.assertEqual((d.path, d.conf, d.how), ("Clásica\\Varios", "low", "common"))

    def test_mixed_inside_a_branch_uses_that_branchs_varios(self):
        d = self.t.decide(["Clásica\\Conciertos\\Piano", "Clásica\\Conciertos\\Cello"], 2)
        self.assertEqual(d.path, "Clásica\\Conciertos\\Varios")

    def test_otros_when_there_is_no_varios(self):
        d = self.t.decide(["Clásica\\Cámara\\Cuartetos", "Clásica\\Cámara\\Tríos"], 2)
        self.assertEqual(d.path, "Clásica\\Cámara\\Otros")

    def test_ancestor_itself_without_a_fallback_child(self):
        rules = OrderedDict([("Clásica", []), ("Clásica\\A\\X", ["quartet"]), ("Clásica\\A\\Y", ["trio"])])
        d = tree(rules).decide(["Clásica\\A\\X", "Clásica\\A\\Y"], 2)
        self.assertEqual(d.path, "Clásica")                       # 'Clásica\\A' is not a node: climb to the root

    def test_ties_are_deterministic(self):
        a, b = "Clásica\\Cámara\\Cuartetos", "Clásica\\Cámara\\Tríos"
        self.assertEqual(self.t.decide([a, b], 2).path, self.t.decide([b, a], 2).path)

    def test_album_text_is_the_last_resort(self):
        fb = extract_concepts(text="Beethoven: Symphony No. 7")
        w = works(("Allegro", []), ("Adagio", []))                     # no work matches
        d = self.t.album_decision(w, fb)
        self.assertEqual((d.path, d.conf, d.how), (self.sym, "low", "album-text"))
        w = works(("Symphony No. 5", []), ("Allegro", []), ("Adagio", []))    # 1 of 3: too few
        self.assertEqual(self.t.album_decision(w, extract_concepts(text="Requiem")).path,
                         "Clásica\\Religiosa\\Misa")
        self.assertIsNone(self.t.album_decision(w, None))

    def test_album_text_never_overrides_the_works(self):
        w = works(("Symphony No. 5", []), ("Allegro", []))             # 1 of 2: enough
        d = self.t.album_decision(w, extract_concepts(text="Requiem"))
        self.assertEqual((d.path, d.how), (self.sym, "unanimous"))


class Resolve(unittest.TestCase):
    def setUp(self):
        self.t = tree()
        self.sym = "Clásica\\Orquestal\\Sinfonias"
        self.dec = cg.Decision(self.sym, "medium", "unanimous", 2, 2)

    def test_no_prior_takes_the_decision(self):
        r = self.t.resolve(self.dec, Counter())
        self.assertEqual((r.path, r.conf, r.was), (self.sym, "medium", None))

    def test_same_path_other_spelling_normalises(self):
        r = self.t.resolve(self.dec, Counter({"clasica\\orquestal\\sinfonias": 3}))
        self.assertEqual((r.path, r.conf, r.was), (self.sym, "medium", None))

    def test_flat_root_is_refined(self):
        r = self.t.resolve(self.dec, Counter({"Clásica": 5}))
        self.assertEqual((r.path, r.conf, r.was), (self.sym, "medium", None))

    def test_more_specific_prior_is_kept(self):
        dec = cg.Decision("Clásica\\Orquestal\\Otros", "medium", "unanimous", 1, 1)
        self.assertIsNone(self.t.resolve(dec, Counter({"Clásica\\Orquestal\\Otros\\Poemas": 2})))

    def test_prior_that_disagrees_gives_low_with_was(self):
        r = self.t.resolve(self.dec, Counter({"Clásica\\Cámara\\Cuartetos": 4}))
        self.assertEqual((r.path, r.conf, r.was), (self.sym, "low", "Clásica\\Cámara\\Cuartetos"))

    def test_most_common_prior_wins(self):
        r = self.t.resolve(self.dec, Counter({"Clásica\\Cámara\\Cuartetos": 1, "Clásica\\Cámara\\Tríos": 3}))
        self.assertEqual(r.was, "Clásica\\Cámara\\Tríos")

    def test_keep_ignores_real_paths_but_not_the_flat_root(self):
        t = tree(existing="keep")
        self.assertIsNone(t.resolve(self.dec, Counter({"Clásica\\Cámara\\Cuartetos": 1})))
        r = t.resolve(self.dec, Counter({"Clásica": 1}))
        self.assertEqual(r.path, self.sym)

    def test_no_decision(self):
        self.assertIsNone(self.t.resolve(None, Counter({"Clásica\\Cámara\\Dúos": 1})))     # a prior is kept
        r = self.t.resolve(None, Counter())
        self.assertEqual((r.path, r.conf, r.was), ("Clásica", "low", None))                # no_match = root
        self.assertIsNone(tree(no_match="keep").resolve(None, Counter()))


class SwapClassical(unittest.TestCase):
    def test_replaces_first_and_drops_repeats(self):
        self.assertEqual(swap_classical(["Classical", "Jazz", "Classical"], "A\\B"), ["A\\B", "Jazz"])
        self.assertEqual(swap_classical(["Jazz", "Classical"], "A\\B"), ["Jazz", "A\\B"])
        self.assertEqual(swap_classical(["Rock"], "A\\B"), ["Rock"])
        self.assertEqual(swap_classical(["Classical", "A\\B"], "A\\B"), ["A\\B"])


class Standard(unittest.TestCase):
    def test_rebase(self):
        out = rebase("Música Clásica")
        self.assertIn("Música Clásica\\Orquestal\\Sinfonias", out)
        self.assertIn("Música Clásica", out)
        self.assertEqual(len(out), len(STANDARD_TREE))
        self.assertEqual(out["Música Clásica\\Orquestal\\Sinfonias"], ["symphony"])

    def test_detect_root(self):
        self.assertEqual(detect_root({}), "Clásica")
        lib = {"Música Clásica\\A": (1, 10), "Música Clásica\\B": (1, 5), "Clásica\\C": (1, 8)}
        self.assertEqual(detect_root(lib), "Música Clásica")
        self.assertEqual(detect_root({"clasica\\X": (1, 2), "Clásica\\Y": (1, 2), "Clásica": (1, 1)}), "clasica")

    def test_compare_statuses(self):
        lib = {
            "Clásica\\Orquestal\\Sinfonias": (3, 30),
            "clasica\\cámara\\cuartetos": (1, 8),
            "Clásica\\Cámara\\Sonatas Violin Y Piano": (2, 12),
            "Clásica\\Cámara\\Dúos": (1, 4),
        }
        c = compare(lib)
        by = {r[0]: r for r in c.rows}
        self.assertEqual(by["Clásica\\Orquestal\\Sinfonias"][3:], ("same", "Clásica\\Orquestal\\Sinfonias"))
        self.assertEqual(by["clasica\\cámara\\cuartetos"][3], "accents/case")
        self.assertEqual(by["Clásica\\Cámara\\Sonatas Violin Y Piano"][3:],
                         ("extends", "Clásica\\Cámara\\Sonatas Violin"))
        self.assertEqual(by["Clásica\\Cámara\\Dúos"][3:], ("not in standard", None))
        self.assertNotIn("Clásica\\Orquestal\\Sinfonias", c.absent)
        self.assertNotIn("Clásica\\Cámara\\Sonatas Violin", c.absent)        # adopted by the extension
        self.assertIn("Clásica\\Cámara\\Tríos", c.absent)
        self.assertEqual(c.root, "Clásica")

    def test_compare_seed_order_and_spelling(self):
        lib = {"clasica\\cámara\\cuartetos": (1, 8), "Clásica\\Cámara\\Dúos": (1, 4)}
        seed = compare(lib).seed
        origins = [s[2] for s in seed]
        self.assertEqual(origins, sorted(origins, key=["std", "mine", "absent"].index))
        paths = [s[0] for s in seed]
        self.assertIn("clasica\\cámara\\cuartetos", paths)                 # your spelling, not the standard's
        self.assertNotIn("Clásica\\Cámara\\Cuartetos", paths)
        mine = [s for s in seed if s[2] == "mine"]
        self.assertEqual([m[0] for m in mine], ["Clásica\\Cámara\\Dúos"])
        self.assertEqual(mine[0][1], [])                                    # no rules for your own nodes
        absent = [s for s in seed if s[2] == "absent"]
        self.assertTrue(absent and all(s[3:] == (0, 0) for s in absent))

    def test_seed_loads_as_a_problem_free_tree(self):
        lib = {"clasica\\cámara\\cuartetos": (1, 8), "Clásica\\Cámara\\Dúos": (1, 4),
               "Clásica\\Cámara\\Sonatas Violin Y Piano": (2, 12)}
        seed = compare(lib).seed
        t = tree({p: rules for p, rules, *_ in seed})
        self.assertEqual(t.problems, [])
        c = extract_concepts(work="String Quartet No. 1")
        self.assertEqual(t.classify(c), "clasica\\cámara\\cuartetos")
        c = extract_concepts(work="Sonata for Violin and Piano No. 5")
        self.assertEqual(t.classify(c), "Clásica\\Cámara\\Sonatas Violin Y Piano")

    def test_custom_root_is_used_everywhere(self):
        lib = {"Música Clásica\\Orquestal\\Sinfonias": (2, 20)}
        c = compare(lib)
        self.assertEqual(c.root, "Música Clásica")
        self.assertTrue(all(p.startswith("Música Clásica") for p, *_ in c.seed))


if __name__ == "__main__":
    unittest.main()
