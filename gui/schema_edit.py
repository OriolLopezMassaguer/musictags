"""Line-level editor for schema.toml that keeps comments, order and spacing.

analyze_tags.py emits the schema as a flat list of literal lines, and those comments
carry real information: track counts (``# 15 tracks``), the values an option accepts
(``# "keep" | "drop" | "style"``) and the commented-out "NOT mapped: decide" entries.
A parse/re-dump cycle must therefore be byte-identical, and an edit must touch only
the lines it changes.

So this is not an AST: every line keeps its raw text and is re-rendered only once it
is modified.
"""

import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import dumps_toml_str  # noqa: E402

BARE_KEY = re.compile(r"[A-Za-z0-9_-]+\Z")
INT_RE = re.compile(r"[+-]?\d+\Z")
FLOAT_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?\Z")
SECTION_RE = re.compile(r"\[([^\]]+)\]\s*\Z")
# "keep" | "drop" | "style"  inside a trailing comment -> a dropdown in the UI
ENUM_RE = re.compile(r'"([^"]+)"(?:\s*\|\s*"([^"]+)")+')


# --------------------------------------------------------------------------- scanning


def _scan(text, stop):
    """Index of the first character of `stop` outside a string, or -1."""
    quote = esc = None
    depth = 0
    for i, c in enumerate(text):
        if quote:
            if esc:
                esc = False
            elif c == "\\" and quote == '"':
                esc = True
            elif c == quote:
                quote = None
        elif c in "\"'":
            quote = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif c in stop and depth == 0:
            return i
    return -1


def split_comment(text):
    """'value   # note' -> ('value', '   ', '# note'), ignoring '#' inside strings."""
    i = _scan(text, "#")
    body = text if i < 0 else text[:i]
    comment = "" if i < 0 else text[i:]
    value = body.rstrip()
    return value, body[len(value):], comment


def parse_key(text):
    """A TOML key as written -> its value, or None when it is not a key at all."""
    t = text.strip()
    if not t:
        return None
    if t[0] == '"' and t[-1] == '"' and len(t) > 1:
        try:
            return json.loads(t)
        except ValueError:
            return None
    if t[0] == "'" and t[-1] == "'" and len(t) > 1:
        return t[1:-1]
    return t if BARE_KEY.match(t) else None


def split_items(inner):
    """Split the inside of an array on top-level commas."""
    items, start, i = [], 0, 0
    while start <= len(inner):
        rest = inner[start:]
        i = _scan(rest, ",")
        if i < 0:
            if rest.strip():
                items.append(rest)
            break
        items.append(rest[:i])
        start += i + 1
    return items


def parse_value(text):
    """TOML scalar/array as written -> a Python value. Raises ValueError otherwise."""
    t = text.strip()
    if t == "true":
        return True
    if t == "false":
        return False
    if INT_RE.match(t):
        return int(t)
    if FLOAT_RE.match(t):
        return float(t)
    if t.startswith('"'):
        return json.loads(t)
    if t.startswith("'") and t.endswith("'") and len(t) > 1:
        return t[1:-1]
    if t.startswith("[") and t.endswith("]"):
        return [parse_value(x) for x in split_items(t[1:-1])]
    raise ValueError("not a TOML value: %r" % text)


def render_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return dumps_toml_str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(render_value(v) for v in value) + "]"
    raise TypeError("cannot write %r to TOML" % type(value))


def value_type(value, comment=""):
    """The control the UI should show for this value."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str) and enum_options(comment):
        return "enum"
    return "str"


def enum_options(comment):
    """The '"a" | "b" | "c"' alternatives documented in a trailing comment."""
    m = ENUM_RE.search(comment or "")
    return re.findall(r'"([^"]+)"', m.group(0)) if m else []


# --------------------------------------------------------------------------- lines


class Line:
    """One source line (or, for a multi-line array, one block of them)."""

    def __init__(self, kind, raw, **kw):
        self.kind = kind          # blank | comment | section | pair | array
        self.raw = raw            # verbatim source, re-emitted while not dirty
        self.dirty = False
        self.section = kw.get("section", "")
        self.key = kw.get("key")
        self.value = kw.get("value")
        self.gap = kw.get("gap", "")
        self.comment = kw.get("comment", "")
        self.active = kw.get("active", True)   # False = commented-out pair
        self.prefix = kw.get("prefix", "")     # the '# ' of a commented-out pair
        self.indent = kw.get("indent", "    ")
        self.quoted = kw.get("quoted", False)  # '"Hard Rock" = ...' vs 'max_genres = ...'
        self.lead = kw.get("lead", "")         # comment lines above an array's items

    # -- editing
    def set_value(self, value):
        if value != self.value or not self.active:
            self.value = value
            self.active = True
            self.dirty = True

    def comment_out(self):
        if self.active:
            self.active = False
            self.dirty = True

    def render(self):
        if not self.dirty:
            return self.raw
        if self.kind == "array":
            head = "%s%s = [" % (self.prefix if not self.active else "", self.key_text())
            body = ["%s%s," % (self.indent, render_value(v)) for v in self.value]
            return "\n".join([head + self.gap + self.comment] + self.lead + body + ["]"])
        prefix = "" if self.active else (self.prefix or "# ")
        line = "%s%s = %s" % (prefix, self.key_text(), render_value(self.value))
        return line + self.gap + self.comment

    def key_text(self):
        if self.quoted or not BARE_KEY.match(self.key or ""):
            return dumps_toml_str(self.key)
        return self.key

    def as_dict(self):
        return {
            "key": self.key,
            "value": self.value,
            "comment": self.comment.lstrip("# ").rstrip(),
            "type": value_type(self.value, self.comment),
            "options": enum_options(self.comment),
            "active": self.active,
        }


def _parse_pair(body, section):
    """'key = value' -> a pair Line, or None."""
    i = _scan(body, "=")
    if i < 0:
        return None
    key = parse_key(body[:i])
    if key is None:
        return None
    vtext, gap, comment = split_comment(body[i + 1:])
    try:
        value = parse_value(vtext)
    except (ValueError, json.JSONDecodeError):
        return None
    return Line("pair", body, section=section, key=key, value=value, gap=gap,
                comment=comment, quoted=body.lstrip().startswith('"'))


class SchemaFile:
    """A schema.toml parsed into lines, editable without losing the comments."""

    def __init__(self, lines, trailing_newline=True, path=None):
        self.lines = lines
        self.trailing_newline = trailing_newline
        self.path = path

    # -- loading -----------------------------------------------------------
    @classmethod
    def loads(cls, text, path=None):
        raw_lines = text.split("\n")
        trailing = bool(raw_lines) and raw_lines[-1] == ""
        if trailing:
            raw_lines.pop()
        out, section, i = [], "", 0
        while i < len(raw_lines):
            raw = raw_lines[i]
            stripped = raw.strip()
            if not stripped:
                out.append(Line("blank", raw, section=section))
            elif SECTION_RE.match(stripped):
                section = SECTION_RE.match(stripped).group(1)
                out.append(Line("section", raw, section=section, key=section))
            elif stripped.startswith("#"):
                node, used = cls._comment_node(raw_lines, i, section)
                out.append(node)
                i += used - 1
            else:
                node, used = cls._value_node(raw_lines, i, section)
                out.append(node)
                i += used - 1
            i += 1
        return cls(out, trailing, path)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as fh:
            return cls.loads(fh.read(), path)

    @staticmethod
    def _comment_node(raw_lines, i, section):
        """A comment, unless it is a commented-out pair with a quoted key."""
        raw = raw_lines[i]
        body = raw.lstrip()
        prefix = raw[:len(raw) - len(body)] + "# "
        inner = body[1:].lstrip()
        # Only quoted keys: '# raw genre (...) = [GENRE, ...]' is prose, not a pair.
        if inner.startswith('"'):
            pair = _parse_pair(inner, section)
            if pair is not None:
                pair.raw, pair.active, pair.prefix = raw, False, prefix
                return pair, 1
        return Line("comment", raw, section=section), 1

    @staticmethod
    def _value_node(raw_lines, i, section):
        raw = raw_lines[i]
        eq = _scan(raw, "=")
        head = split_comment(raw[eq + 1:])[0].strip() if eq >= 0 else ""
        if eq >= 0 and head.startswith("[") and not head.endswith("]"):
            return SchemaFile._array_node(raw_lines, i, section)
        pair = _parse_pair(raw, section)
        return (pair, 1) if pair else (Line("comment", raw, section=section), 1)

    @staticmethod
    def _array_node(raw_lines, i, section):
        """key = [ \\n  "a", \\n ]  -> one array Line covering every source line."""
        raw = raw_lines[i]
        eq = _scan(raw, "=")
        key = parse_key(raw[:eq])
        _, gap, comment = split_comment(raw[eq + 1:])
        items, lead, indent, used = [], [], "    ", 1
        j = i + 1
        while j < len(raw_lines):
            line = raw_lines[j]
            used += 1
            if line.strip() == "]":
                break
            if line.strip().startswith("#"):
                lead.append(line)
            else:
                body = line.strip().rstrip(",")
                indent = line[:len(line) - len(line.lstrip())] or indent
                try:
                    items.append(parse_value(body))
                except (ValueError, json.JSONDecodeError):
                    lead.append(line)
            j += 1
        node = Line("array", "\n".join(raw_lines[i:i + used]), section=section, key=key,
                    value=items, gap=gap, comment=comment, indent=indent, lead=lead,
                    quoted=raw.lstrip().startswith('"'))
        return node, used

    # -- reading -----------------------------------------------------------
    def dumps(self):
        text = "\n".join(line.render() for line in self.lines)
        return text + "\n" if self.trailing_newline else text

    def sections(self):
        seen = []
        for line in self.lines:
            if line.kind == "section" and line.key not in seen:
                seen.append(line.key)
        return seen

    def pairs(self, section):
        return [l for l in self.lines
                if l.section == section and l.kind in ("pair", "array")]

    def get(self, section, key):
        for line in self.pairs(section):
            if line.key == key:
                return line
        return None

    def to_dict(self, active_only=True):
        """{section: {key: value}} — what core.load_config() would see."""
        out = {s: {} for s in self.sections()}   # a section whose entries are all
        for line in self.lines:                     # commented out is still a section
            if line.kind in ("pair", "array") and (line.active or not active_only):
                out.setdefault(line.section, {})[line.key] = line.value
        return out

    # -- writing -----------------------------------------------------------
    def set(self, section, key, value):
        line = self.get(section, key)
        if line is None:
            return self.add(section, key, value)
        line.set_value(value)
        return line

    def add(self, section, key, value, comment=""):
        """Append a key at the end of its section, creating the section if needed."""
        existing = self.pairs(section)
        quoted = (existing[0].quoted if existing else not BARE_KEY.match(key))
        line = Line("array" if isinstance(value, list) and len(value) > 8 else "pair",
                    "", section=section, key=key, value=value, quoted=quoted,
                    gap="   " if comment else "", comment=comment)
        line.dirty = True
        at = self._end_of(section)
        if at is None:
            if self.lines and self.lines[-1].kind != "blank":
                self.lines.append(Line("blank", ""))
            head = Line("section", "[%s]" % section, section=section, key=section)
            self.lines.append(head)
            at = len(self.lines)
        self.lines.insert(at, line)
        return line

    def remove(self, section, key):
        line = self.get(section, key)
        if line is not None:
            self.lines.remove(line)
        return line is not None

    def section_lines(self, section):
        """Every source line belonging to a section, header included."""
        out, inside = [], False
        for line in self.lines:
            if line.kind == "section":
                inside = line.key == section
            if inside:
                out.append(line)
        while out and out[-1].kind == "blank":
            out.pop()
        return out

    def append_lines(self, lines):
        """Append already-parsed lines verbatim (used when copying a whole section)."""
        if self.lines and self.lines[-1].kind != "blank":
            self.lines.append(Line("blank", ""))
        self.lines.extend(lines)

    def add_section(self, section, lines):
        """Append a whole section verbatim (used by the merge page)."""
        if self.lines and self.lines[-1].kind != "blank":
            self.lines.append(Line("blank", ""))
        for raw in lines:
            stripped = raw.strip()
            if SECTION_RE.match(stripped):
                self.lines.append(Line("section", raw, section=section, key=section))
            elif not stripped:
                self.lines.append(Line("blank", raw, section=section))
            else:
                node, _ = (self._comment_node([raw], 0, section) if stripped.startswith("#")
                           else self._value_node([raw], 0, section))
                self.lines.append(node)

    def _end_of(self, section):
        """Index just after the last non-blank line of a section."""
        last = None
        for i, line in enumerate(self.lines):
            if line.section == section and line.kind != "blank":
                last = i
        return None if last is None else last + 1

    def save(self, path=None, backup=True, validate=True):
        """Write the file, keeping a .bak and rolling back if it no longer parses."""
        path = path or self.path
        text = self.dumps()
        if validate:
            import tomli
            tomli.loads(text)                     # raises before anything is written
        if backup and os.path.exists(path):
            shutil.copy2(path, path + ".bak")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
        return path
