#!/usr/bin/env python3
# =============================================================================
# memory.py — bounded, char-capped memory files (USER.md / MEMORY.md).
#
# Memory is two small Markdown files the system curates across sessions:
#   USER.md   — who the user is: preferences, communication style, habits.
#   MEMORY.md — agent notes: environment facts, conventions, tool quirks.
# Both are deliberately small (a frozen snapshot injected at session start) and
# enforced with a HARD CHARACTER CAP so they never bloat context. Entries are
# delimited by a leading "§"; multi-line entries are allowed.
#
# Usage:
#   memory.py init    <file> <cap> <title>     create with header if absent
#   memory.py read    <file>                   print the file
#   memory.py chars   <file>                   print current char count
#   memory.py add     <file> <cap> <text>      append an entry (reject if > cap)
#   memory.py replace <file> <cap> <substr> <text>   replace the unique match
#   memory.py remove  <file> <substr>          remove the unique matching entry
#   memory.py trim    <file> <cap>             drop oldest entries until <= cap
#
# add/replace exit 3 (not 2) when the result would exceed the cap, so callers
# can distinguish "too big" from "bad usage".
# =============================================================================
import sys
import os
import unicodedata

MARK = "§"  # § section sign


def _unsafe(text):
    """Memory enters the system prompt (CLAUDE.md @-import) and is sometimes
    written by the review loop from transcript content, so reject control /
    invisible / bidi-format characters — a classic injection/obfuscation vector
    with no legitimate place in a notes file. Returns an issue string or None.
    Normal text, accents, CJK, and emoji are all allowed."""
    for ch in text:
        if ch in "\n\t":
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Co", "Cn") or cat.startswith("Cs"):
            return "control/invisible character U+%04X (category %s)" % (ord(ch), cat)
    return None


def parse(path):
    """Return (header, [entries]). Each entry keeps its leading § marker."""
    if not os.path.isfile(path):
        return "", []
    text = open(path, errors="replace").read()
    idx = text.find(MARK)
    if idx == -1:
        return text, []
    header, rest = text[:idx], text[idx:]
    entries, cur = [], []
    for line in rest.splitlines(keepends=True):
        if line.startswith(MARK):
            if cur:
                entries.append("".join(cur).strip())
            cur = [line]
        else:
            cur.append(line)
    if cur:
        entries.append("".join(cur).strip())
    return header, [e for e in entries if e]


def render(header, entries):
    head = header.rstrip("\n")
    body = "\n".join(entries)
    if head and body:
        return head + "\n" + body + "\n"
    if head:
        return head + "\n"
    if body:
        return body + "\n"
    return ""


def entry_text(entry):
    """Strip the leading § and surrounding whitespace for matching."""
    return entry.lstrip(MARK).strip()


def find_matches(entries, substr):
    return [i for i, e in enumerate(entries) if substr in entry_text(e)]


def _atomic_write(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)


def _intarg(v, name):
    try:
        return int(v)
    except ValueError:
        sys.stderr.write("%s must be an integer (got '%s')\n" % (name, v))
        sys.exit(2)


def _mk_entry(text):
    """Build one logical entry. A continuation line that begins with the marker
    would be parsed as a *new* entry (splitting one entry into several and
    breaking replace/remove uniqueness), so indent any such line."""
    lines = text.strip().split("\n")
    out = [lines[0]] if lines else [""]
    for ln in lines[1:]:
        out.append(" " + ln if ln.startswith(MARK) else ln)
    return MARK + " " + "\n".join(out)


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(__doc__)
        return 2
    action, path = argv[1], argv[2]

    if action == "read":
        if os.path.isfile(path):
            sys.stdout.write(open(path, errors="replace").read())
        return 0

    if action == "chars":
        n = len(open(path, errors="replace").read()) if os.path.isfile(path) else 0
        sys.stdout.write(str(n))
        return 0

    if action == "init":
        if len(argv) < 5:
            sys.stderr.write("init needs <cap> <title>\n")
            return 2
        if os.path.isfile(path):
            return 0  # never clobber
        cap, title = argv[3], argv[4]
        with open(path, "w") as f:
            f.write("# %s\n" % title)
            # NOTE: keep the section mark OUT of the header text — a literal
            # delimiter here would be parsed as the start of the first entry.
            f.write("<!-- cairn memory — char cap %s chars; small on purpose; "
                    "one entry per section mark -->\n" % cap)
        return 0

    if action == "add":
        if len(argv) < 5:
            sys.stderr.write("add needs <cap> <text>\n")
            return 2
        cap, text = _intarg(argv[3], "cap"), argv[4].strip()
        u = _unsafe(text)
        if u:
            sys.stderr.write("REJECTED: %s in memory entry\n" % u)
            return 4
        header, entries = parse(path)
        if not header:
            header = "# Memory\n"
        entries.append(_mk_entry(text))
        out = render(header, entries)
        if len(out) > cap:
            sys.stderr.write(
                "REJECTED: adding this entry would make %s %d chars (cap %d). "
                "Trim or replace an existing entry first.\n"
                % (os.path.basename(path), len(out), cap))
            return 3
        _atomic_write(path, out)
        return 0

    if action == "replace":
        if len(argv) < 6:
            sys.stderr.write("replace needs <cap> <substr> <text>\n")
            return 2
        cap, substr, text = _intarg(argv[3], "cap"), argv[4], argv[5].strip()
        u = _unsafe(text)
        if u:
            sys.stderr.write("REJECTED: %s in memory entry\n" % u)
            return 4
        header, entries = parse(path)
        m = find_matches(entries, substr)
        if len(m) == 0:
            sys.stderr.write("no entry matches '%s'\n" % substr)
            return 2
        if len(m) > 1:
            sys.stderr.write("'%s' matches %d entries; be more specific\n" % (substr, len(m)))
            return 2
        entries[m[0]] = _mk_entry(text)
        out = render(header, entries)
        if len(out) > cap:
            sys.stderr.write("REJECTED: result would be %d chars (cap %d)\n" % (len(out), cap))
            return 3
        _atomic_write(path, out)
        return 0

    if action == "remove":
        if len(argv) < 4:
            sys.stderr.write("remove needs <substr>\n")
            return 2
        substr = argv[3]
        header, entries = parse(path)
        m = find_matches(entries, substr)
        if len(m) == 0:
            sys.stderr.write("no entry matches '%s'\n" % substr)
            return 2
        if len(m) > 1:
            sys.stderr.write("'%s' matches %d entries; be more specific\n" % (substr, len(m)))
            return 2
        del entries[m[0]]
        _atomic_write(path, render(header, entries))
        return 0

    if action == "trim":
        if len(argv) < 4:
            sys.stderr.write("trim needs <cap>\n")
            return 2
        cap = _intarg(argv[3], "cap")
        header, entries = parse(path)
        dropped = 0
        while entries and len(render(header, entries)) > cap:
            entries.pop(0)  # drop oldest first
            dropped += 1
        _atomic_write(path, render(header, entries))
        sys.stdout.write(str(dropped))
        return 0

    sys.stderr.write("unknown action: %s\n" % action)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
