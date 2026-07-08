#!/usr/bin/env python3
# =============================================================================
# meta.py — read/write a skill's `.meta` file (key=value lines).
#
# The `.meta` file gives every managed skill provenance, lifecycle state,
# telemetry, and a quality score. This helper is the ONLY writer: it preserves
# unknown keys and a canonical key order, writes atomically, and NEVER clobbers
# an existing file on `init`.
#
# Usage:
#   meta.py get   <file> <key>            print value (empty if missing)
#   meta.py set   <file> <key> <value>    set/replace one key, keep the rest
#   meta.py bump  <file> <key>            integer increment (default 0)
#   meta.py init  <file> [k=v ...]        write defaults ONLY if file is absent
#   meta.py dump  <file>                  print all key=value in canonical order
#
# Format (canonical order):
#   provenance=managed     # managed (curated) | bundled (protected)
#   pinned=false
#   state=active           # active | stale | archived
#   created=YYYY-MM-DD
#   last_used=YYYY-MM-DD
#   last_patched=
#   use_count=0
#   quality=               # 1-5, set by the assessment/refine scorer
# =============================================================================
import sys
import os

CANON = ["provenance", "pinned", "state", "created",
         "last_used", "last_patched", "use_count", "quality"]
DEFAULTS = {
    "provenance": "managed", "pinned": "false", "state": "active",
    "created": "", "last_used": "", "last_patched": "",
    "use_count": "0", "quality": "",
}


def read(path):
    """Return (dict, order) where order is the file's original key order."""
    d, order = {}, []
    if os.path.isfile(path):
        with open(path, errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                stripped = line.lstrip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if not k:
                        continue
                    if k not in d:
                        order.append(k)
                    d[k] = v.strip()
    return d, order


def _ordered_keys(d, order):
    keys = [k for k in CANON if k in d]
    keys += [k for k in order if k not in CANON and k in d]
    for k in d:
        if k not in keys:
            keys.append(k)
    return keys


def write(path, d, order):
    keys = _ordered_keys(d, order)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for k in keys:
            f.write("%s=%s\n" % (k, d[k]))
    os.replace(tmp, path)


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(__doc__)
        return 2
    action, path = argv[1], argv[2]

    if action == "get":
        if len(argv) < 4:
            sys.stderr.write("get needs a key\n")
            return 2
        d, _ = read(path)
        sys.stdout.write(d.get(argv[3], ""))
        return 0

    if action == "set":
        if len(argv) < 5:
            sys.stderr.write("set needs <key> <value>\n")
            return 2
        key, val = argv[3], argv[4]
        if "\n" in val or "\r" in val:
            sys.stderr.write("meta value may not contain a newline\n")
            return 2
        val = val.strip()  # match read()'s strip so disk == what readers see
        d, order = read(path)
        if key not in d:
            order.append(key)
        d[key] = val
        write(path, d, order)
        return 0

    if action == "bump":
        if len(argv) < 4:
            sys.stderr.write("bump needs a key\n")
            return 2
        key = argv[3]
        d, order = read(path)
        try:
            n = int(d.get(key, "0") or "0")
        except ValueError:
            n = 0
        n += 1
        if key not in d:
            order.append(key)
        d[key] = str(n)
        write(path, d, order)
        return 0

    if action == "init":
        if os.path.isfile(path):
            return 0  # never clobber an existing .meta
        d, order = dict(DEFAULTS), list(CANON)
        for kv in argv[3:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                k, v = k.strip(), v.replace("\n", " ").replace("\r", " ").strip()
                if k not in d:
                    order.append(k)
                d[k] = v
        write(path, d, order)
        return 0

    if action == "dump":
        d, order = read(path)
        for k in _ordered_keys(d, order):
            sys.stdout.write("%s=%s\n" % (k, d[k]))
        return 0

    sys.stderr.write("unknown action: %s\n" % action)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
