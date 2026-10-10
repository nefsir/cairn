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


def _dirty_paths(cfg: Config) -> list[str]:
    out = _git(cfg, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    parts = out.split("\0")
    paths, i = [], 0
    while i < len(parts):
        e = parts[i]
        i += 1
        if len(e) < 4:
            continue
        xy, path = e[:2], e[3:]
        if xy[0] in "RC":
            i += 1  # skip the rename source
        paths.append(path)
    return paths


def _bytes(cfg: Config, rel: str) -> bytes | None:
    p = cfg.skills / rel
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def snapshot_dirty(cfg: Config) -> dict[str, bytes | None]:
    return {rel: _bytes(cfg, rel) for rel in _dirty_paths(cfg)}


def changed_since(cfg: Config, snap: dict[str, bytes | None]) -> list[str]:
    now = set(_dirty_paths(cfg))
    changed = {p for p in now if p not in snap or _bytes(cfg, p) != snap[p]}
    changed |= {p for p in snap if p not in now}  # run restored it to HEAD
    return sorted(changed)


def skill_names(paths: list[str]) -> list[str]:
    return sorted({p.split("/")[0] for p in paths if p})


def commit_paths(cfg: Config, paths: list[str], message: str) -> None:
    if not paths or not skills_is_repo(cfg):
        return
    _git(cfg, "add", "-A", "--", *paths)
    ident = [] if _git(cfg, "config", "user.email").stdout.strip() else \
        ["-c", "user.name=cairn", "-c", "user.email=cairn@localhost"]
    _git(cfg, *ident, "commit", "-q", "-m", message, "--", *paths)


def revert_paths(cfg: Config, snap: dict[str, bytes | None], paths: list[str]) -> None:
    for rel in paths:
        full = cfg.skills / rel
        if rel in snap:
            data = snap[rel]
            if data is None:
                full.unlink(missing_ok=True)
            else:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_bytes(data)
        elif _git(cfg, "ls-files", "--error-unmatch", "--", rel).returncode == 0:
            _git(cfg, "checkout", "--", rel)
        else:
            full.unlink(missing_ok=True)
        d = full.parent
        while d != cfg.skills and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
