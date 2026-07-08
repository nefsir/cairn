NAME = "pin-unpin-provenance"

# Golden master for the curation-metadata surface: `cairn pin`, `unpin`, and
# `provenance` (both the mutating <name> <managed|bundled> form and the read-only
# --list / no-arg listing). Exercises every flag, the .meta mutations, the
# whole-tree skills git commits each mutation produces, the exact --list column
# format, an idempotent no-op set (which must NOT create a second commit), the
# "(none)" row for a .meta-less skill, and every die path.
#
# Determinism notes:
#   * All seeded .meta files use ABSOLUTE dates so their bytes are invariant to
#     when the harness runs; the normalizer collapses dates to <DATE> anyway.
#   * py meta init never clobbers an existing .meta, so the dates I seed survive
#     `install` untouched (install only stamps skills that lack a .meta).
#   * Skill dir names are ASCII lowercase/hyphen slugs, so the C-locale glob sort
#     used by `provenance --list` is fully determined: alpha < beta < gamma.

_ALPHA_SKILL = """---
name: alpha-skill
description: Alpha fixture skill exercising pin/unpin/provenance mutations.
---
Body of alpha-skill.
"""

_BETA_SKILL = """---
name: beta-skill
description: Beta fixture skill starting life as bundled, flipped to managed.
---
Body of beta-skill.
"""

_GAMMA_SKILL = """---
name: gamma-skill
description: Gamma fixture with no .meta, to cover the (none) provenance row.
---
Body of gamma-skill.
"""

# Canonical key order (see lib/meta.py CANON), absolute dates.
_ALPHA_META = (
    "provenance=managed\n"
    "pinned=false\n"
    "state=active\n"
    "created=2020-01-01\n"
    "last_used=2020-06-01\n"
    "last_patched=\n"
    "use_count=7\n"
    "quality=4\n"
)

_BETA_META = (
    "provenance=bundled\n"
    "pinned=true\n"
    "state=active\n"
    "created=2021-03-03\n"
    "last_used=2021-09-09\n"
    "last_patched=\n"
    "use_count=2\n"
    "quality=5\n"
)


def run(ctx):
    # --- seed two skills WITH absolute-dated .meta BEFORE install so install's
    #     git-init snapshots them and stamp_meta leaves their dates alone. ---
    ctx.seed("skills/alpha-skill/SKILL.md", _ALPHA_SKILL)
    ctx.seed("skills/alpha-skill/.meta", _ALPHA_META)
    ctx.seed("skills/beta-skill/SKILL.md", _BETA_SKILL)
    ctx.seed("skills/beta-skill/.meta", _BETA_META)

    # install: git-inits skills/, stamps skill-extraction, commits the tree.
    ctx.run("install")

    # --- baseline listing: header + column format, both fixtures present.
    #     alpha = managed/false, beta = bundled/true. skill-extraction is skipped.
    ctx.run("provenance", "--list")

    # --- pin: pinned false -> true, one whole-tree commit.
    ctx.run("pin", "alpha-skill")
    # idempotent re-pin: value already true -> .meta byte-identical -> nothing
    # staged -> skills_commit makes NO second commit (git log proves it).
    ctx.run("pin", "alpha-skill")

    ctx.run("provenance", "--list")   # alpha now pinned=true

    # --- unpin: pinned true -> false, another commit.
    ctx.run("unpin", "alpha-skill")

    # --- provenance mutations: managed -> bundled and bundled -> managed.
    ctx.run("provenance", "alpha-skill", "bundled")
    ctx.run("provenance", "beta-skill", "managed")

    # no-arg form must behave exactly like --list; then the explicit flag again.
    ctx.run("provenance")
    ctx.run("provenance", "--list")

    # --- die paths (rc=1, stderr) -------------------------------------------
    ctx.run("pin")                                   # usage: cairn pin <name>
    ctx.run("unpin")                                 # usage: cairn unpin <name>
    ctx.run("pin", "ghost-skill")                    # no skill '...' in <dir>
    ctx.run("provenance", "ghost-skill", "managed")  # no skill '...'
    ctx.run("provenance", "alpha-skill", "sideways") # must be managed|bundled
    ctx.run("provenance", "alpha-skill")             # usage: provenance <name> <..>

    # --- (none) row: a skill with SKILL.md but no .meta, added AFTER install so
    #     stamp_meta never touched it. Sorts last (gamma > alpha,beta).
    ctx.seed("skills/gamma-skill/SKILL.md", _GAMMA_SKILL)
    ctx.run("provenance", "--list")
