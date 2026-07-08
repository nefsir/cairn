"""cairn lint [name] — validate skill frontmatter (delegates to lib/validate.py).

Ports bash cmd_lint exactly, incl. bash's ``$(…)`` trailing-newline stripping: the
lib's issue output ends in ``\\n``, which command substitution drops before the
empty-check and the 6-space re-indent.
"""
from __future__ import annotations

from ..context import Context
from ..helpers import need_python, resolve_skill_dir
from ..out import die, ok, warn


def _indent6(issues: str) -> None:
    # bash: printf '%s\n' "$out" | sed 's/^/      /'  (out already had trailing \n stripped)
    for line in issues.split("\n"):
        print("      " + line)


def cmd_lint(ctx: Context, args: list[str]) -> int:
    need_python()
    cfg = ctx.cfg
    if not cfg.skills.is_dir():
        die(f"no skills dir at {cfg.skills}")

    if args:
        name = args[0]
        d = resolve_skill_dir(cfg, name)
        if d is None:
            die(f"no skill '{name}'")
        out = ctx.lib.run("validate", "skill", d).out.rstrip("\n")   # $(…) strips trailing \n
        if out == "":
            ok(f"{name}: frontmatter valid")
            return 0
        warn(f"{name}: invalid frontmatter:")
        _indent6(out)
        return 1

    out = ctx.lib.run("validate", "all", str(cfg.skills)).out.rstrip("\n")
    if out == "":
        ok("all skills: frontmatter valid (name, description ≤1024, body)")
        return 0
    warn("frontmatter issues (name / description ≤1024 / body):")
    _indent6(out)
    return 1
