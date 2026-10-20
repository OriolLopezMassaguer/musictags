"""
rules.py - credit splitting and name canonicalisation shared by analyze & propose.
"""
from __future__ import annotations

import re

from core import name_key

DEFAULT_SPLIT = [" & ", ", ", "; ", ";", " / ", " + "]
DEFAULT_FEAT = [r"\s*[\(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+", r"\s+(?:feat\.?|ft\.?|featuring)\s+"]
DEFAULT_KEEP = ["AC/DC", "Earth, Wind & Fire", "Simon & Garfunkel", "Crosby, Stills, Nash & Young",
                "Hall & Oates", "Florence + the Machine", "Mumford & Sons", "Sly & the Family Stone",
                "Echo & the Bunnymen", "Siouxsie and the Banshees", "Tyler, the Creator",
                "Peter, Paul and Mary", "Emerson, Lake & Palmer", "Blood, Sweat & Tears",
                "Ike & Tina Turner", "Belle & Sebastian", "Sam & Dave", "Kool & the Gang",
                "Booker T. & the M.G.'s", "Derek & the Dominos", "Iron & Wine", "Above & Beyond",
                "Marina and the Diamonds", "Nick Cave & the Bad Seeds", "Bob Marley & the Wailers",
                "Tom Petty and the Heartbreakers", "Huey Lewis & the News", "Joan Jett & the Blackhearts"]


class CreditSplitter:
    """Split 'A & B feat. C' into main=['A','B'], feat=['C'], honouring names that must
    stay together (bands like 'Simon & Garfunkel')."""

    def __init__(self, split_seps=None, feat_patterns=None, keep_together=None, known=None):
        self.known = known or (lambda s: False)   # e.g. 'Satie, Erik' is one known name
        self.split_seps = split_seps if split_seps is not None else DEFAULT_SPLIT
        pats = feat_patterns if feat_patterns is not None else DEFAULT_FEAT
        self.feat_re = re.compile("|".join(f"(?:{p})" for p in pats), re.I)
        seps = sorted(self.split_seps, key=len, reverse=True)
        self.split_re = re.compile("|".join(re.escape(s) for s in seps)) if seps else None
        self.keep = sorted(set(keep_together or []), key=len, reverse=True)
        self.keep_keys = {name_key(k) for k in self.keep}
        self.keep_res = [re.compile(re.escape(k), re.I) for k in self.keep]

    def _protect(self, s):
        saved = []
        for rx in self.keep_res:
            def sub(m):
                saved.append(m.group(0))
                return f"\x00{len(saved) - 1}\x00"
            s = rx.sub(sub, s)
        return s, saved

    @staticmethod
    def _restore(s, saved):
        return re.sub(r"\x00(\d+)\x00", lambda m: saved[int(m.group(1))], s)

    def split_list(self, s: str) -> list[str]:
        if not s or name_key(s) in self.keep_keys or not self.split_re or self.known(s):
            return [s.strip()] if s and s.strip() else []
        p, saved = self._protect(s)
        parts = [self._restore(x, saved).strip(" ,;") for x in self.split_re.split(p)]
        parts = [re.sub(r"^(?:and|y|i|et|und)\s+", "", x, flags=re.I) for x in parts]
        return [x for x in parts if x]

    def split(self, s: str) -> tuple[list[str], list[str]]:
        if not s:
            return [], []
        p, saved = self._protect(s)
        m = self.feat_re.search(p)
        if m:
            main_s, feat_s = p[:m.start()], p[m.end():]
            feat_s = re.sub(r"[\)\]]\s*$", "", feat_s)
        else:
            main_s, feat_s = p, ""
        main = self.split_list(self._restore(main_s, saved))
        feat = self.split_list(self._restore(feat_s, saved)) if feat_s else []
        return main, feat

    def title_feat(self, title: str) -> list[str]:
        """'Song (feat. X & Y)' -> ['X', 'Y']"""
        m = re.search(r"[\(\[]\s*(?:feat\.?|ft\.?|featuring)\s+([^\)\]]+)[\)\]]", title or "", re.I)
        return self.split_list(m.group(1)) if m else []


class Canon:
    """Maps any spelling of a name to its canonical form via an alias table keyed on name_key()."""

    def __init__(self, aliases: dict[str, str] | None = None, *more: dict[str, str]):
        self.map: dict[str, str] = {}
        for table in (aliases or {}), *more:
            for variant, canonical in table.items():
                self.map.setdefault(name_key(variant), canonical)
                self.map.setdefault(name_key(canonical), canonical)

    def __call__(self, name: str) -> str:
        return self.map.get(name_key(name), name.strip())

    def known(self, name: str) -> bool:
        return name_key(name) in self.map


def dedupe(seq):
    seen, out = set(), []
    for x in seq:
        k = name_key(x)
        if x and k not in seen:
            seen.add(k)
            out.append(x)
    return out
