import json

NAME = "uninstall-preservation-and-migrate"

# Golden master for the LIFECYCLE surface the other scenarios never reach:
# cmd_uninstall (bin/cairn:712) and cmd_migrate (bin/cairn:698 -> provision).
# It drives, in one $CLAUDE_DIR, every branch the gap calls for and asserts each
# step's rc + stdout + stderr AND the resulting tree/git/shim state (all diffed by
# the harness, oracle vs candidate, byte-for-byte after normalization):
#
#   PART A — uninstall PRESERVATION + FOREIGN-hook survival + second-uninstall no-op
#     * install --enable-hooks over a pre-seeded settings.json that already holds a
#       NON-cairn hook on SessionEnd (the event cairn also writes) AND a NON-cairn
#       hook on PreToolUse (an event cairn never touches) + a top-level "env" key.
#     * uninstall: the managed CLAUDE.md block is stripped, cairn's three hooks
#       (SessionEnd review / UserPromptSubmit suggest / PostToolUse track) are pruned
#       from settings.json, but BOTH foreign hooks + the env key survive (settings is
#       therefore non-empty and is NOT dropped). The user skill, its .meta, both
#       memory files, the skills git repo and $CLAUDE_DIR/cairn ($STATE) are LEFT
#       INTACT — proven by their bytes still being in the final tree.
#     * a SECOND uninstall is a no-op: no managed block remains (nothing to strip,
#       no backup), settings.json no longer mentions cairn (branch skipped), the
#       schedule was never set ("no maintenance schedule was set").
#
#   PART B — empty-{} settings.json is DROPPED
#     * re-seed settings.json to a bare "{}" (no foreign hook this time), reinstall
#       --enable-hooks so it holds ONLY cairn's hooks, then uninstall: pruning the
#       cairn hooks empties the object to {}, which cairn deletes outright (the .bak
#       preserves the prior state) — so settings.json is ABSENT from the final tree.
#
#   PART C — migrate off a v1 ("skill-system") managed block
#     * seed a CLAUDE.md carrying the OLD v1 marker block (bin/cairn:329 OLD_BEGIN/
#       OLD_END) wrapped in the user's own prose.
#     * migrate --dry-run: DRY=1 describes the v1->cairn swap and every would-be
#       action but changes NOTHING on disk (no backup, no new files).
#     * migrate --no-assess: the real swap (v1 block out, cairn block in), dirs +
#       commands + template + meta-skill recreated, skills committed — with assess
#       skipped, so NO `claude` model call happens.
#     * migrate (bare): assess=1 now scores the one unscored managed user skill via
#       the deterministic `claude` shim (quality "" -> 3); the CLAUDE.md block is
#       already current so it converges with no further backup.
#
# Determinism / fixtures:
#   * All seeded .meta + memory fixtures use ABSOLUTE dates (never today-relative),
#     so their bytes are invariant to when the harness runs; the normalizer collapses
#     any date to <DATE> regardless.
#   * The user skill's .meta is seeded with quality="" so the bare `migrate` assess
#     pass has exactly one skill to score -> exactly one deterministic shim call
#     (CAIRN_SHIM_CLAUDE_OUT defaults to "3"); skill-extraction is bundled (skipped).
#   * py memory init / py meta init never clobber an existing file, so install/migrate
#     leave the seeded memory + user-skill .meta byte-untouched.
#   * All skill/dir names are ASCII lowercase/hyphen slugs (C-locale glob == codepoint
#     sort).
#
# KNOWN NON-DETERMINISM (documented; NOT worked around by dropping a step):
#   cmd_uninstall and swap_block back up the file they are about to rewrite as
#   "<file>.bak-$CAIRN_TS" where CAIRN_TS="$(ts)" == `date +%Y%m%d-%H%M%S` reads the
#   REAL wall clock (the harness pins GIT_*_DATE but not `date`). The normalizer
#   rewrites ".bak-<TS>" inside file CONTENT and stdout, but compare() sets the
#   tree-PATH keys RAW, so the oracle and candidate runs — which execute seconds
#   apart — emit backup files whose NAMES differ (CLAUDE.md.bak-...530 vs ...531) and
#   diverge on "TREE PATHS differ". This is the SOLE divergence this scenario carries;
#   every OTHER observable (each step rc/stdout/stderr, the skills git log/status, the
#   shim logs, and every non-backup file) is byte-identical. It is reported as a real
#   finding rather than hidden by dropping the removal/swap steps — those steps ARE
#   the coverage this gap exists to add.
#
#   Second-order: to keep the STDOUT deterministic this scenario deliberately seeds a
#   NON-empty CLAUDE.md (user prose) so every swap_block takes the real-backup path
#   ("block swapped") every time. If CLAUDE.md were empty at an install, swap_block
#   makes no backup yet decides its "swapped vs installed" line with
#   `[ -f "$md.bak-$CAIRN_TS" ]` — testing for a file named with the CURRENT second —
#   so a leftover CLAUDE.md.bak-<sameTS> from an earlier step in the same wall-clock
#   second flips the message (a false "swapped (backup: …)" citing a backup it never
#   made). That is a latent cairn correctness bug surfaced while building this
#   scenario; the seeded prose keeps it out of the observed stdout here.

_USER_SKILL = """---
name: widget-polish-routine
description: Polish and deburr machined widgets before final inspection. Use when a widget shows tooling marks, when the surface finish fails the gloss gate, or the user says "widget polish", "deburr pass", "finish the widget".
keywords: widget, polish, deburr, finish, inspection
---
Body of widget-polish-routine.
"""

# Canonical key order (lib/meta.py CANON), absolute dates, quality left BLANK so the
# bare-migrate assess pass has one skill to score.
_USER_META = (
    "provenance=managed\n"
    "pinned=false\n"
    "state=active\n"
    "created=2020-02-02\n"
    "last_used=2020-08-08\n"
    "last_patched=\n"
    "use_count=3\n"
    "quality=\n"
)

_USER_MEM = (
    "# USER model (cairn)\n"
    "<!-- seeded pre-install; uninstall must NOT touch this -->\n"
    "§ prefers terse answers and absolute-dated fixtures\n"
)

_AGENT_MEM = (
    "# Agent notes (cairn)\n"
    "<!-- seeded pre-install; uninstall must NOT touch this -->\n"
    "§ sandbox pins LC_ALL=C and TZ=UTC\n"
)

# A CLAUDE.md that ALREADY holds the user's own prose (no managed markers). install
# appends the cairn block BELOW it; uninstall strips ONLY the block and MUST leave
# this prose intact. Keeping it non-empty also pins swap_block onto the real-backup
# path so its "block swapped" line is deterministic (see the header note).
_USER_CLAUDE_MD = (
    "# My global Claude instructions\n"
    "\n"
    "Prefer metric units and absolute dates.\n"
    "Keep this prose exactly; only the managed block is cairn's to add or remove.\n"
)

# settings.json carrying two NON-cairn hooks + an env key. The SessionEnd foreign
# hook shares an event with cairn's review hook (proves per-hook, not per-event,
# pruning); the PreToolUse foreign hook sits on an event cairn never iterates (proves
# whole-event preservation); "env" proves non-hook keys are untouched. No cairn
# substring anywhere, so is_cairn() never matches these.
_FOREIGN_SETTINGS = json.dumps({
    "hooks": {
        "SessionEnd": [
            {"hooks": [{"type": "command", "command": "/opt/acme/audit-logger --on-session-end"}]}
        ],
        "PreToolUse": [
            {"matcher": "Bash",
             "hooks": [{"type": "command", "command": "/opt/acme/bash-guard.sh"}]}
        ],
    },
    "env": {"ACME_MODE": "on"},
}, indent=2) + "\n"

# A v1 ("skill-system") managed CLAUDE.md: OLD_BEGIN/OLD_END markers (bin/cairn:329)
# on their own lines, wrapped in the user's own prose that migrate MUST preserve.
_OLD_BEGIN = "<!-- BEGIN skill-system (managed by claude-skill-system installer) -->"
_OLD_END = "<!-- END skill-system -->"
_V1_CLAUDE_MD = (
    "# My personal Claude instructions\n"
    "\n"
    "Always answer in metric units.\n"
    "\n"
    + _OLD_BEGIN + "\n"
    "## Legacy skill-system\n"
    "This block was written by the old claude-skill-system installer.\n"
    + _OLD_END + "\n"
    "\n"
    "Signing off — keep my prose above and below the managed block intact.\n"
)


def run(ctx):
    # --- fixtures seeded BEFORE the first install so install git-inits/commits the
    #     user skill and stamp_meta / memory-init leave the seeded bytes alone. -----
    ctx.seed("skills/widget-polish-routine/SKILL.md", _USER_SKILL)
    ctx.seed("skills/widget-polish-routine/.meta", _USER_META)
    ctx.seed("memories/USER.md", _USER_MEM)
    ctx.seed("memories/MEMORY.md", _AGENT_MEM)
    ctx.seed("CLAUDE.md", _USER_CLAUDE_MD)
    ctx.seed("settings.json", _FOREIGN_SETTINGS)

    # =====================================================================
    # PART A — install --enable-hooks, then uninstall (preserve everything but
    #          the managed block + cairn's own hooks), then a no-op second run.
    # =====================================================================
    # cairn's three hooks are upserted ALONGSIDE the foreign SessionEnd hook and the
    # untouched PreToolUse hook (settings.json is backed up + rewritten).
    ctx.run("install", "--enable-hooks")

    # uninstall #1: strips the managed CLAUDE.md block, prunes ONLY cairn's hooks
    # (foreign SessionEnd + PreToolUse + env survive -> settings stays, not dropped),
    # removes commands/template/skill-extraction, and LEAVES the user skill, its
    # .meta, both memory files, the skills git and $STATE untouched.
    ctx.run("uninstall")

    # uninstall #2: nothing left to strip (no managed block -> no backup), settings no
    # longer mentions cairn (branch skipped), no schedule was ever set. Pure no-op.
    ctx.run("uninstall")

    # =====================================================================
    # PART B — empty-{} settings.json is dropped.
    # =====================================================================
    # Clear the foreign hook: now settings holds ONLY what cairn adds, so pruning it
    # on uninstall empties the object to {} and cairn deletes the file.
    ctx.seed("settings.json", "{}\n")
    ctx.run("install", "--enable-hooks")   # settings.json -> only cairn's hooks
    ctx.run("uninstall")                   # prune -> {} -> settings.json removed

    # =====================================================================
    # PART C — migrate off a v1 ("skill-system") managed block.
    # =====================================================================
    # After Part B the managed block was stripped (CLAUDE.md is back to the user's
    # prose only); overwrite it with a realistic v1 CLAUDE.md so migrate exercises the
    # OLD-block swap path.
    ctx.seed("CLAUDE.md", _V1_CLAUDE_MD)

    # migrate --dry-run: describes the v1->cairn swap + every would-be action, writes
    # NOTHING (DRY=1) -> no backup, no recreated files, no commit, no model call.
    ctx.run("migrate", "--dry-run")

    # migrate --no-assess: the REAL migration — v1 block out / cairn block in
    # (CLAUDE.md backed up), dirs + commands + template + meta-skill recreated, skills
    # committed. assess is skipped -> NO `claude` shim call in this step.
    ctx.run("migrate", "--no-assess")

    # migrate (bare): assess=1 scores the one unscored managed skill via the
    # deterministic `claude` shim (widget-polish-routine quality "" -> "3");
    # skill-extraction is bundled (skipped). The CLAUDE.md block is already current,
    # so swap_block converges with no further backup.
    ctx.run("migrate")
