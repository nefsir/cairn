"""cairn status — health dashboard.

Ports bash cmd_status. The skills dashboard is the bash script's inline python lifted
verbatim (same reads, same print formats, byte-for-byte); the surrounding orchestration
(lifecycle / validate / memory / harvest / hook lines, separators, tip) is reproduced
with the lib seam + info() at the exact indentation bash emits.
"""
from __future__ import annotations

import glob
import os
import re

from ..clock import stamp_hm, today
from ..config import Config
from ..context import Context
from ..helpers import need_python
from ..out import hdr, info

SEP_DASH = "------------------------------------------------"
SEP_EQ = "================================================"


def _stale_days() -> int:
    return int(os.environ.get("CAIRN_STALE_DAYS") or 30)


def _archive_days() -> int:
    return int(os.environ.get("CAIRN_ARCHIVE_DAYS") or 90)


def _dashboard(skills: str, today_s: str, stale: int, arch: int) -> None:
    """Lifted verbatim from bash cmd_status' inline python (argv SKILLS/today/STALE/ARCH).
    Every print format is byte-identical; do not 'improve' it."""
    def meta_get(d, k):
        p = os.path.join(d, ".meta")
        if os.path.isfile(p):
            for line in open(p, errors="replace"):
                if line.strip().startswith(k + "="):
                    return line.split("=", 1)[1].strip()
        return ""

    def usage(d):
        p = os.path.join(d, "usage.md")
        sc = []
        if os.path.isfile(p):
            for l in open(p, errors="replace"):
                m = re.match(r"\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5", l)
                if m:
                    sc.append(int(m.group(1)))
        return sc

    def cases(d):
        p = os.path.join(d, "evals/cases.md")
        return sum(1 for l in open(p, errors="replace") if l.startswith("## Case")) if os.path.isfile(p) else 0

    def learns(d):
        p = os.path.join(d, "learnings.md")
        n = 0
        if os.path.isfile(p):
            for l in open(p, errors="replace"):
                s = l.strip()
                if s and not s.startswith("<!--") and (s.startswith("-") or re.match(r"^\d{4}-\d{2}-\d{2}", s)):
                    n += 1
        return n

    dirs = [d for d in sorted(glob.glob(os.path.join(skills, "*")))
            if os.path.isfile(os.path.join(d, "SKILL.md")) and os.path.basename(d) != "skill-extraction"]
    total = len(dirs)
    prov = {}
    state = {}
    quals = []
    improvable = 0
    rated = []
    never = 0
    biglearn = []
    for d in dirs:
        prov[meta_get(d, "provenance") or "(none)"] = prov.get(meta_get(d, "provenance") or "(none)", 0) + 1
        state[meta_get(d, "state") or "(none)"] = state.get(meta_get(d, "state") or "(none)", 0) + 1
        q = meta_get(d, "quality")
        if q.isdigit():
            quals.append(int(q))
        if cases(d) >= 5:
            improvable += 1
        sc = usage(d)
        if sc:
            rated.append((os.path.basename(d), sum(sc) / len(sc), len(sc)))
        else:
            never += 1
        if learns(d) >= 15:
            biglearn.append(os.path.basename(d))
    print("Skills:            %d" % total)
    print("  by provenance:   " + ", ".join("%s=%d" % (k, v) for k, v in sorted(prov.items())))
    print("  by state:        " + ", ".join("%s=%d" % (k, v) for k, v in sorted(state.items())))
    if quals:
        print("  quality scored:  %d (avg %.1f/5, %d unscored)" % (len(quals), sum(quals) / len(quals), total - len(quals)))
    print("  improvable (>=5 eval cases): %d" % improvable)
    print("  never rated:     %d" % never)
    if rated:
        overall = sum(a for _, a, _ in rated) / len(rated)
        print("  avg usefulness:  %.1f/5 (%d rated)" % (overall, len(rated)))
        low = sorted([(n, a, c) for n, a, c in rated if c >= 3 and a <= 2.5], key=lambda x: x[1])
        if low:
            print("  LOW usefulness (<=2.5, >=3 uses): %d  -> cairn improve / /skill-improve" % len(low))
            for n, a, c in low[:5]:
                print("      %s: %.1f/5 over %d" % (n, a, c))
    if biglearn:
        print("  fold candidates (>=15 learnings): %d  -> /skill-fold" % len(biglearn))


def cmd_status(ctx: Context, args: list[str]) -> int:
    need_python()
    cfg = ctx.cfg
    hdr(f"cairn status — {stamp_hm()}  (v{cfg.version})")
    if cfg.skills.is_dir():
        _dashboard(str(cfg.skills), today(), _stale_days(), _archive_days())
        life = ctx.lib.run("lifecycle", "propose", str(cfg.skills), today(),
                           _stale_days(), _archive_days()).out
        if life.strip("\n") != "":
            rows = [r for r in life.split("\n") if r]
            nstale = sum(1 for r in rows if r.split("\t")[2:3] == ["stale"])
            narch = sum(1 for r in rows if r.split("\t")[2:3] == ["archived"])
            info(f"  lifecycle ready: {nstale} -> stale, {narch} -> archived  (cairn curate --apply-lifecycle)")
        inv = ctx.lib.run("validate", "all", str(cfg.skills)).out
        inv_n = inv.count("\n")
        if inv_n != 0:
            info(f"  frontmatter issues: {inv_n}  -> cairn lint")
    else:
        info(f"Skills:            (none — {cfg.skills} missing; run cairn install)")
    print(SEP_DASH)
    if cfg.user_md.is_file() or cfg.memory_md.is_file():
        u = ctx.lib.run("memory", "chars", str(cfg.user_md)).value() if cfg.user_md.is_file() else "0"
        m = ctx.lib.run("memory", "chars", str(cfg.memory_md)).value() if cfg.memory_md.is_file() else "0"
        info(f"Memory: USER.md {u}/{cfg.user_cap} · MEMORY.md {m}/{cfg.memory_cap}")
    cand = cfg.harvest / "candidates.jsonl"
    prop = cfg.harvest / "PROPOSALS.md"
    if cand.is_file():
        n = sum(1 for l in cand.read_text(encoding="utf-8", errors="replace").split("\n") if l != "")
        info(f"Mined candidates:  {n}")
    else:
        info("Mined candidates:  none (cairn mine)")
    if prop.is_file():
        h = sum(1 for l in prop.read_text(encoding="utf-8", errors="replace").split("\n") if l.startswith("### "))
        info(f"Proposals:         {prop} ({h} headers)")
    else:
        info("Proposals:         none (cairn distill / refine)")
    if (cfg.harvest / "CURATE.md").is_file():
        info(f"Curate report:     {cfg.harvest / 'CURATE.md'}")
    settings = cfg.claude_dir / "settings.json"
    on = settings.is_file() and _grep_cairn_review(settings)
    info("SessionEnd hook:   on" if on else "SessionEnd hook:   off (enable: cairn install --enable-hooks)")
    print(SEP_EQ)
    info("tip: 'cairn curate' for merge/fold/lifecycle detail; 'cairn provenance --list' for the catalog.")
    return 0


def _grep_cairn_review(path) -> bool:
    # bash: grep -q 'cairn.*review' settings.json
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(re.search(r"cairn.*review", line) for line in text.split("\n"))
