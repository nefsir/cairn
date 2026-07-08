"""cairn improve [name] — eval->fix->re-eval loop over skills with >=5 eval cases and
fresh signal. Ports cmd_improve + improve_one: the candidate picker (inline python lifted
verbatim), the per-skill claude loop (scoped, CAIRN_REVIEW_HOOK on env), and the
battery gate.
"""
from __future__ import annotations

import glob
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path


def _on_battery() -> bool:
    """--battery-skip probe. macOS: pmset (byte-identical to bash). Windows: NET-NEW
    GetSystemPowerStatus via ctypes. Elsewhere: never on battery (bash has no probe)."""
    if platform.system() == "Windows":
        try:
            import ctypes

            class _PS(ctypes.Structure):
                _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                            ("BatteryLifePercent", ctypes.c_byte), ("Reserved1", ctypes.c_byte),
                            ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]
            ps = _PS()
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(ps)):
                return ps.ACLineStatus == 0   # 0 = offline (on battery)
        except Exception:
            return False
        return False
    if shutil.which("pmset"):
        batt = subprocess.run(["pmset", "-g", "batt"], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace").stdout
        return "Battery Power" in batt
    return False

from ..clock import today
from ..context import Context
from ..gitutil import skills_commit
from ..helpers import need_claude, need_python, resolve_skill_dir
from ..out import die, ok, say, warn

IMPROVE_PROMPT = """You are running ONE autonomous iteration of a skill-improvement loop in the
current directory (a skill: SKILL.md, learnings.md, usage.md, evals/cases.md,
evals/runs.md). No user is present — ask nothing, make conservative choices.
1. Read evals/runs.md first; do not repeat edits a prior iteration rolled back.
2. Execute every case in evals/cases.md by following SKILL.md literally.
3. Grade each against its pass criteria; compute the pass rate.
4. Analyze failures: triggering (description), procedure gap (body), or missing
   knowledge (learnings/references).
5. Apply MINIMAL targeted edits to SKILL.md (and learnings.md if apt). Never
   rewrite wholesale; re-read before editing; keep frontmatter valid; preserve
   the learnings-loop sections.
6. Re-run the previously failing cases; compute the new pass rate.
7. Append to evals/runs.md: date, pass rate before -> after, edits (one line
   each), open issues. If the case set is too weak to grade, improve
   evals/cases.md instead and say so in runs.md."""


def improve_one(ctx: Context, d: str, iters, model: str) -> bool:
    cfg = ctx.cfg
    name = os.path.basename(d)
    it = iters if (isinstance(iters, str) and iters.isdigit()) else "1"
    n = int(it)
    if n < 1:
        n = 1
    lf = cfg.logs / "improve.log"
    for i in range(1, n + 1):
        say(lf, f"improving {name} iteration {i}/{n} (model {model})")
        env = os.environ.copy()
        env["CAIRN_REVIEW_HOOK"] = "1"
        with open(lf, "ab") as log:
            rc = subprocess.run(
                ["claude", "-p", IMPROVE_PROMPT, "--model", model, "--max-turns", "50",
                 "--permission-mode", "acceptEdits", "--allowedTools", "Read,Edit,Write,Glob,Grep"],
                cwd=d, stdout=log, stderr=subprocess.STDOUT, env=env).returncode
        if rc != 0:
            say(lf, f"iteration {i} failed (rc={rc}) on {name}")
            return False
    ctx.lib.run("meta", "set", f"{d}/.meta", "last_patched", today())
    (Path(d) / "evals" / ".last-improve").touch()
    return True


def _pick(SKILLS, MAX):
    """Ready-skill picker — lifted verbatim from bash cmd_improve's inline python."""
    def mt(p):
        try:
            return os.path.getmtime(p)
        except OSError:
            return 0.0

    def usage_avg(p):
        if not os.path.isfile(p):
            return None
        sc = []
        for line in open(p, errors='replace'):
            m = re.match(r'\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5', line)
            if m:
                sc.append(int(m.group(1)))
        return (sum(sc) / len(sc)) if sc else None

    def meta_get(d, k):
        p = os.path.join(d, '.meta')
        if os.path.isfile(p):
            for line in open(p, errors='replace'):
                if line.strip().startswith(k + '='):
                    return line.split('=', 1)[1].strip()
        return ''
    rows = []
    for d in sorted(glob.glob(os.path.join(SKILLS, '*'))):
        name = os.path.basename(d)
        if name == 'skill-extraction' or not os.path.isdir(d):
            continue
        sk, lr, cs = (os.path.join(d, f) for f in ('SKILL.md', 'learnings.md', 'evals/cases.md'))
        if not (os.path.isfile(sk) and os.path.isfile(cs)):
            continue
        try:
            cases = sum(1 for l in open(cs, errors='replace') if l.startswith('## Case'))
        except OSError:
            cases = 0
        if cases < 5:
            continue
        if meta_get(d, 'state') == 'archived':
            continue
        stamp = os.path.join(d, 'evals/.last-improve')
        st = mt(stamp)
        newest = max(mt(lr), mt(os.path.join(d, 'usage.md')))
        if st and newest <= st:
            continue
        q = meta_get(d, 'quality')
        qk = int(q) if q.isdigit() else 9
        avg = usage_avg(os.path.join(d, 'usage.md'))
        ak = avg if avg is not None else 9.9
        rows.append((qk, ak, -newest, name))
    rows.sort()
    return [r[3] for r in rows[:MAX]]


def cmd_improve(ctx: Context, args: list[str]) -> int:
    need_python()
    cfg = ctx.cfg
    MAX = int(os.environ.get("CAIRN_IMPROVE_MAX") or 2)
    ITER = os.environ.get("CAIRN_IMPROVE_ITERATIONS") or "1"
    model = cfg.model_default
    one = ""
    dryr = batt_skip = 0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--max":
            MAX = int(args[i + 1]) if i + 1 < len(args) else 2; i += 1
        elif a == "--iterations":
            ITER = args[i + 1] if i + 1 < len(args) else "1"; i += 1
        elif a == "--model":
            model = args[i + 1] if i + 1 < len(args) else cfg.model_default; i += 1
        elif a == "--dry-run":
            dryr = 1
        elif a == "--battery-skip":
            batt_skip = 1
        elif a.startswith("--"):
            die(f"improve: unknown option {a}")
        else:
            one = a
        i += 1
    if not cfg.skills.is_dir():
        die(f"no skills dir at {cfg.skills}")
    cfg.logs.mkdir(parents=True, exist_ok=True)

    if batt_skip == 1 and _on_battery():
        ok("on battery — skipping (--battery-skip)")
        return 0

    if one:
        d = resolve_skill_dir(cfg, one)
        if d is None:
            die(f"no skill '{one}'")
        cases = os.path.join(d, "evals", "cases.md")
        nc = 0
        if os.path.isfile(cases):
            nc = sum(1 for l in open(cases, errors="replace") if l.startswith("## Case"))
        if nc < 5:
            die(f"{one} has <5 eval cases — write more first (/skill-improve helps)")
        if dryr == 1:
            ok(f"would improve {one} ({ITER} iteration(s), model {model})")
            return 0
        need_claude()
        if improve_one(ctx, d, ITER, model):
            skills_commit(cfg, f"cairn: improve {one}")
            ok(f"improved {one}")
        else:
            warn(f"improve {one} ended with errors (see {cfg.logs / 'improve.log'})")
        return 0

    cand = _pick(str(cfg.skills), MAX)
    if not cand:
        ok("nothing to improve (no skill with >=5 cases + fresh signal)")
        return 0
    if dryr == 1:
        ok("would improve: " + " ".join(cand) + " ")
        return 0
    need_claude()
    n = 0
    for name in cand:
        if improve_one(ctx, str(cfg.skills / name), ITER, model):
            n += 1
            ok(f"improved {name}")
        else:
            warn(f"FAILED {name} (continuing)")
    skills_commit(cfg, f"cairn: improve ({n} skill(s))")
    ok(f"improve run complete ({n} skill(s))")
    return 0
