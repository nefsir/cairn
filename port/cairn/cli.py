"""Dispatcher — argv routing with bash's failure-isolation contract.

Bash runs under ``set -uo pipefail`` WITHOUT ``-e``: a subcommand's failure maps to an
exit code but never aborts the process. Here every routed handler runs inside
:func:`main`'s try/except: a :class:`CairnDie` becomes a stderr ``ERROR:`` line + its
exit code; nothing leaks a traceback in place of bash's clean error.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .config import Config, load_config
from .context import Context
from .out import CairnDie, die, print_die

# Every real subcommand name (matches the bash router's case arms).
KNOWN_COMMANDS = frozenset({
    "memory", "pin", "unpin", "provenance", "status", "lint", "suggest", "track",
    "install", "migrate", "uninstall", "review", "curate", "improve", "maintain",
    "schedule", "mine", "distill", "refine", "test",
})


def banner(cfg: Config) -> None:
    import sys
    if cfg.logo.is_file():
        sys.stdout.write(cfg.logo.read_text(encoding="utf-8"))
    else:
        sys.stdout.write("\n  cairn — self-improving skills & memory for Claude Code\n")
    c_dim, c_0 = _dim_reset()
    sys.stdout.write(
        f"\n  {c_dim}v{cfg.version}{c_0} · run 'cairn --help' for the subcommand map\n\n"
    )


def show_help(cfg: Config) -> None:
    b, dim, z = _b_dim_reset()
    print(_HELP.format(b=b, dim=dim, z=z, ver=cfg.version, cd=cfg.claude_dir))


def _handlers() -> dict[str, Callable[[Context, list[str]], int]]:
    """Ported command handlers. Grows one migration unit at a time."""
    from .commands.backfill import cmd_distill, cmd_mine, cmd_refine
    from .commands.curate import cmd_curate
    from .commands.improve import cmd_improve
    from .commands.lifecycle import cmd_install, cmd_migrate, cmd_uninstall
    from .commands.lint import cmd_lint
    from .commands.memory import cmd_memory
    from .commands.provenance import cmd_pin, cmd_provenance, cmd_unpin
    from .commands.review import cmd_review
    from .commands.schedule import cmd_maintain, cmd_schedule
    from .commands.status import cmd_status
    from .commands.suggest import cmd_suggest
    from .commands.testcmd import cmd_test
    from .commands.track import cmd_track
    return {"lint": cmd_lint, "memory": cmd_memory, "status": cmd_status,
            "suggest": cmd_suggest, "track": cmd_track,
            "pin": cmd_pin, "unpin": cmd_unpin, "provenance": cmd_provenance,
            "review": cmd_review, "uninstall": cmd_uninstall,
            "install": cmd_install, "migrate": cmd_migrate, "curate": cmd_curate,
            "mine": cmd_mine, "distill": cmd_distill, "refine": cmd_refine,
            "schedule": cmd_schedule, "maintain": cmd_maintain, "test": cmd_test,
            "improve": cmd_improve}


def main(argv: list[str], cairn_home: Path) -> int:
    cfg = load_config(cairn_home)
    sub = argv[1] if len(argv) > 1 else ""
    rest = argv[2:]
    try:
        if sub in ("", "banner"):
            banner(cfg)
            return 0
        if sub in ("-h", "--help", "help"):
            show_help(cfg)
            return 0
        if sub in ("-V", "--version", "version"):
            print(f"cairn {cfg.version}")
            return 0
        handler = _handlers().get(sub)
        if handler is not None:
            return handler(Context.build(cfg), rest)
        if sub in KNOWN_COMMANDS:
            die(f"'{sub}' is not available in this build")
        die(f"unknown command: {sub} (try 'cairn --help')")
    except CairnDie as e:
        print_die(e.message)
        return e.code
    return 0


# --- color helpers (gated on stdout tty / NO_COLOR, like bash) ----------------
def _ansi() -> dict[str, str]:
    import os
    import sys
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return {"b": "\033[1m", "dim": "\033[2m", "0": "\033[0m"}
    return {"b": "", "dim": "", "0": ""}


def _dim_reset() -> tuple[str, str]:
    a = _ansi()
    return a["dim"], a["0"]


def _b_dim_reset() -> tuple[str, str, str]:
    a = _ansi()
    return a["b"], a["dim"], a["0"]


# The help body, byte-identical to bash's show_help heredoc (color markers + the
# $CAIRN_VERSION / $CLAUDE_DIR interpolations become format fields).
_HELP = """\
{b}cairn{z} — self-improving skills & memory for Claude Code  (v{ver})

{b}Backfill (Layer A, one-time){z}
  cairn mine [ROOT] [opts]     mine past transcripts into skill candidates
  cairn distill [opts]         cluster candidates -> synthesized proposals
  cairn refine [opts]          generalize + reusability-score the proposals

{b}The loop (Layer B, ongoing){z}
  cairn review [TRANSCRIPT]    post-session review: patch/create skills + memory
  cairn curate                 consolidation + lifecycle report (read-only)
  cairn curate --merge [--yes]        auto-merge overlapping skills into umbrellas
  cairn curate --archive-weak [--assess] [--yes]   archive low-quality/low-use skills
  cairn curate --apply-lifecycle      apply stale/archive transitions
  cairn improve                improvement pass (eval -> fix -> re-eval)
  cairn maintain               run the nightly job now (improve + inactivity-archive)
  cairn schedule [HH:MM]       run maintain nightly (launchd/cron); --off to remove

{b}Store & memory{z}
  cairn status                 health dashboard
  cairn lint [name]            validate skill frontmatter (name, description ≤1024)
  cairn suggest "<text>"       show the skills matching a prompt (the use-side hook)
  cairn memory [user|agent ...] read / add / replace / remove / trim memory
  cairn pin <name>             freeze a skill from auto-curation
  cairn unpin <name>
  cairn provenance --list      show provenance / pinned / state / quality
  cairn provenance <name> <managed|bundled>

{b}Lifecycle{z}
  cairn install [--enable-hooks]   fresh install (or migrate if a setup exists)
  cairn migrate [--dry-run] [--no-assess]
  cairn uninstall
  cairn test                   run the test suite (static + unit + integration)
  cairn --version | --help

Everything lives under {dim}{cd}{z} as plain files in git."""
