"""cairn track --hook — PostToolUse telemetry: bump use_count/last_used for the skill
named in a Skill-tool invocation. Ports bash cmd_track incl. the defensive tool_input
walk (plugin:skill / a/b forms) and the best-effort (never-fail) meta updates.
"""
from __future__ import annotations

import json
import os
import sys

from ..clock import today
from ..context import Context
from ..helpers import need_python
from ..out import warn


def _skill_from_tool_input(skills: str, raw: str) -> str | None:
    """Recursively collect string values under tool_input; the first that names an
    installed skill (verbatim, after ':' , or after '/') wins. Mirrors the bash snippet."""
    try:
        d = json.loads(raw)
    except Exception:
        return None
    vals: list[str] = []

    def collect(x: object) -> None:
        if isinstance(x, str):
            vals.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                collect(v)
        elif isinstance(x, list):
            for v in x:
                collect(v)

    collect(d.get("tool_input") or {})
    for v in vals:
        for cand in (v, v.split(":")[-1], v.split("/")[-1]):
            if cand and os.path.isfile(os.path.join(skills, cand, "SKILL.md")):
                return cand
    return None


def cmd_track(ctx: Context, args: list[str]) -> int:
    if os.environ.get("CAIRN_DISABLE") or os.environ.get("CAIRN_REVIEW_HOOK"):
        return 0
    need_python()
    cfg = ctx.cfg
    if not cfg.skills.is_dir():
        return 0
    if (args[0] if args else "") != "--hook":
        warn("cairn track is a PostToolUse hook (use --hook)")
        return 0
    name = _skill_from_tool_input(str(cfg.skills), sys.stdin.read())
    if not name:
        return 0
    meta = cfg.skills / name / ".meta"
    day = today()
    # best-effort (bash: `… 2>/dev/null || true`) — telemetry never fails the tool call
    ctx.lib.run("meta", "init", str(meta), f"created={day}", f"last_used={day}")
    ctx.lib.run("meta", "set", str(meta), "last_used", day)
    ctx.lib.run("meta", "bump", str(meta), "use_count")
    return 0
