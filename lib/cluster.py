#!/usr/bin/env python3
# =============================================================================
# cluster.py — mechanical (no-AI) similarity clustering by trigger overlap.
#
# Shared by the backfill distiller (cluster mined candidates) and the curator
# (cluster existing skills to find umbrella opportunities). Tokenizes name +
# description, drops stopwords, and groups by Jaccard overlap with union-find.
# No model calls — this is the free pre-pass that decides what the AI looks at.
#
# Usage:
#   cluster.py candidates <in.jsonl> <threshold> <outdir>
#       Cluster mined candidates. Writes <outdir>/cluster_NNNN.json (members,
#       largest cluster first) and prints a one-line summary.
#   cluster.py skills <skills_dir> <threshold>
#       Cluster installed skills by SKILL.md frontmatter overlap. Prints one
#       line per multi-skill cluster: tab-separated skill dir names.
# =============================================================================
import sys
import os
import re
import json
import glob
import itertools

STOP = set("""a an the of to and or for with use used using when this that those
these on in into your you user users claude skill skills it its as be by from at
if then else do does done can will would should task tasks help via run runs new
also etc safely across""".split())


def toks(s):
    return set(t for t in re.split(r'[^a-z0-9]+', s.lower())
               if len(t) > 2 and t not in STOP)


def jac(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def union_find(items_toks, threshold):
    """items_toks: list of token-sets. Returns list of clusters (index lists),
    largest first."""
    n = len(items_toks)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in itertools.combinations(range(n), 2):
        if jac(items_toks[i], items_toks[j]) >= threshold:
            parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=len, reverse=True)


def frontmatter(path):
    name, desc = "", ""
    try:
        t = open(path, errors="replace").read()
        m = re.search(r'^---\s*\n(.*?)\n---', t, re.S)
        fm = m.group(1) if m else ""
        nm = re.search(r'^name:[ \t]*(.+)$', fm, re.M)
        name = nm.group(1).strip() if nm else ""
        dm = re.search(r'^description:[ \t]*(.+)$', fm, re.M)
        if dm:
            desc = dm.group(1).strip()
    except (OSError, UnicodeError):
        pass
    return name, desc


def cmd_candidates(in_path, threshold, outdir):
    cands = []
    with open(in_path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict):
                continue
            name = str(o.get("name", "")).strip()
            desc = str(o.get("description", "")).strip()
            if not (name or desc):
                continue
            o["_t"] = toks(name + " " + desc)
            cands.append(o)
    clusters = union_find([c["_t"] for c in cands], threshold)
    # only clear files we own (cluster_NNNN.json) — never an unrelated file
    for f in glob.glob(os.path.join(outdir, "cluster_*.json")):
        if re.match(r'^cluster_\d{4}\.json$', os.path.basename(f)):
            os.remove(f)
    sizes = []
    for idx, g in enumerate(clusters):
        members = []
        for i in g:
            c = dict(cands[i])
            c.pop("_t", None)
            members.append(c)
        with open(os.path.join(outdir, "cluster_%04d.json" % idx), "w") as out:
            json.dump(members, out, ensure_ascii=False)
        sizes.append(len(g))
    multi = [s for s in sizes if s >= 2]
    sys.stdout.write(
        "candidates=%d clusters=%d multi=%d covered=%d singletons=%d\n"
        % (len(cands), len(clusters), len(multi), sum(multi),
           len([s for s in sizes if s == 1])))
    return 0


def cmd_skills(skills_dir, threshold):
    skills = []
    for d in sorted(glob.glob(os.path.join(skills_dir, "*"))):
        sp = os.path.join(d, "SKILL.md")
        if not os.path.isfile(sp):
            continue
        dirn = os.path.basename(d)
        if dirn == "skill-extraction":
            continue
        name, desc = frontmatter(sp)
        skills.append((dirn, toks((name or dirn) + " " + desc)))
    clusters = union_find([t for _, t in skills], threshold)
    for g in clusters:
        if len(g) > 1:
            sys.stdout.write("\t".join(skills[i][0] for i in g) + "\n")
    return 0


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    action = argv[1]
    if action == "candidates":
        return cmd_candidates(argv[2], float(argv[3]), argv[4])
    if action == "skills":
        return cmd_skills(argv[2], float(argv[3]))
    sys.stderr.write("unknown action: %s\n" % action)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
