#!/usr/bin/env python3
# =============================================================================
# lifecycle.py — skill lifecycle date math (active -> stale -> archived).
#
# A managed skill ages by inactivity: active -> stale (no activity for
# STALE days) -> archived (ARCHIVE days). Archiving only ever MOVES a skill;
# nothing is deleted. Pinned and bundled skills never auto-transition.
#
# All dates are ISO YYYY-MM-DD. "Activity" = the most recent of last_used /
# last_patched / created in a skill's .meta.
#
# Usage:
#   lifecycle.py days <date-a> <date-b>           whole days between (abs)
#   lifecycle.py state <today> <last_activity> <stale_days> <archive_days>
#                                                 -> active | stale | archived
#   lifecycle.py propose <skills_dir> <today> <stale_days> <archive_days>
#       Scan every skill's .meta and print, tab-separated, the ones whose
#       proposed state differs from current (skipping pinned / bundled):
#           <dir>\t<current_state>\t<proposed_state>\t<idle_days>
# =============================================================================
import sys
import os
import datetime


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.date(*[int(x) for x in s.split("-")[:3]])
    except (ValueError, TypeError):
        return None


def days_between(a, b):
    da, db = parse_date(a), parse_date(b)
    if da is None or db is None:
        return None
    return abs((da - db).days)


def state_for(today, last_activity, stale_days, archive_days):
    da, db = parse_date(today), parse_date(last_activity)
    if da is None or db is None:
        return "active", None  # no/invalid activity stamp -> leave active
    idle = (da - db).days
    if idle < 0:
        idle = 0  # activity dated in the future (clock skew / import) -> treat as active
    if idle >= archive_days:
        return "archived", idle
    if idle >= stale_days:
        return "stale", idle
    return "active", idle


def _read_meta(path):
    d = {}
    if os.path.isfile(path):
        for line in open(path, errors="replace"):
            line = line.rstrip("\n")
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    action = argv[1]

    if action == "days":
        d = days_between(argv[2], argv[3])
        if d is None:
            sys.stderr.write("bad date\n")
            return 2
        sys.stdout.write(str(d))
        return 0

    if action == "state":
        today, last, stale, arch = argv[2], argv[3], int(argv[4]), int(argv[5])
        st, _ = state_for(today, last, stale, arch)
        sys.stdout.write(st)
        return 0

    if action == "propose":
        skills_dir, today = argv[2], argv[3]
        stale, arch = int(argv[4]), int(argv[5])
        if not os.path.isdir(skills_dir):
            return 0
        for name in sorted(os.listdir(skills_dir)):
            d = os.path.join(skills_dir, name)
            if not os.path.isdir(d) or not os.path.isfile(os.path.join(d, "SKILL.md")):
                continue
            meta = _read_meta(os.path.join(d, ".meta"))
            if meta.get("provenance", "managed") == "bundled":
                continue
            if meta.get("pinned", "false") == "true":
                continue
            current = meta.get("state", "active")
            last = (meta.get("last_used") or meta.get("last_patched")
                    or meta.get("created") or "")
            proposed, idle = state_for(today, last, stale, arch)
            if proposed != current:
                sys.stdout.write("%s\t%s\t%s\t%s\n"
                                 % (name, current, proposed,
                                    "" if idle is None else idle))
        return 0

    sys.stderr.write("unknown action: %s\n" % action)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
