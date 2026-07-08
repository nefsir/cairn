"""Skill-lifecycle helpers — archive_skill (the never-delete MOVE) and is_protected."""
from __future__ import annotations

import os
import shutil

from .clock import ts
from .context import Context


def archive_skill(ctx: Context, name: str) -> str | None:
    """Move a skill to $ARCHIVE/<name>-<ts> (never delete), stamp state=archived, return
    the dest path (or None on failure / missing). Collision suffix ``-<pid>``."""
    cfg = ctx.cfg
    d = cfg.skills / name
    if not d.is_dir():
        return None
    cfg.archive.mkdir(parents=True, exist_ok=True)
    dest = cfg.archive / f"{name}-{ts()}"
    if dest.exists():
        dest = cfg.archive / f"{dest.name}-{os.getpid()}"
    try:
        shutil.move(str(d), str(dest))
    except OSError:
        return None
    ctx.lib.run("meta", "set", str(dest / ".meta"), "state", "archived")
    return str(dest)


def is_protected(ctx: Context, name: str) -> bool:
    if name == "skill-extraction":
        return True
    meta = str(ctx.cfg.skills / name / ".meta")
    if ctx.lib.run("meta", "get", meta, "provenance").out == "bundled":
        return True
    if ctx.lib.run("meta", "get", meta, "pinned").out == "true":
        return True
    return False
