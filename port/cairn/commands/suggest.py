"""cairn suggest ["<text>" | --hook | --tick] — surface matching skills.

Ports bash cmd_suggest exactly: manual / UserPromptSubmit-hook / PostToolUse-tick
modes, the @@ROSTER@@ names-only fallback re-render (the sentinel must never leak),
the per-session tick counter file, and the additionalContext JSON. Scoring is the
suggest lib via the in-process seam (stdin = the prompt).
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys

from ..clock import today  # noqa: F401 (kept parallel to bash; not used here)
from ..context import Context
from ..helpers import need_python

_MATCH_HDR = ("Skill check — installed skills matching this request. Invoke the fitting "
              "one via the Skill tool BEFORE improvising, or say why it does not apply:\n")
_ROSTER_HDR = ("Skill check — no installed skill matched this request strongly, but you "
               "may have one for it. If a name below fits, load it via the Skill tool "
               "(nearest by keyword first); otherwise proceed normally:\n")


def _platform() -> str:
    s = platform.system()
    if s == "Darwin":
        return "macos"
    if s == "Linux":
        return "linux"
    if s == "Windows":
        return "windows"      # net-new (no bash oracle); macos/linux match bash
    return ""


def _hook_prompt() -> str:
    try:
        return json.load(sys.stdin).get("prompt", "") or ""
    except Exception:
        return ""


def _tick_prompt(ctx: Context) -> str | None:
    n_raw = os.environ.get("CAIRN_SUGGEST_TICK") or "8"
    if not n_raw.isdigit():
        return None
    n = int(n_raw)
    if n <= 0:
        return None
    try:
        d = json.load(sys.stdin)
        sid_raw = d.get("session_id", "") or "s"
        tp = d.get("transcript_path", "") or ""
    except Exception:
        sid_raw, tp = "s", ""
    sid = re.sub(r"[^A-Za-z0-9_-]", "", sid_raw) or "s"
    if not tp or not os.path.isfile(tp):
        return None
    ctx.cfg.state.mkdir(parents=True, exist_ok=True)
    cf = ctx.cfg.state / f".suggest-tick-{sid}"
    try:
        cnt = int(cf.read_text(encoding="utf-8", errors="replace") or "0")
    except (OSError, ValueError):
        cnt = 0
    cnt += 1
    cf.write_text(str(cnt), encoding="utf-8")
    if cnt % n != 0:
        return None
    return ctx.lib.run("transcript", "last-user", tp).out


def cmd_suggest(ctx: Context, args: list[str]) -> int:
    if "--hook" in args and (os.environ.get("CAIRN_DISABLE") or os.environ.get("CAIRN_REVIEW_HOOK")):
        return 0
    need_python()
    cfg = ctx.cfg
    if not cfg.skills.is_dir():
        return 0
    first = args[0] if args else ""
    mode = "manual"
    prompt = ""
    if first == "--hook":
        mode = "hook"
        prompt = _hook_prompt()
    elif first == "--tick":
        mode = "tick"
        p = _tick_prompt(ctx)
        if p is None:
            return 0
        prompt = p
    elif first == "":
        return 0
    else:
        prompt = " ".join(args)

    if prompt == "":
        return 0

    topk = os.environ.get("CAIRN_SUGGEST_TOPK") or "3"
    matches = ctx.lib.run("suggest", str(cfg.skills), topk, _platform(), stdin=prompt).out
    matches = matches.rstrip("\n")   # bash $(…) strips trailing newlines
    if matches == "":
        return 0

    if matches.startswith("@@ROSTER@@"):
        if mode == "tick":
            return 0
        parts = matches.split("\t")
        rextra = parts[1] if len(parts) > 1 else ""
        rnames = "\t".join(parts[2:]) if len(parts) > 2 else ""
        sys.stdout.write(_ROSTER_HDR + f"  {rnames}\n")
        if rextra.isdigit() and rextra != "0":
            sys.stdout.write(f'  (+{rextra} more — refine wording or run: cairn suggest "<keywords>")\n')
        return 0

    lines = []
    for line in matches.split("\n"):
        if not line:
            continue
        f = line.split("\t")
        n = f[0]
        d = "\t".join(f[2:]) if len(f) > 2 else ""
        if n:
            lines.append(f"  - {n} — {d}")
    block = "\n".join(lines)

    if mode == "tick":
        ctxtext = ("Skill check (still relevant mid-task) — if you have not yet, invoke "
                   "the fitting skill via the Skill tool, or note why it does not apply:\n" + block)
        sys.stdout.write(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PostToolUse", "additionalContext": ctxtext}}) + "\n")
    else:
        sys.stdout.write(_MATCH_HDR + block + "\n")
    return 0
