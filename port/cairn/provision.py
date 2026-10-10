"""The provision pipeline — ports bash provision() + its helpers (put, swap_block,
self_install, link_cairn, stamp_meta, seed_feedback, dir_date, detect_existing,
relocate_state, enable_hooks, assess_skills, low_quality_list, unscored_managed_exists).
Every stdout line matches bash byte-for-byte; file/git effects match too (proven by the
install scenarios' full-tree + git-log diff, incl. the un-normalized short-HEAD hash).
"""
from __future__ import annotations

import filecmp
import glob
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from .claude import score_one_skill
from .clock import stamp, today, ts
from .config import BEGIN_MARK, END_MARK, OLD_BEGIN, OLD_END, Config
from .context import Context
from .gitutil import _git, skills_commit, skills_is_repo
from .helpers import has_git
from .out import hdr, info, ok, warn
from .settingsjson import dumps, enable_hooks_transform
from .textblock import strip_block, trim_trailing_blank


def _cmp(a: Path, b: Path) -> bool:
    try:
        return a.is_file() and b.is_file() and filecmp.cmp(str(a), str(b), shallow=False)
    except OSError:
        return False


def _backup(f: Path, ts_s: str) -> None:
    try:
        shutil.copyfile(f, f.with_name(f.name + f".bak-{ts_s}"))
    except OSError:
        pass


def put(src: Path, dest: Path, label: str, dry: bool, ts_s: str) -> None:
    if dry:
        if dest.is_file() and _cmp(src, dest):
            info(f"would skip {label} (unchanged)")
        elif dest.is_file():
            info(f"would update {label} (backing up existing)")
        else:
            info(f"would create {label}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and _cmp(src, dest):
        ok(f"{label} (unchanged)")
    elif dest.is_file():
        _backup(dest, ts_s)
        shutil.copyfile(src, dest)
        ok(f"{label} (updated; backup: {dest.name}.bak-{ts_s})")
    else:
        shutil.copyfile(src, dest)
        ok(f"{label} (created)")


def dir_date(d: Path) -> str:
    try:
        return datetime.fromtimestamp(int(os.path.getmtime(d))).strftime("%Y-%m-%d")
    except OSError:
        return today()


def detect_existing(cfg: Config) -> bool:
    if cfg.skills.is_dir() and any(p.is_dir() for p in cfg.skills.glob("*")):
        return True
    md = cfg.claude_dir / "CLAUDE.md"
    if md.is_file():
        t = md.read_text(encoding="utf-8", errors="replace")
        if OLD_BEGIN in t or BEGIN_MARK in t:
            return True
    scripts = cfg.claude_dir / "scripts"
    if scripts.is_dir() and any(scripts.glob("skill-*.sh")):
        return True
    return False


def relocate_state(cfg: Config, dry: bool) -> None:
    if dry:
        if (cfg.claude_dir / "skill-harvest").is_dir():
            info("would move skill-harvest -> cairn/harvest")
        if (cfg.claude_dir / "skill-archive").is_dir():
            info("would move skill-archive -> cairn/skill-archive")
        return
    if (cfg.claude_dir / "skill-harvest").is_dir() and not cfg.harvest.exists():
        cfg.state.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cfg.claude_dir / "skill-harvest"), str(cfg.harvest))
        ok("moved skill-harvest -> cairn/harvest")
    if (cfg.claude_dir / "skill-archive").is_dir() and not cfg.archive.exists():
        cfg.state.mkdir(parents=True, exist_ok=True)
        shutil.move(str(cfg.claude_dir / "skill-archive"), str(cfg.archive))
        ok("moved skill-archive -> cairn/skill-archive")


_DEPLOY_SUBDIRS = ("bin", "lib", "assets", "tests", "port")


def source_id(cairn_home: Path) -> str:
    """Identity of the code being installed: git HEAD (+dirty) or a content hash."""
    try:
        head = subprocess.run(["git", "-C", str(cairn_home), "rev-parse", "HEAD"],
                              capture_output=True, text=True)
        if head.returncode == 0:
            dirty = subprocess.run(
                ["git", "-C", str(cairn_home), "status", "--porcelain", "--", *_DEPLOY_SUBDIRS],
                capture_output=True, text=True).stdout.strip()
            return head.stdout.strip() + ("+dirty" if dirty else "")
    except OSError:
        pass
    h = hashlib.sha256()
    for sub in _DEPLOY_SUBDIRS:
        base = cairn_home / sub
        for p in sorted(base.rglob("*")) if base.is_dir() else []:
            if p.is_file() and "__pycache__" not in p.parts:
                h.update(p.relative_to(cairn_home).as_posix().encode())
                h.update(p.read_bytes())
    return "tree:" + h.hexdigest()[:16]


def _read_stamp(cfg: Config) -> dict[str, str]:
    f = cfg.state / ".cairn-source"
    out: dict[str, str] = {}
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            out[k] = v
    return out


def self_install(cfg: Config, dry: bool) -> None:
    if cfg.cairn_home == cfg.state:
        return
    if dry:
        info(f"would copy bin/ lib/ assets/ into {cfg.state}")
        return
    sid = source_id(cfg.cairn_home)
    if not sid.endswith("+dirty") and _read_stamp(cfg).get("id") == sid:
        ok(f"cairn in {cfg.state} (unchanged)")
        return
    cfg.state.mkdir(parents=True, exist_ok=True)
    # bin/lib/assets/tests match bash exactly; ALSO copy the port package so the
    # deployed python entry is self-contained (STATE/port on sys.path). The extra
    # STATE/port/ is a deploy detail, excluded from the equivalence tree diff.
    for sub in ("bin", "lib", "assets", "tests", "port"):
        s = cfg.cairn_home / sub
        if s.is_dir():
            shutil.copytree(s, cfg.state / sub, dirs_exist_ok=True)
    if cfg.logo.is_file():
        shutil.copyfile(cfg.logo, cfg.state / "cairn-logo.txt")
    shutil.rmtree(cfg.state / "lib" / "__pycache__", ignore_errors=True)
    (cfg.state / "bin" / "README.md").unlink(missing_ok=True)
    try:
        os.chmod(cfg.state / "bin" / "cairn", 0o755)
    except OSError:
        pass
    (cfg.state / ".cairn-source").write_text(
        f"source={cfg.cairn_home}\nid={sid}\ninstalled={stamp()}\n", encoding="utf-8")
    ok(f"installed cairn into {cfg.state}")


def link_cairn(cfg: Config, dry: bool) -> None:
    home = Path(os.environ.get("HOME") or Path.home())
    target = cfg.state / "bin" / "cairn"
    dest = home / ".local" / "bin" / "cairn"
    if dry:
        info(f"would link {dest} -> {target}")
        return
    lb = home / ".local" / "bin"
    made = lb.is_dir()
    if not made:
        try:
            lb.mkdir(parents=True, exist_ok=True)
            made = True
        except OSError:
            made = False
    if made:
        try:
            if dest.is_symlink() or dest.exists():
                dest.unlink()
            os.symlink(target, dest)
            ok(f"linked {dest} -> cairn")
        except OSError:
            pass
        if str(lb) not in os.environ.get("PATH", "").split(os.pathsep):
            warn("add ~/.local/bin to PATH to run 'cairn' directly")
    else:
        warn(f"could not link onto PATH — run via {target} or add it to PATH yourself")


def swap_block(cfg: Config, dry: bool, ts_s: str) -> None:
    md = cfg.claude_dir / "CLAUDE.md"
    block = (cfg.assets / "claude-block.md").read_text(encoding="utf-8", errors="replace")
    if dry:
        t = md.read_text(encoding="utf-8", errors="replace") if md.is_file() else ""
        if md.is_file() and BEGIN_MARK in t:
            info("would replace existing cairn block in CLAUDE.md")
        elif md.is_file() and OLD_BEGIN in t:
            info("would replace v1 skill-system block with cairn block")
        else:
            info("would append cairn block to CLAUDE.md")
        return
    if not md.exists():
        md.write_text("", encoding="utf-8")
    text = md.read_text(encoding="utf-8", errors="replace")
    for b, e in ((BEGIN_MARK, END_MARK), (OLD_BEGIN, OLD_END)):
        if b in text and e not in text:
            warn("CLAUDE.md has a managed-block BEGIN marker with no END — looks hand-edited.")
            warn("Leaving it untouched (no swap). Fix the markers, then re-run. Nothing was changed.")
            return
    stripped = strip_block(strip_block(text, OLD_BEGIN, OLD_END), BEGIN_MARK, END_MARK)
    trimmed = trim_trailing_blank(stripped)
    cand = (trimmed + "\n" + block) if trimmed != "" else block
    if cand == text:
        ok("CLAUDE.md block up to date")
        return
    backed_up = text != ""
    if backed_up:
        _backup(md, ts_s)
    md.write_text(cand, encoding="utf-8")
    if md.with_name(md.name + f".bak-{ts_s}").is_file():
        ok(f"CLAUDE.md block swapped (backup: CLAUDE.md.bak-{ts_s})")
    else:
        ok("CLAUDE.md block installed")


def stamp_meta(ctx: Context, dry: bool) -> None:
    cfg = ctx.cfg
    for d in sorted(cfg.skills.glob("*")):
        if not (d / "SKILL.md").is_file():
            continue
        name = d.name
        if (d / ".meta").is_file():
            continue
        created = dir_date(d)
        if dry:
            info(f"would stamp .meta on {name} (created={created})")
            continue
        ctx.lib.run("meta", "init", str(d / ".meta"), f"created={created}", f"last_used={created}")
        if name == "skill-extraction":
            ctx.lib.run("meta", "set", str(d / ".meta"), "provenance", "bundled")


def seed_feedback(cfg: Config, dry: bool) -> None:
    for d in sorted(cfg.skills.glob("*")):
        if not (d / "SKILL.md").is_file():
            continue
        name = d.name
        if name == "skill-extraction" or dry:
            continue
        lr = d / "learnings.md"
        if not lr.is_file():
            lr.write_text(f"# Learnings — {name}\n<!-- YYYY-MM-DD — what happened → what to do differently -->\n", encoding="utf-8")
        us = d / "usage.md"
        if not us.is_file():
            us.write_text(f"# Usage ratings — {name}\n<!-- YYYY-MM-DD | N/5 | task context | helped or hindered -->\n", encoding="utf-8")


def _evals_all_pass(rate: str) -> bool:
    """True when a recorded eval rate is a full pass, e.g. '7/7'."""
    passed, sep, total = rate.partition("/")
    if not sep:
        return False
    try:
        return int(total) > 0 and int(passed) == int(total)
    except ValueError:
        return False


def low_quality_list(ctx: Context) -> str:
    """Skills whose stale `quality` score is still backed by evidence.

    `quality` is written ONCE — the assess pass skips anything already scored and
    nothing recomputes it — so a 1-2 assigned months ago outlives a full rewrite.
    Evidence beats the frozen number: a skill in regular use, or one whose own eval
    set passes completely, is not weak whatever the old assessment said. Without
    this guard `curate --archive-weak` would archive the second most-used skill here
    (36 uses, evals 7/7, still flagged 2/5 from before it was rewritten).
    """
    out = []
    for d in sorted(ctx.cfg.skills.glob("*")):
        if not (d / ".meta").is_file():
            continue
        meta = d / ".meta"
        q = ctx.lib.run("meta", "get", str(meta), "quality").out
        if q not in ("1", "2"):
            continue
        try:
            if int(ctx.lib.run("meta", "get", str(meta), "use_count").out or 0) >= 3:
                continue
        except ValueError:
            pass
        if _evals_all_pass(ctx.lib.run("meta", "get", str(meta), "last_eval_rate").out):
            continue
        out.append(f"{d.name} (quality {q})\n")
    return "".join(out)


def unscored_managed_exists(ctx: Context) -> bool:
    for d in sorted(ctx.cfg.skills.glob("*")):
        if not (d / ".meta").is_file():
            continue
        if d.name == "skill-extraction":
            continue
        if ctx.lib.run("meta", "get", str(d / ".meta"), "provenance").out == "bundled":
            continue
        if ctx.lib.run("meta", "get", str(d / ".meta"), "quality").out == "":
            return True
    return False


def assess_skills(ctx: Context) -> None:
    cfg = ctx.cfg
    n = 0
    for d in sorted(cfg.skills.glob("*")):
        if not (d / "SKILL.md").is_file():
            continue
        name = d.name
        if name == "skill-extraction":
            continue
        if ctx.lib.run("meta", "get", str(d / ".meta"), "provenance").out == "bundled":
            continue
        if ctx.lib.run("meta", "get", str(d / ".meta"), "quality").out != "":
            continue
        q = score_one_skill(cfg, str(d))
        if q:
            ctx.lib.run("meta", "set", str(d / ".meta"), "quality", q)
            n += 1
            ok(f"{name} → quality {q}")
    ok(f"assessed {n} skill(s)")


def enable_hooks(cfg: Config, dry: bool, ts_s: str) -> None:
    settings = cfg.claude_dir / "settings.json"
    if dry:
        info("would add SessionEnd review + UserPromptSubmit suggest + PostToolUse track hooks to settings.json (backed up)")
        return
    cairn_bin = str(cfg.state / "bin" / "cairn")
    logf = str(cfg.logs / "review-hook.log")
    data: object = {}
    if settings.is_file():
        try:
            data = json.loads(settings.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
    changed, data = enable_hooks_transform(data, cairn_bin, logf)
    if changed:
        if settings.is_file():
            _backup(settings, ts_s)
        tmp = settings.with_name(settings.name + f".cairn-tmp.{os.getpid()}")
        tmp.write_text(dumps(data), encoding="utf-8")
        os.replace(tmp, settings)
        ok("hooks installed: SessionEnd review (capture) + UserPromptSubmit suggest (surface at task start) + PostToolUse track (real use_count). Disable: cairn uninstall.")
    else:
        ok("cairn hooks already present (no change)")


def provision(ctx: Context, enable_hooks_flag: int, assess: int, dry: bool) -> None:
    cfg = ctx.cfg
    ts_s = ts()

    hdr("Detect")
    ok("existing setup found — migrating in place" if detect_existing(cfg) else "fresh install")

    hdr("Snapshot")
    if has_git():
        if skills_is_repo(cfg):
            skills_commit(cfg, "cairn: pre-migration snapshot", dry=dry)
            ok("snapshotted skills/ (git)")
        elif dry:
            info(f"would git init {cfg.skills}")
        else:
            cfg.skills.mkdir(parents=True, exist_ok=True)
            if _git(cfg, "init", "-q", "-b", "main").returncode != 0:
                _git(cfg, "init", "-q")
            (cfg.skills / ".gitignore").write_text(".DS_Store\n", encoding="utf-8")
            skills_commit(cfg, "cairn: initial snapshot", dry=dry)
            ok("git-initialised skills/")
    else:
        warn("git not found — skill repo not initialised (everything else proceeds)")

    hdr("Relocate state")
    relocate_state(cfg, dry)

    hdr("Directories")
    if not dry:
        for d in (cfg.skills, cfg.memories, cfg.commands, cfg.templates / "skill-template" / "evals",
                  cfg.harvest, cfg.archive, cfg.logs):
            d.mkdir(parents=True, exist_ok=True)
    ok(str(cfg.claude_dir) + "/{skills,memories,commands,templates,cairn/{harvest,skill-archive,logs}}")

    hdr("Dispatcher")
    self_install(cfg, dry)
    link_cairn(cfg, dry)

    hdr("Commands")
    for f in sorted(glob.glob(str(cfg.assets / "commands" / "*.md"))):
        base = os.path.basename(f)
        put(Path(f), cfg.commands / base, f"commands/{base}", dry, ts_s)

    hdr("Template + meta-skill")
    tpl_root = cfg.assets / "templates" / "skill-template"
    # Pure-Python, no coreutils/`find` dependency (works natively on Windows). Sorted
    # (LC_ALL=C byte order) to match bash's `find | LC_ALL=C sort` oracle byte-for-byte.
    for rel in sorted(p.relative_to(tpl_root).as_posix()
                      for p in tpl_root.rglob("*") if p.is_file()):
        put(tpl_root / rel, cfg.templates / "skill-template" / rel, f"templates/skill-template/{rel}", dry, ts_s)
    put(cfg.assets / "skills" / "skill-extraction" / "SKILL.md",
        cfg.skills / "skill-extraction" / "SKILL.md", "skills/skill-extraction/SKILL.md", dry, ts_s)

    hdr("Memory")
    if dry:
        info(f"would init memories/USER.md ({cfg.user_cap}) + MEMORY.md ({cfg.memory_cap}) if absent")
    else:
        cfg.memories.mkdir(parents=True, exist_ok=True)
        ctx.lib.run("memory", "init", str(cfg.user_md), str(cfg.user_cap), "USER model (cairn)")
        ok("memories/USER.md")
        ctx.lib.run("memory", "init", str(cfg.memory_md), str(cfg.memory_cap), "Agent notes (cairn)")
        ok("memories/MEMORY.md")

    hdr("CLAUDE.md")
    swap_block(cfg, dry, ts_s)

    hdr("Skill metadata")
    stamp_meta(ctx, dry)
    seed_feedback(cfg, dry)
    if not dry:
        ok("every skill stamped with .meta")

    if assess == 1 and not dry:
        hdr("Assess (quality scoring)")
        if shutil.which("claude"):
            assess_skills(ctx)
        else:
            warn("claude not on PATH — skipping assessment (re-run: cairn migrate)")
    elif assess == 1:
        info("would assess each skill's quality (1-5) into .meta")

    if enable_hooks_flag == 1:
        hdr("Hooks")
        enable_hooks(cfg, dry, ts_s)

    hdr("Commit")
    skills_commit(cfg, "cairn: migrated to 2.0", dry=dry)
    if not dry and skills_is_repo(cfg):
        short = _git(cfg, "rev-parse", "--short", "HEAD").stdout.strip()
        ok(f"committed skills/ ({short})")

    hdr("Done")
    if dry:
        info("dry run — nothing changed")
        return
    ok(f"cairn {cfg.version} ready")
    info("next: start a NEW Claude Code session, then try  cairn status  ·  /skill-new demo")
    lowq = low_quality_list(ctx)
    if lowq:
        warn("low-quality skills flagged (improve / pin / merge):")
        for line in lowq.rstrip("\n").split("\n"):
            print("      " + line)
    if assess == 0 and unscored_managed_exists(ctx):
        info("tip: 'cairn migrate' also scores your existing skills' quality (model calls)")
