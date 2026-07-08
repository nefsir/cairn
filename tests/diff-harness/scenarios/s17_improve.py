NAME = "improve (picker / dry / single / real / skip-after)"

# improve has no install-based scenario (gap); this isolated golden master seeds one
# eligible skill (>=5 eval cases, fresh signal, no .last-improve) directly and drives
# the picker, dry-run, single-skill, a real run (claude shim), and the skip-after-improve.

_SKILL = """---
name: widget-improve-x
description: Improve widget polishing. Use when a widget needs deburring or a gloss pass.
---
Body.
"""
_CASES = "".join(f"## Case {i}\n- input: widget {i}\n- pass: polished\n" for i in range(1, 6))
_META = ("provenance=managed\npinned=false\nstate=active\ncreated=2020-01-01\n"
         "last_used=2020-01-01\nlast_patched=\nuse_count=1\nquality=3\n")


def run(ctx):
    ctx.seed("skills/widget-improve-x/SKILL.md", _SKILL)
    ctx.seed("skills/widget-improve-x/evals/cases.md", _CASES)
    ctx.seed("skills/widget-improve-x/learnings.md", "# Learnings\n- a fresh signal line\n")
    ctx.seed("skills/widget-improve-x/usage.md", "# Usage ratings\n")
    ctx.seed("skills/widget-improve-x/.meta", _META)
    # git-init the skills repo so the real run's skills_commit has somewhere to commit
    ctx.run("install")                       # delegates to bash; sets up state + git
    ctx.run("improve", "--dry-run")          # picker -> "would improve: widget-improve-x "
    ctx.run("improve", "widget-improve-x", "--dry-run")
    ctx.run("improve", "widget-improve-x")   # real: claude shim rc0 -> stamp + commit
    ctx.run("improve", "--dry-run")          # now .last-improve is newer -> nothing to improve
