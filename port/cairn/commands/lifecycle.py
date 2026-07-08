"""cairn install / migrate / uninstall — the provision pipeline. Ported incrementally;
uninstall (self-contained) first, then install/migrate/provision.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
from pathlib import Path

from ..clock import ts
from ..config import BEGIN_MARK, END_MARK, Config
import shutil as _shutil

from ..context import Context
from ..helpers import need_python
from ..out import die, hdr, info, ok, warn
from ..provision import provision
from ..schedutil import sched_disable
from ..settingsjson import dumps, remove_cairn_hooks
from ..textblock import strip_block


def cmd_install(ctx: Context, args: list[str]) -> int:
    hooks = 0
    for a in args:
        if a == "--enable-hooks":
            hooks = 1
        else:
            die(f"install: unknown option {a}")
    need_python()
    if not _shutil.which("claude"):
        warn("claude not on PATH — file install proceeds; model steps (mine/review/assess) need it")
    provision(ctx, hooks, 0, dry=False)
    return 0


def cmd_migrate(ctx: Context, args: list[str]) -> int:
    assess = 1
    hooks = 0
    dry = False
    for a in args:
        if a == "--dry-run":
            dry = True
        elif a == "--no-assess":
            assess = 0
        elif a == "--enable-hooks":
            hooks = 1
        else:
            die(f"migrate: unknown option {a}")
    need_python()
    provision(ctx, hooks, assess, dry=dry)
    return 0


def _backup(src: Path, ts_s: str) -> None:
    try:
        shutil.copyfile(src, src.with_name(src.name + f".bak-{ts_s}"))
    except OSError:
        pass


def cmd_uninstall(ctx: Context, args: list[str]) -> int:
    cfg = ctx.cfg
    cairn_ts = ts()
    hdr("Uninstall")

    for f in sorted(glob.glob(str(cfg.assets / "commands" / "*.md"))):
        (cfg.commands / os.path.basename(f)).unlink(missing_ok=True)
    shutil.rmtree(cfg.templates / "skill-template", ignore_errors=True)
    (cfg.skills / "skill-extraction" / "SKILL.md").unlink(missing_ok=True)
    (cfg.skills / "skill-extraction" / ".meta").unlink(missing_ok=True)
    try:
        (cfg.skills / "skill-extraction").rmdir()
    except OSError:
        pass
    ok("removed commands, template, meta-skill")

    md = cfg.claude_dir / "CLAUDE.md"
    if md.is_file():
        text = md.read_text(encoding="utf-8", errors="replace")
        if BEGIN_MARK in text:
            _backup(md, cairn_ts)
            md.write_text(strip_block(text, BEGIN_MARK, END_MARK), encoding="utf-8")
            ok(f"managed block removed from CLAUDE.md (backup: CLAUDE.md.bak-{cairn_ts})")

    settings = cfg.claude_dir / "settings.json"
    if settings.is_file():
        stext = settings.read_text(encoding="utf-8", errors="replace")
        if "cairn" in stext:
            _backup(settings, cairn_ts)
            try:
                data = json.loads(stext)
            except Exception:
                data = None
            if isinstance(data, dict):
                remove_cairn_hooks(data)
                settings.write_text(dumps(data), encoding="utf-8")
            # if removing our hook left an empty {}, drop the file (the .bak preserves it)
            if re.sub(r"[ \n\t]", "", settings.read_text(encoding="utf-8", errors="replace")) == "{}":
                settings.unlink(missing_ok=True)
            ok("cairn hooks removed from settings.json")

    sched_disable(cfg)

    link = Path(os.environ.get("HOME") or Path.home()) / ".local" / "bin" / "cairn"
    if link.is_symlink() and os.readlink(str(link)).endswith("/cairn/bin/cairn"):
        link.unlink(missing_ok=True)

    info(f"Left untouched: your skills, their .meta, memory, the git repo, {cfg.state}.")
    info(f"Remove the rest yourself if you want: rm -rf {cfg.state}  (it holds the dispatcher + archive).")
    return 0
