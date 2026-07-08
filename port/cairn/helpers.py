"""Shared helpers ported from bash — dependency gates and skill-dir resolution.
Ported incrementally as commands need them (put/skills_git/etc. arrive with unit 6).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import Config
from .out import die


def need_python() -> None:
    if shutil.which("python3") is None:
        die("python3 required for this command")


def need_claude() -> None:
    if shutil.which("claude") is None:
        die("claude not on PATH (install Claude Code first)")


def has_git() -> bool:
    return shutil.which("git") is not None


def resolve_skill_dir(cfg: Config, name: str) -> str | None:
    """Global-then-project lookup, matching bash resolve_skill_dir. Returns the dir
    path (str, for the lib seam) or None if not found."""
    d = cfg.skills / name
    if d.is_dir():
        return str(d)
    p = Path(os.getcwd()) / ".claude" / "skills" / name
    if p.is_dir():
        return str(p)
    return None
