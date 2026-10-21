"""Merge schema.proposed.toml into schema.toml without losing your decisions.

analyze_tags.py rewrites schema.proposed.toml wholesale on every run and there is no
merge logic anywhere, so the hand-made decisions that live only in schema.toml --
mapped genres, orchestra codes, keep_together, aliases -- are lost the moment you
copy the new proposal over it. The README's answer is a manual `cp`. This is the
answer instead.

Defaults follow one rule: the analysis knows what is *in the library*, you know what
the values should *be*. So anything new is added, and anything you changed is kept.
"""

import os

from gui.runner import ROOT
from gui.schema_edit import SchemaFile

# Sections whose keys are data (one row per genre/orchestra/name), not options.
MAP_SECTIONS = {"genre_map", "orchestra_abbrev", "aliases", "sort_overrides"}
LIVE = "schema.toml"
PROPOSED = "schema.proposed.toml"


class Diff:
    """One difference the merge page offers to resolve."""

    def __init__(self, kind, section, key=None, mine=None, theirs=None,
                 default="theirs", note="", comment="", extra=None):
        self.kind = kind          # section | option | entry | pending | list
        self.section = section
        self.key = key
        self.mine = mine
        self.theirs = theirs
        self.default = default    # mine | theirs | skip
        self.note = note
        self.comment = comment
        self.extra = extra or {}

    @property
    def id(self):
        return "%s::%s" % (self.section, self.key if self.key is not None else "*")

    def as_dict(self):
        return {"id": self.id, "kind": self.kind, "section": self.section,
                "key": self.key, "mine": self.mine, "theirs": self.theirs,
                "default": self.default, "note": self.note,
                "comment": self.comment, **self.extra}


def load_pair(root=ROOT):
    live_path, prop_path = os.path.join(root, LIVE), os.path.join(root, PROPOSED)
    live = SchemaFile.load(live_path) if os.path.exists(live_path) else None
    prop = SchemaFile.load(prop_path) if os.path.exists(prop_path) else None
    return live, prop


def compare(live, prop):
    """All differences, in the order the page should show them."""
    diffs = []
    if prop is None:
        return diffs
    if live is None:
        return [Diff("section", s, note="Esquema nuevo entero.") for s in prop.sections()]

    live_sections = live.sections()
    for section in prop.sections():
        if section not in live_sections:
            diffs.append(Diff("section", section, theirs=_preview(prop, section),
                              note="Sección que no tienes."))
            continue
        diffs.extend(_compare_section(live, prop, section))

    for section in live_sections:
        if section not in prop.sections():
            diffs.append(Diff("section", section, mine=_preview(live, section),
                              default="mine", note="Solo la tienes tú; se conserva."))
    return diffs


def _preview(schema, section, limit=12):
    lines = [l.raw for l in schema.section_lines(section) if l.kind != "blank"]
    return lines[:limit] + (["…  (%d líneas más)" % (len(lines) - limit)]
                            if len(lines) > limit else [])


def _compare_section(live, prop, section):
    diffs = []
    mine = {l.key: l for l in live.pairs(section)}
    theirs = {l.key: l for l in prop.pairs(section)}
    is_map = section in MAP_SECTIONS

    for key, line in theirs.items():
        other = mine.get(key)
        if other is None:
            kind = "entry" if is_map else "option"
            diffs.append(Diff(kind, section, key, theirs=line.value, default="theirs",
                              comment=_comment(line),
                              note="Nuevo en la biblioteca." if is_map else "Opción nueva.",
                              extra={"active": line.active}))
        elif other.value != line.value:
            # A list option (taxonomy, keep_together, separators) reads far better as
            # "these went, these came" than as two long literals. Map values are
            # excluded: there [GENRE, STYLE] is an ordered pair, not a set.
            if not is_map and isinstance(other.value, list) \
                    and isinstance(line.value, list):
                diffs.append(_list_diff(section, key, other, line))
            else:
                diffs.append(Diff("entry" if is_map else "option", section, key,
                                  mine=other.value, theirs=line.value, default="mine",
                                  comment=_comment(line),
                                  note="Lo cambiaste tú; se conserva lo tuyo."))
        elif not other.active and line.active:
            diffs.append(Diff("entry" if is_map else "option", section, key,
                              mine=None, theirs=line.value, default="theirs",
                              comment=_comment(line),
                              note="Lo tienes comentado; el análisis lo activa."))

    for key, line in mine.items():
        if key not in theirs and is_map and line.active:
            diffs.append(Diff("entry", section, key, mine=line.value, default="mine",
                              comment=_comment(line),
                              note="Ya no aparece en la biblioteca; se conserva."))
    return diffs


def _list_diff(section, key, mine, theirs):
    """A long list (keep_together, taxonomy): offer mine / theirs / the union."""
    a, b = list(mine.value), list(theirs.value)
    sa, sb = set(a), set(b)
    return Diff("list", section, key, mine=a, theirs=b, default="mine",
                comment=_comment(theirs),
                note="%d entradas tuyas, %d propuestas." % (len(a), len(b)),
                extra={"only_mine": sorted(sa - sb), "only_theirs": sorted(sb - sa),
                       "shared": len(sa & sb), "union": sorted(sa | sb)})


def _comment(line):
    return (line.comment or "").lstrip("# ").rstrip()


def apply(live, prop, choices):
    """Apply {diff id: 'mine'|'theirs'|'union'|'skip'} to the live schema, in place."""
    applied = []
    for diff in compare(live, prop):
        pick = choices.get(diff.id, diff.default)
        if pick in ("mine", "skip"):
            continue
        if diff.kind == "section":
            if diff.theirs is None:
                continue
            live.append_lines(_clone(prop.section_lines(diff.section)))
            applied.append(diff.id)
        elif diff.kind == "list" and pick == "union":
            live.set(diff.section, diff.key, diff.extra["union"])
            applied.append(diff.id)
        else:
            source = prop.get(diff.section, diff.key)
            if source is None:
                continue
            target = live.get(diff.section, diff.key)
            if target is None:
                new = live.add(diff.section, diff.key, source.value)
                new.comment, new.gap = source.comment, source.gap or "   "
                if not source.active:
                    new.comment_out()
            else:
                target.set_value(source.value)
            applied.append(diff.id)
    return applied


def _clone(lines):
    import copy
    return [copy.copy(l) for l in lines]


def summary(diffs):
    counts = {}
    for d in diffs:
        counts[d.kind] = counts.get(d.kind, 0) + 1
    return {"total": len(diffs), "by_kind": counts,
            "adds": sum(1 for d in diffs if d.default == "theirs")}
