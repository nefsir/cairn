#!/usr/bin/env python3
# =============================================================================
# validate.py — check a skill's SKILL.md against the house frontmatter contract.
#
# A skill must: open and close with `---`, carry a non-empty `name` (<=64 chars)
# and `description` (<=1024 chars — the cap that keeps the activation index lean),
# and have a non-empty body. This is the deterministic guard behind the prompt
# discipline: `cairn lint` runs it; the test suite asserts it.
#
# Usage:
#   validate.py skill <skill-dir>     print one issue per line; exit 1 if invalid
#   validate.py all   <skills-dir>    print "<dir>: <issue>"; exit 1 if any invalid
# =============================================================================
import sys
import os
import re
import glob

MAX_NAME = 64
MAX_DESC = 1024


def _field(fm, key):
    """Value of a top-level `key:` in the frontmatter text. Stays on the SAME
    line as the key (so an empty `key:` does NOT bleed into the next line), and
    folds in indented YAML continuation / block-scalar lines (so the full
    multi-line value is measured, not just its first line). None if empty/absent."""
    lines = fm.split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r'^' + re.escape(key) + r':[^\S\r\n]*(.*)$', ln)
        if not m:
            continue
        parts = [m.group(1).strip()]
        for nxt in lines[i + 1:]:
            if re.match(r'^\s+\S', nxt):      # indented -> continuation / block body
                parts.append(nxt.strip())
            else:
                break                          # dedent, next key, or blank line
        val = " ".join(p for p in parts if p)
        val = re.sub(r'^[>|][-+0-9]*\s*', '', val).strip()  # drop a YAML block indicator
        return val or None
    return None


def check(skill_md):
    if not os.path.isfile(skill_md):
        return ["SKILL.md missing"]
    text = open(skill_md, errors="replace").read()
    m = re.match(r'^---[ \t]*\n(.*?)\n---[ \t]*\n?(.*)$', text, re.S)
    if not m:
        return ["no valid frontmatter (must open and close with ---)"]
    fm, body = m.group(1), m.group(2)
    issues = []
    name, desc = _field(fm, "name"), _field(fm, "description")
    if not name:
        issues.append("missing 'name'")
    elif len(name) > MAX_NAME:
        issues.append("name exceeds %d chars (%d)" % (MAX_NAME, len(name)))
    if not desc:
        issues.append("missing 'description'")
    elif len(desc) > MAX_DESC:
        issues.append("description exceeds %d chars (%d)" % (MAX_DESC, len(desc)))
    if not body.strip():
        issues.append("empty body")
    return issues


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(__doc__)
        return 2
    action = argv[1]
    if action == "skill":
        issues = check(os.path.join(argv[2], "SKILL.md"))
        for i in issues:
            sys.stdout.write(i + "\n")
        return 1 if issues else 0
    if action == "all":
        bad = 0
        for d in sorted(glob.glob(os.path.join(argv[2], "*"))):
            sp = os.path.join(d, "SKILL.md")
            if not os.path.isfile(sp):
                continue
            for i in check(sp):
                bad += 1
                sys.stdout.write("%s: %s\n" % (os.path.basename(d), i))
        return 1 if bad else 0
    sys.stderr.write("unknown action: %s\n" % action)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
