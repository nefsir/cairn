#!/usr/bin/env python3
"""diff-cairn — differential golden-master harness.

Treats one cairn build (oracle) and another (candidate) as black boxes and proves
BYTE-equivalence of every observable: per-step exit code + stdout + stderr, the full
$CLAUDE_DIR file tree (incl. every .meta raw-byte and settings.json), the skills git
log/status, and the deterministic shim logs. Non-determinism (paths, timestamps,
backup suffixes) is normalized out with STRICT patterns so a format regression still
diffs.

Self-check: run with oracle == candidate == bin/cairn; MUST be all-green, else the
normalization is wrong and the harness cannot be trusted to judge the port.

Usage:
  diff-cairn.py [--oracle PATH] [--candidate PATH] [--scenario NAME ...]
  (defaults: oracle=candidate=<repo>/bin/cairn, all scenarios in scenarios/)
"""
import os, sys, re, subprocess, importlib.util, argparse, tempfile, shutil
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
SHIMS = HARNESS / "shims"
SCEN_DIR = HARNESS / "scenarios"
REPO = HARNESS.parent.parent

FIXED_GIT = {
    "GIT_AUTHOR_DATE": "2020-01-01T00:00:00 +0000",
    "GIT_COMMITTER_DATE": "2020-01-01T00:00:00 +0000",
}


class Ctx:
    """Drives one cairn build in an isolated $HOME and records every step."""
    def __init__(self, cairn, home):
        self.cairn = str(cairn)
        self.home = Path(home)
        self.claude_dir = self.home / ".claude"
        self.steps = []
        self.home.mkdir(parents=True, exist_ok=True)

    def _env(self, extra=None):
        e = os.environ.copy()
        e["HOME"] = str(self.home)
        e["PATH"] = f"{SHIMS}{os.pathsep}" + e.get("PATH", "")
        e["TZ"] = "UTC"
        e["LC_ALL"] = "C"
        e["NO_COLOR"] = "1"
        e.update(FIXED_GIT)
        for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
                  "GIT_COMMITTER_EMAIL", "CLAUDE_DIR"):
            e.pop(k, None)
        if extra:
            e.update(extra)
        return e

    def run(self, *argv, stdin=b"", env=None):
        data = stdin.encode() if isinstance(stdin, str) else stdin
        p = subprocess.run([self.cairn, *map(str, argv)], input=data,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           env=self._env(env), cwd=str(self.home))
        self.steps.append({"argv": list(map(str, argv)), "rc": p.returncode,
                           "out": p.stdout, "err": p.stderr})
        return p

    def seed(self, rel, content):
        f = self.claude_dir / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content.encode() if isinstance(content, str) else content)

    def seed_home(self, rel, content):
        f = self.home / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(content.encode() if isinstance(content, str) else content)


def _git(ctx, repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=ctx._env())
    return p.stdout


def snapshot(ctx):
    snap = {"tree": {}, "git": {}, "shims": {}}
    cd = ctx.claude_dir
    if cd.exists():
        for root, dirs, files in os.walk(cd):
            dirs[:] = [d for d in dirs if d != ".git"]
            for fn in files:
                p = Path(root) / fn
                rel = p.relative_to(cd).as_posix()
                # STATE/port is the python entry's own package copy (self-contained
                # deploy) — bash never writes it; excluded from the equivalence diff.
                if rel.startswith("cairn/port/"):
                    continue
                try:
                    snap["tree"][rel] = p.read_bytes()
                except OSError:
                    snap["tree"][rel] = b"<unreadable>"
    if ctx.home.exists():
        for name in sorted(os.listdir(ctx.home)):
            if name.startswith((".claude-", ".crontab", ".launchctl", ".pmset")):
                p = ctx.home / name
                if p.is_file():
                    snap["shims"][name] = p.read_bytes()
    skills = cd / "skills"
    if (skills / ".git").exists():
        snap["git"]["log"] = _git(ctx, skills, "log", "--pretty=%T%x09%an%x09%ae%x09%s")
        snap["git"]["status"] = _git(ctx, skills, "status", "--porcelain")
    return snap


def _norm_stamps(s):
    """Timestamp/suffix normalization shared by content AND path keys. STRICT & ordered
    (longest first) so a format regression still surfaces: seconds vs minute datetimes
    map to DISTINCT tokens, so a port that gains/loses a :SS field diffs rather than
    being silently equated."""
    s = re.sub(r'\.bak-\d{8}-\d{6}', ".bak-<TS>", s)
    s = re.sub(r'-\d{8}-\d{6}(?:-\d+)?', "-<TS>", s)       # archive/collision suffix
    s = re.sub(r'\.cairn-(tmp|st)\.\d+', r'.cairn-\1.<PID>', s)
    s = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', "<DATETIME_S>", s)  # seconds first
    s = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?!:)', "<DATETIME_M>", s)   # then minute
    s = re.sub(r'\b\d{8}-\d{6}\b', "<TS>", s)
    s = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', "<DATE>", s)
    return s


def _norm(b, ctx):
    """Normalize a captured stdout/stderr/file body before diffing."""
    s = b.decode("utf-8", "replace") if isinstance(b, (bytes, bytearray)) else b
    s = s.replace(str(ctx.claude_dir), "<CLAUDE_DIR>")   # longest first (contains home)
    s = s.replace(str(ctx.home), "<HOME>")
    s = re.sub(r'/var/folders/\S+', "<TMP>", s)
    s = re.sub(r'/private/tmp/\S+', "<TMP>", s)
    s = re.sub(r'/tmp/\S+', "<TMP>", s)
    return _norm_stamps(s)


def _norm_key(rel):
    """Normalize a $CLAUDE_DIR-relative PATH so a second-precision ts() baked into a
    directory/backup name (skill-archive/<name>-<TS>/, .bak-<TS>) doesn't spuriously
    diverge two runs that never share the same wall-clock second."""
    return _norm_stamps(rel)


def _keyed_tree(tree):
    """Map a {rawpath: bytes} tree to {normalized-key: bytes}. When several distinct
    real-timestamp paths collapse to the same normalized key (e.g. three CLAUDE.md.bak-
    <TS> from successive rewrites), disambiguate by the real-timestamp order and append
    a rank (#0,#1,…) so the two runs match POSITIONALLY — the k-th backup by creation
    time is the same logical file in both — instead of a nondeterministic last-wins."""
    from collections import defaultdict
    groups = defaultdict(list)
    for rel in tree:
        # Exclude `.bak-<TS>` backups from the tree diff: they are wall-clock-named
        # copies of a known prior state, and their very MULTIPLICITY is second-boundary
        # dependent (two rewrites in the same second collide to one file; across a
        # second boundary they stay two). That is inherent to bash cairn's ts()-named
        # backups, not a behavioral contract. Backup CREATION is still verified via the
        # announced "backup: <file>.bak-<ts>" line in the normalized stdout diff; the
        # live file's transition + git history cover the state. (Matches the synthesis's
        # idempotency exclusion set: .git / *.bak-* / logs.)
        if re.search(r'\.bak-\d{8}-\d{6}', rel):
            continue
        base = _norm_key(rel)
        order = tuple(re.findall(r'\d{8}-\d{6}', rel))   # real ts(es) -> creation order
        groups[base].append((order, rel))
    out = {}
    for base, items in groups.items():
        if len(items) == 1:
            out[base] = tree[items[0][1]]
        else:
            for i, (_, rel) in enumerate(sorted(items)):
                out[f"{base}#{i}"] = tree[rel]
    return out


def _ud(tag, a, b):
    import difflib
    a_l, b_l = a.splitlines(keepends=True), b.splitlines(keepends=True)
    return f"--- {tag} (oracle vs candidate) ---\n" + "".join(
        difflib.unified_diff(a_l, b_l, "oracle", "candidate", n=1))[:2500]


def compare(oc, os_, cc, cs):
    d = []
    if len(oc.steps) != len(cc.steps):
        d.append(f"STEP COUNT: oracle={len(oc.steps)} candidate={len(cc.steps)}")
    for i, (a, b) in enumerate(zip(oc.steps, cc.steps)):
        if a["rc"] != b["rc"]:
            d.append(f"step {i} argv={a['argv']}: EXIT oracle={a['rc']} candidate={b['rc']}")
        na, nb = _norm(a["out"], oc), _norm(b["out"], cc)
        if na != nb:
            d.append(_ud(f"stdout step {i} argv={a['argv']}", na, nb))
        ea, eb = _norm(a["err"], oc), _norm(b["err"], cc)
        if ea != eb:
            d.append(_ud(f"stderr step {i} argv={a['argv']}", ea, eb))
    # file tree — compare on NORMALIZED path keys so a second-precision ts() baked
    # into an archive/backup dir name doesn't diverge two runs a second apart.
    ta = _keyed_tree(os_["tree"])
    tb = _keyed_tree(cs["tree"])
    pa, pb = set(ta), set(tb)
    if pa != pb:
        d.append(f"TREE PATHS differ:\n  only in oracle:    {sorted(pa - pb)}\n  only in candidate: {sorted(pb - pa)}")
    for rel in sorted(pa & pb):
        na, nb = _norm(ta[rel], oc), _norm(tb[rel], cc)
        if na != nb:
            d.append(_ud(f"file {rel}", na, nb))
    # git + shims
    for k in sorted(set(os_["git"]) | set(cs["git"])):
        na, nb = _norm(os_["git"].get(k, b""), oc), _norm(cs["git"].get(k, b""), cc)
        if na != nb:
            d.append(_ud(f"git {k}", na, nb))
    for k in sorted(set(os_["shims"]) | set(cs["shims"])):
        na, nb = _norm(os_["shims"].get(k, b""), oc), _norm(cs["shims"].get(k, b""), cc)
        if na != nb:
            d.append(_ud(f"shim {k}", na, nb))
    return d


def load_scenarios(names):
    mods = []
    for f in sorted(SCEN_DIR.glob("s*.py")):
        if names and f.stem not in names and f.stem.split("_")[0] not in names:
            continue
        spec = importlib.util.spec_from_file_location(f.stem, f)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        mods.append((f.stem, m))
    return mods


def run_scenario(name, mod, oracle, candidate):
    tmp = Path(tempfile.mkdtemp(prefix="diffcairn-"))
    try:
        oc = Ctx(oracle, tmp / "oracle" / "home")
        cc = Ctx(candidate, tmp / "cand" / "home")
        mod.run(oc)
        mod.run(cc)
        diffs = compare(oc, snapshot(oc), cc, snapshot(cc))
        return diffs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    # After the flip, bin/cairn is the Python entry and the bash reference is
    # bin/cairn.bash; default to proving them equivalent. Pre-flip, fall back to
    # bin/cairn (bash) vs bin/cairn.py so the harness still runs.
    _bash = REPO / "bin" / "cairn.bash"
    _flipped = _bash.exists()
    ap.add_argument("--oracle", default=str(_bash if _flipped else REPO / "bin" / "cairn"))
    ap.add_argument("--candidate", default=str(REPO / "bin" / ("cairn" if _flipped else "cairn.py")))
    ap.add_argument("--scenario", action="append", default=[])
    a = ap.parse_args()
    a.oracle = str(Path(a.oracle).resolve())
    candidate = str(Path(a.candidate).resolve()) if a.candidate else a.oracle
    label = "SELF-CHECK (bash vs bash)" if candidate == a.oracle else "oracle vs candidate"
    print(f"diff-cairn: {label}\n  oracle    = {a.oracle}\n  candidate = {candidate}\n")
    mods = load_scenarios(a.scenario)
    if not mods:
        print("no scenarios found"); return 1
    fails = 0
    for name, mod in mods:
        diffs = run_scenario(name, mod, a.oracle, candidate)
        if diffs:
            fails += 1
            print(f"  ✗ {name}  ({len(diffs)} divergence(s))")
            for x in diffs[:6]:
                print("\n".join("      " + ln for ln in str(x).splitlines()))
        else:
            print(f"  ✓ {name}")
    print(f"\n{'ALL GREEN' if not fails else str(fails)+' SCENARIO(S) DIVERGED'} — {len(mods)} scenario(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
