"""Load, group, filter and save changes.csv.

70k rows over 11k files is too much to hand to a browser, and the interesting unit
is the album, not the row: 87% of this library is classical, so most of the work is
eyeballing one proposed album name at a time. Rows are therefore grouped with the
proposer's own album_key(), filtered server-side, and paged.

Only the `approve` and `new` columns are ever rewritten, so ./4_apply.sh keeps
working on the same file.
"""

import csv
import json
import os
import shutil
import sqlite3
import sys
import threading

from core import LIST_SEP
from propose_changes import album_key

from gui.runner import ROOT

CHANGES = "changes.csv"
DB = "tags.sqlite"
COLUMNS = ["id", "approve", "confidence", "rule", "path", "field", "old", "new"]
# apply_changes.py:23 -- what it counts as approved.
YES = {"y", "yes", "x", "1", "true", "si", "sí"}
CONFIDENCES = ["high", "medium", "low"]

# Fields shown first inside an album, because they are the ones worth reading.
FIELD_ORDER = ["album", "albumartist", "albumartistsort", "artist", "artists",
               "artistsort", "composer", "composersort", "conductor", "ensemble",
               "genre", "style", "work", "movementname", "movement", "compilation"]

_LOCK = threading.Lock()
_CACHE = {}

ID, APPROVE, CONF, RULE, PATH, FIELD, OLD, NEW = range(8)


# rule family of the classical GENRE path (propose_changes.Proposer.classical_genres)
TREE_RULE = "genre-tree"


def _genre_text(raw):
    """'Clásica\\Orquestal\\Sinfonias || Folk' -> 'Clásica\\Orquestal\\Sinfonias, Folk'."""
    return raw.replace(LIST_SEP, ", ") if raw else raw


def approved(value):
    return value.strip().lower() in YES


def rule_group(rule):
    """'album: classical name (…)' -> 'album'. The prefix is the proposer's rule family."""
    return rule.split(":", 1)[0].strip() if ":" in rule else rule.strip()


class Album:
    def __init__(self, key, folder, name):
        self.key = key
        self.folder = folder
        self.name = name
        self.rows = []
        self.files = set()

    @property
    def display(self):
        return self.name or os.path.basename(self.folder)

    def summary(self, rows):
        conf = {c: 0 for c in CONFIDENCES}
        fields, approved_n, new_album, new_artist = {}, 0, None, None
        new_genre = old_genre = None
        for i in self.rows:
            row = rows[i]
            conf[row[CONF]] = conf.get(row[CONF], 0) + 1
            fields[row[FIELD]] = fields.get(row[FIELD], 0) + 1
            approved_n += approved(row[APPROVE])
            if row[FIELD] == "album" and new_album is None:
                new_album = row[NEW]
            elif row[FIELD] == "albumartist" and new_artist is None:
                new_artist = row[NEW]
            elif row[FIELD] == "genre" and new_genre is None and rule_group(row[RULE]) == TREE_RULE:
                new_genre, old_genre = row[NEW], row[OLD]
        return {"key": "%s\u0000%s" % self.key, "display": self.display,
                "folder": self.folder, "rel": os.path.basename(self.folder),
                "tracks": len(self.files), "changes": len(self.rows),
                "approved": approved_n, "confidence": conf,
                "fields": sorted(fields.items(), key=lambda kv: -kv[1]),
                "new_album": new_album, "new_albumartist": new_artist,
                "new_genre": _genre_text(new_genre), "old_genre": _genre_text(old_genre)}


class ChangeSet:
    """changes.csv in memory, with the indexes the filters need."""

    def __init__(self, path, rows, stamp):
        self.path = path
        self.rows = rows
        self.stamp = stamp
        self.dirty = False
        self.albums = {}
        self.order = []
        self._group()
        self.facets = self._facets()

    # -- building ----------------------------------------------------------
    def _group(self):
        # Resolve one ALBUM title per file *first*. Doing it per row would put the
        # rows of the same file in different groups whenever the cache has no title
        # for it, because only the `album` rows carry the old name.
        titles = dict(album_titles())
        for row in self.rows:
            if row[FIELD] == "album" and not titles.get(row[PATH]):
                titles[row[PATH]] = row[OLD]

        for i, row in enumerate(self.rows):
            path = row[PATH]
            key = album_key(path, {"album": [titles.get(path, "")]})
            album = self.albums.get(key)
            if album is None:
                album = self.albums[key] = Album(key, key[0], key[1])
                self.order.append(key)
            album.rows.append(i)
            album.files.add(path)

    def _facets(self):
        out = {"field": {}, "confidence": {}, "rule": {}}
        for row in self.rows:
            out["field"][row[FIELD]] = out["field"].get(row[FIELD], 0) + 1
            out["confidence"][row[CONF]] = out["confidence"].get(row[CONF], 0) + 1
            g = rule_group(row[RULE])
            out["rule"][g] = out["rule"].get(g, 0) + 1
        return {k: dict(sorted(v.items(), key=lambda kv: -kv[1])) for k, v in out.items()}

    # -- reading -----------------------------------------------------------
    def match(self, row, field="", confidence="", rule="", q="", pending=False):
        if field and row[FIELD] != field:
            return False
        if confidence and row[CONF] != confidence:
            return False
        if rule and rule_group(row[RULE]) != rule:
            return False
        if pending and approved(row[APPROVE]):
            return False
        if q:
            needle = q.casefold()
            if not any(needle in row[c].casefold()
                       for c in (PATH, OLD, NEW, RULE)):
                return False
        return True

    def filter_rows(self, **f):
        return [i for i, row in enumerate(self.rows) if self.match(row, **f)]

    def album_list(self, **f):
        """Albums that still have a matching row, with their matching rows only."""
        out = []
        for key in self.order:
            album = self.albums[key]
            keep = [i for i in album.rows if self.match(self.rows[i], **f)]
            if not keep:
                continue
            summary = album.summary(self.rows)
            summary["matching"] = len(keep)
            summary["row_ids"] = keep
            out.append(summary)
        return out

    def album_rows(self, key, **f):
        album = self.albums.get(tuple(key.split("\u0000", 1)))
        if album is None:
            return []
        rows = [i for i in album.rows if self.match(self.rows[i], **f)]
        rank = {name: n for n, name in enumerate(FIELD_ORDER)}
        rows.sort(key=lambda i: (self.rows[i][PATH],
                                 rank.get(self.rows[i][FIELD], 99)))
        return rows

    def row_dict(self, i):
        row = self.rows[i]
        return {"i": i, "id": row[ID], "approved": approved(row[APPROVE]),
                "confidence": row[CONF], "rule": row[RULE],
                "rule_group": rule_group(row[RULE]),
                "path": row[PATH], "file": os.path.basename(row[PATH]),
                "field": row[FIELD],
                "old": row[OLD].split(LIST_SEP) if row[OLD] else [],
                "new": row[NEW].split(LIST_SEP) if row[NEW] else [],
                "old_raw": row[OLD], "new_raw": row[NEW]}

    def counts(self, **f):
        rows = self.filter_rows(**f)
        return {"matching": len(rows),
                "approved": sum(1 for i in rows if approved(self.rows[i][APPROVE])),
                "total": len(self.rows)}

    # -- writing -----------------------------------------------------------
    def set_approved(self, indexes, value):
        token = "y" if value else ""
        n = 0
        for i in indexes:
            if self.rows[i][APPROVE] != token:
                self.rows[i][APPROVE] = token
                n += 1
        self.dirty = self.dirty or bool(n)
        return n

    def set_new(self, i, value):
        if self.rows[i][NEW] != value:
            self.rows[i][NEW] = value
            self.dirty = True
            return True
        return False

    def save(self, backup=True):
        if backup and os.path.exists(self.path):
            shutil.copy2(self.path, self.path + ".bak")
        tmp = self.path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow(COLUMNS)
            writer.writerows(self.rows)
        os.replace(tmp, self.path)
        self.dirty = False
        self.stamp = os.stat(self.path).st_mtime
        return self.path


def album_titles(db_name=DB):
    """path -> ALBUM tag, so grouping matches the proposer's own album_key()."""
    path = os.path.join(ROOT, db_name)
    stamp = os.stat(path).st_mtime if os.path.exists(path) else None
    if stamp is None:
        return {}
    cached = _CACHE.get("titles")
    if cached and cached[0] == stamp:
        return cached[1]
    db = sqlite3.connect(path)
    out = {}
    for p, raw in db.execute("SELECT path, tags FROM files"):
        tags = json.loads(raw) if raw else {}
        out[sys.intern(p)] = (tags.get("album") or [""])[0]
    db.close()
    _CACHE["titles"] = (stamp, out)
    return out


def load(name=CHANGES, force=False):
    """The parsed changes.csv, reloaded only when the file on disk changed."""
    path = name if os.path.isabs(name) else os.path.join(ROOT, name)
    if not os.path.exists(path):
        return None
    stamp = os.stat(path).st_mtime
    with _LOCK:
        current = _CACHE.get("changes")
        if current is not None and current.stamp == stamp and not force:
            return current
        rows = []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            header = next(reader, None)
            if header != COLUMNS:
                raise ValueError("changes.csv tiene columnas inesperadas: %s" % header)
            for row in reader:
                if len(row) != 8:
                    continue
                row[RULE] = sys.intern(row[RULE])
                row[PATH] = sys.intern(row[PATH])
                row[FIELD] = sys.intern(row[FIELD])
                row[CONF] = sys.intern(row[CONF])
                rows.append(row)
        changeset = ChangeSet(path, rows, stamp)
        _CACHE["changes"] = changeset
        return changeset


def invalidate():
    _CACHE.pop("changes", None)
