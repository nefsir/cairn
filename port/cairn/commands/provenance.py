"""cairn pin / unpin / provenance — freeze a skill from curation, or set/list
provenance. Ports bash _set_pin + cmd_provenance: meta init(no-clobber) + set +
whole-tree skills_commit, and the fixed-width ``provenance --list`` table.
"""
from __future__ import annotations

import glob
import os

from ..clock import today
from ..context import Context
from ..gitutil import skills_commit
from ..helpers import need_python, resolve_skill_dir
from ..out import die, ok

_LIST_FMT = "%-32s %-9s %-6s %-8s %-4s %-4s %s"


def _set_pin(ctx: Context, name: str, val: str) -> int:
    cfg = ctx.cfg
    d = resolve_skill_dir(cfg, name)
    if d is None:
        die(f"no skill '{name}' in {cfg.skills}")
    need_python()
    meta = f"{d}/.meta"
    day = today()
    ctx.lib.run("meta", "init", meta, f"created={day}", f"last_used={day}")
    ctx.lib.run("meta", "set", meta, "pinned", val)
    skills_commit(cfg, f"cairn: pin={val} {name}")
    ok(f"{name}: pinned={val}")
    return 0


def cmd_pin(ctx: Context, args: list[str]) -> int:
    if len(args) < 1:
        die("usage: cairn pin <name>")
    return _set_pin(ctx, args[0], "true")


def cmd_unpin(ctx: Context, args: list[str]) -> int:
    if len(args) < 1:
        die("usage: cairn unpin <name>")
    return _set_pin(ctx, args[0], "false")


def cmd_provenance(ctx: Context, args: list[str]) -> int:
    need_python()
    cfg = ctx.cfg
    first = args[0] if args else ""
    if first == "--list" or first == "":
        if not cfg.skills.is_dir():
            die(f"no skills dir at {cfg.skills}")
        print(_LIST_FMT % ("SKILL", "PROV", "PINNED", "STATE", "QUAL", "USED", "LAST_USED"))
        for d in sorted(glob.glob(f"{cfg.skills}/*/")):
            if not os.path.isfile(os.path.join(d, "SKILL.md")):
                continue
            name = os.path.basename(d.rstrip("/"))
            if name == "skill-extraction":
                continue
            meta = os.path.join(d, ".meta")
            if not os.path.isfile(meta):
                print(_LIST_FMT % (name, "(none)", "-", "-", "-", "-", "-"))
                continue

            def g(key: str) -> str:
                return ctx.lib.run("meta", "get", meta, key).out
            print(_LIST_FMT % (name, g("provenance"), g("pinned"), g("state"),
                               g("quality"), g("use_count"), g("last_used")))
        return 0

    name = first
    prov = args[1] if len(args) > 1 else ""
    if prov == "":
        die("usage: cairn provenance <name> <managed|bundled>")
    if prov not in ("managed", "bundled"):
        die("provenance must be 'managed' or 'bundled'")
    d = resolve_skill_dir(cfg, name)
    if d is None:
        die(f"no skill '{name}'")
    meta = f"{d}/.meta"
    day = today()
    ctx.lib.run("meta", "init", meta, f"created={day}", f"last_used={day}")
    ctx.lib.run("meta", "set", meta, "provenance", prov)
    skills_commit(cfg, f"cairn: provenance={prov} {name}")
    ok(f"{name}: provenance={prov}")
    return 0
