#!/usr/bin/env python3
"""lib-parity — proves the in-process LibRunner is byte-identical to a real
``python3 lib/<helper>.py`` subprocess for the same (argv, stdin): same rc, stdout,
stderr AND resulting files. Covers every observable mechanism the seam must reproduce
(stdout value, multiline, file write + rc0, rc2 + stderr, usage-doc, stdin, rc1), which
suffices because all libs share the print/sys.exit/return-int pattern.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIB = REPO / "lib"
sys.path.insert(0, str(REPO / "port"))
from cairn.libseam import LibRunner  # noqa: E402

runner = LibRunner(LIB)

_META = (
    "provenance=managed\npinned=false\nstate=active\ncreated=2020-01-01\n"
    "last_used=2020-01-01\nlast_patched=\nuse_count=3\nquality=5\n"
)
_GOOD_SKILL = (
    "---\nname: redis-timeout-x\n"
    "description: diagnose redis command timeout lettuce pool exhaustion\n---\nbody\n"
)
_BAD_SKILL = "---\nname: bad\n---\n"   # missing description


def _seed_meta(d: Path) -> None:
    (d / "s.meta").write_text(_META, encoding="utf-8")


def _seed_skills(d: Path) -> None:
    g = d / "skills" / "redis-timeout-x"
    g.mkdir(parents=True)
    (g / "SKILL.md").write_text(_GOOD_SKILL, encoding="utf-8")


def _seed_bad(d: Path) -> None:
    b = d / "skills" / "bad"
    b.mkdir(parents=True)
    (b / "SKILL.md").write_text(_BAD_SKILL, encoding="utf-8")


# (name, helper, argv-builder, stdin, setup, env-extra)
CASES = [
    ("meta-get-value",    "meta", lambda d: ["get", f"{d}/s.meta", "quality"], "", _seed_meta, {}),
    ("meta-get-missing",  "meta", lambda d: ["get", f"{d}/s.meta", "nope"], "", _seed_meta, {}),
    ("meta-dump",         "meta", lambda d: ["dump", f"{d}/s.meta"], "", _seed_meta, {}),
    ("meta-set-write",    "meta", lambda d: ["set", f"{d}/s.meta", "quality", "4"], "", _seed_meta, {}),
    ("meta-bump-write",   "meta", lambda d: ["bump", f"{d}/s.meta", "use_count"], "", _seed_meta, {}),
    ("meta-init-create",  "meta", lambda d: ["init", f"{d}/new.meta", "created=2020-01-01", "quality=3"], "", lambda d: None, {}),
    ("meta-getkey-rc2",   "meta", lambda d: ["get", f"{d}/s.meta"], "", _seed_meta, {}),
    ("suggest-stdin-hit", "suggest", lambda d: [f"{d}/skills", "3", "macos"], "redis command timeout lettuce pool", _seed_skills, {"CAIRN_SUGGEST_THRESHOLD": "1"}),
    ("suggest-stdin-silent", "suggest", lambda d: [f"{d}/skills", "3", "macos"], "thanks looks good", _seed_skills, {"CAIRN_SUGGEST_THRESHOLD": "1"}),
    ("validate-good-rc0", "validate", lambda d: ["skill", f"{d}/skills/redis-timeout-x"], "", _seed_skills, {}),
    ("validate-bad-rc1",  "validate", lambda d: ["skill", f"{d}/skills/bad"], "", _seed_bad, {}),
]


def _snapshot(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes()
            for p in sorted(d.rglob("*")) if p.is_file()}


def _subprocess(helper, args, stdin, env):
    p = subprocess.run(
        [sys.executable, str(LIB / f"{helper}.py"), *args],
        input=stdin.encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    )
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def main() -> int:
    fails = 0
    base_env = os.environ.copy()
    base_env.update({"LC_ALL": "C", "TZ": "UTC", "NO_COLOR": "1"})
    for name, helper, build, stdin, setup, env_extra in CASES:
        # --- subprocess path (oracle) in dir A
        da = Path(tempfile.mkdtemp(prefix="parA-"))
        setup(da)
        sp_rc, sp_out, sp_err = _subprocess(helper, build(da), stdin, {**base_env, **env_extra})
        sp_tree = {k: v for k, v in _snapshot(da).items()}
        # --- in-process path (candidate) in dir B, env-matched for the relevant vars
        db = Path(tempfile.mkdtemp(prefix="parB-"))
        setup(db)
        saved = {k: os.environ.get(k) for k in env_extra}
        os.environ.update(env_extra)
        try:
            res = runner.run(helper, *build(db), stdin=stdin)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        ip_tree = _snapshot(db)
        # --- compare (normalize the only legitimate difference: the temp dir path)
        so = sp_out.replace(str(da), "<D>"); io_ = res.out.replace(str(db), "<D>")
        se = sp_err.replace(str(da), "<D>"); ie = res.err.replace(str(db), "<D>")
        st = {k: v.replace(str(da).encode(), b"<D>") for k, v in sp_tree.items()}
        it = {k: v.replace(str(db).encode(), b"<D>") for k, v in ip_tree.items()}
        diffs = []
        if sp_rc != res.rc:
            diffs.append(f"rc {sp_rc} != {res.rc}")
        if so != io_:
            diffs.append(f"stdout:\n    subp={so!r}\n    inproc={io_!r}")
        if se != ie:
            diffs.append(f"stderr:\n    subp={se!r}\n    inproc={ie!r}")
        if st != it:
            diffs.append(f"files: {sorted(st)} vs {sorted(it)}")
        if diffs:
            fails += 1
            print(f"  ✗ {name}")
            for x in diffs:
                print("      " + x)
        else:
            print(f"  ✓ {name}")
    print(f"\n{'ALL GREEN' if not fails else str(fails)+' FAILED'} — {len(CASES)} parity cases")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
