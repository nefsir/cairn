"""settings.json hook surgery — the pure JSON transforms lifted verbatim from bash's
inline python (enable_hooks / uninstall). Serialization matches bash exactly: change is
gated on the ``sort_keys=True`` snapshot, but the file is WRITTEN insertion-order with
``indent=2`` and no trailing newline (``json.dumps(indent=2)``).
"""
from __future__ import annotations

import json


def enable_hooks_transform(data: object, cairn_bin: str, logf: str) -> tuple[bool, dict]:
    """Upsert cairn's three hooks; return (changed, data). Lifted from bash enable_hooks."""
    if not isinstance(data, dict):
        data = {}
    before = json.dumps(data, sort_keys=True)
    hooks = data.setdefault("hooks", {})

    def upsert(event: str, needle: str, command: str, matcher: str | None = None) -> None:
        arr = hooks.setdefault(event, [])
        for group in arr:
            for h in (group.get("hooks", []) if isinstance(group, dict) else []):
                if isinstance(h, dict) and "cairn" in str(h.get("command", "")) and needle in str(h.get("command", "")):
                    h["command"] = command
                    return
        grp: dict = {"hooks": [{"type": "command", "command": command}]}
        if matcher:
            grp["matcher"] = matcher
        arr.append(grp)

    upsert("SessionEnd", "review",
           '[ -n "${CAIRN_REVIEW_HOOK:-}" ] && exit 0; "%s" review --enqueue >> "%s" 2>&1' % (cairn_bin, logf))
    upsert("UserPromptSubmit", "suggest", '"%s" suggest --hook 2>/dev/null || true' % cairn_bin)
    upsert("PostToolUse", "track", '"%s" track --hook 2>/dev/null || true' % cairn_bin, matcher="Skill")

    changed = json.dumps(data, sort_keys=True) != before
    return changed, data


def remove_cairn_hooks(data: dict) -> dict:
    """Prune only cairn's own hooks, preserving foreign hooks AND each surviving group's
    other keys (e.g. ``matcher``). This intentionally fixes the old bash oracle's
    matcher-drop wart, so it diverges from bash on the (untested) mixed-matcher path."""
    def is_cairn(h: object) -> bool:
        c = str(h.get("command", "")) if isinstance(h, dict) else ""
        return "cairn" in c and ("review" in c or "suggest" in c or "track" in c)

    for event in ("SessionEnd", "UserPromptSubmit", "PostToolUse"):
        arr = data.get("hooks", {}).get(event, [])
        keep = []
        for group in arr:
            hs = [h for h in (group.get("hooks", []) if isinstance(group, dict) else []) if not is_cairn(h)]
            if hs:
                group["hooks"] = hs   # mutate in place -> retains matcher + any other group keys
                keep.append(group)
        if "hooks" in data and event in data["hooks"]:
            if keep:
                data["hooks"][event] = keep
            else:
                del data["hooks"][event]
        if "hooks" in data and not data["hooks"]:
            del data["hooks"]
    return data


def dumps(data: object) -> str:
    """bash ``json.dump(data, f, indent=2)`` — insertion order, no trailing newline."""
    return json.dumps(data, indent=2)
