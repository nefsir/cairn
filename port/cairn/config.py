"""Runtime configuration — every path derives from ``CLAUDE_DIR`` (env-overridable),
mirroring the bash dispatcher's global block. Read at process start (each cairn
invocation is a fresh process), so the throwaway-sandbox test harness works by simply
setting ``HOME``/``CLAUDE_DIR``.

Ports lines 24 & 44-72 of ``bin/cairn`` exactly, including defaults.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import CAIRN_VERSION

# Managed CLAUDE.md block markers — MUST byte-match assets/claude-block.md.
BEGIN_MARK = "<!-- BEGIN cairn (managed by cairn) -->"
END_MARK = "<!-- END cairn -->"
# v1 ("skill-system") markers, stripped on migrate.
OLD_BEGIN = "<!-- BEGIN skill-system (managed by claude-skill-system installer) -->"
OLD_END = "<!-- END skill-system -->"

# Transient-error pattern shared by every resilient ``claude -p`` caller (verbatim).
TRANSIENT_RE = (
    r"rate.?limit|quota|overloaded|too many requests|429|503|529|timeout|"
    r"timed out|temporarily|try again|connection|network|ECONNRESET|ETIMEDOUT"
)


@dataclass(frozen=True)
class Config:
    """Resolved paths + constants for one cairn invocation."""
    version: str
    cairn_home: Path        # repo root or ~/.claude/cairn (where bin/lib/assets live)
    lib: Path
    assets: Path
    logo: Path
    claude_dir: Path
    skills: Path
    memories: Path
    commands: Path
    templates: Path
    state: Path
    harvest: Path
    archive: Path
    logs: Path
    user_md: Path
    memory_md: Path
    user_cap: int
    memory_cap: int
    model_default: str

    # --- convenience string forms (bash interpolates the raw path, no trailing slash)
    def s(self, p: Path) -> str:
        return str(p)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_config(cairn_home: Path, env: os._Environ[str] | None = None) -> Config:
    """Build the Config for this run.

    ``cairn_home`` is the resolved directory that contains ``bin/``, ``lib/`` and
    ``assets/`` — the launcher passes ``<entry>/../..`` so it equals the bash
    ``CAIRN_HOME`` (repo root or ~/.claude/cairn).
    """
    e = os.environ if env is None else env
    cairn_home = Path(cairn_home).resolve()
    home = Path(e.get("HOME") or Path.home())
    claude_dir = Path(e["CLAUDE_DIR"]) if e.get("CLAUDE_DIR") else home / ".claude"
    state = claude_dir / "cairn"
    memories = claude_dir / "memories"
    return Config(
        version=CAIRN_VERSION,
        cairn_home=cairn_home,
        lib=cairn_home / "lib",
        assets=cairn_home / "assets",
        logo=cairn_home / "cairn-logo.txt",
        claude_dir=claude_dir,
        skills=claude_dir / "skills",
        memories=memories,
        commands=claude_dir / "commands",
        templates=claude_dir / "templates",
        state=state,
        harvest=state / "harvest",
        archive=state / "skill-archive",
        logs=state / "logs",
        user_md=memories / "USER.md",
        memory_md=memories / "MEMORY.md",
        user_cap=_int_env("CAIRN_USER_CAP", 1375),
        memory_cap=_int_env("CAIRN_MEMORY_CAP", 2200),
        model_default=e.get("CAIRN_MODEL") or "sonnet",
    )
