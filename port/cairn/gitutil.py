"""Git helpers for the skills repo — ported from bash skills_git/skills_is_repo/
skills_commit. Best-effort throughout (a git failure never aborts a command). The
commit is deterministic: whole-tree ``add -A``, skip when nothing is staged, and the
``cairn@localhost`` identity fallback when no user identity is configured — so the
commit object (tree + author + subject) matches the bash oracle byte-for-byte.
"""
from __future__ import annotations

import subprocess

from .config import Config
from .helpers import has_git
from .out import info


def _git(cfg: Config, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cfg.skills), *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        encoding="utf-8", errors="replace",
    )


def skills_is_repo(cfg: Config) -> bool:
    if not has_git():
        return False
    return _git(cfg, "rev-parse", "--git-dir").returncode == 0


def skills_changed_names(cfg: Config) -> list[str]:
    """Unique top-level skill dir names touched in the working tree — ports
    `skills_git status --porcelain | awk '{print $NF}' | cut -d/ -f1 | sort -u`."""
    names = set()
    for line in _git(cfg, "status", "--porcelain").stdout.split("\n"):
        if not line.strip():
            continue
        last = line.split()[-1]          # awk $NF
        names.add(last.split("/")[0])    # cut -d/ -f1
    return sorted(names)


def skills_commit(cfg: Config, message: str, dry: bool = False) -> None:
    """Commit all of skills/ (best-effort). Ports bash skills_commit exactly."""
    if dry:
        info(f"would commit skills/: {message}")
        return
    if not skills_is_repo(cfg):
        return
    _git(cfg, "add", "-A")
    if _git(cfg, "diff", "--cached", "--quiet").returncode == 0:
        return  # nothing staged
    email = _git(cfg, "config", "user.email").stdout.strip()
    if email:
        _git(cfg, "commit", "-q", "-m", message)
    else:
        _git(cfg, "-c", "user.name=cairn", "-c", "user.email=cairn@localhost",
             "commit", "-q", "-m", message)
