NAME = "memory-command-surface"

# Golden master for the bounded-memory command layer (cmd_memory in bin/cairn ->
# lib/memory.py). Exercises the WHOLE surface and asserts, on every step, the exit
# code + stdout + stderr AND the resulting memories/USER.md / MEMORY.md bytes (the
# harness diffs the full $CLAUDE_DIR tree automatically):
#
#   * list        -> `cairn memory` (no which): both files with header + char count
#   * read        -> `cairn memory user` / `... agent` (action defaults to read)
#   * add         -> multi-word text JOINED via the shell `$*` expansion
#   * replace     -> multi-word replacement text, also `$*`-joined; unique-match path
#   * remove      -> uses ONLY `$1` (extra words ignored) — the $*-vs-$1 distinction
#   * trim        -> drops oldest entries until <= cap, reports the count
#   * aliases     -> `user`, `agent`, and the `memory` alias all routed correctly
#   * over-cap    -> seed a near-cap USER.md, add to overflow -> rc 1 + REJECTED msg
#   * unsafe unicode -> a bidi-override char (U+202E) in an entry -> rc 1 + REJECTED
#   * die paths   -> bad `which`, unknown action, missing args, no-match/ambiguous
#
# Determinism notes:
#   * No entry text contains a date/count, so nothing depends on when the harness
#     runs; the seeded near-cap and multi-entry fixtures are byte-fixed.
#   * The $*-join is proven by passing three SEPARATE argv words to add/replace and
#     observing one joined entry. The $1-only of remove is proven by the fixture
#     "uses zsh on macOS" + `remove zsh macOS`: a $*-based impl would search for the
#     substring "zsh macOS" (absent -> no match -> rc 1), so the two impls diverge
#     here and the golden master pins the correct ($1-only) behavior.
#   * over-cap uses a seeded near-cap USER.md (1372/1375 chars) so a fixed add lands
#     at exactly 1423 chars; trim overrides CAIRN_MEMORY_CAP=200 for that one step so
#     a small fixed multi-entry fixture (293 chars) deterministically drops 2 oldest.
#   * The unsafe char is written as the escape "‮" so the fixture stays ASCII in
#     the repo; subprocess re-encodes it UTF-8 and cairn's LC_ALL=C python (UTF-8
#     mode) decodes it back to U+202E, category Cf -> rejected.

# Near-cap USER.md fixture: header + one big entry = 1372 chars (cap is 1375).
_NEAR_CAP_USER = (
    "# USER model (cairn)\n"
    "<!-- near cap -->\n"
    "§ " + ("a" * 1330) + "\n"
)

# Multi-entry MEMORY.md fixture (293 chars): four oldest->newest entries so a small
# cap forces trim to drop the two oldest and keep charlie + delta.
_TRIM_MEMORY = (
    "# Agent notes (cairn)\n"
    "<!-- trim demo -->\n"
    "§ first oldest note about the sandbox environment alpha padding\n"
    "§ second note bravo covering conventions and quirks here padding\n"
    "§ third note charlie about tool behavior and defaults padding\n"
    "§ fourth newest note delta most recent addition here padding\n"
)


def run(ctx):
    # install: creates memories/USER.md + MEMORY.md (empty, header only), the skills
    # git, settings, etc. Memory ops never commit, so the skills git stays at this
    # install commit for the whole scenario.
    ctx.run("install")

    # --- read / list on freshly-initialized, empty files ---------------------
    ctx.run("memory")          # list: both files, "== NAME (chars/cap) ==" + header
    ctx.run("memory", "user")  # read (default action), USER.md empty
    ctx.run("memory", "agent") # read (default action) via the agent alias, empty

    # --- add: multi-word text joined by `$*` -> one entry --------------------
    ctx.run("memory", "user", "add", "prefers", "concise", "answers")
    ctx.run("memory", "agent", "add", "uses", "zsh", "on", "macOS")   # agent alias
    ctx.run("memory", "memory", "add", "TZ", "set", "to", "UTC", "always")  # memory alias

    # --- replace: unique match "concise", multi-word replacement (`$*` join) --
    ctx.run("memory", "user", "replace", "concise", "prefers", "terse", "one-liners")

    # --- remove: `$1`-only. Fixture is "uses zsh on macOS"; args are "zsh macOS".
    #     Only $1 ("zsh") is used as the substring -> unique match -> removed. A
    #     $*-join impl would look for "zsh macOS" (absent) and fail: this pins $1.
    ctx.run("memory", "agent", "remove", "zsh", "macOS")

    # --- second USER entry to set up the ambiguous-match branch ---------------
    ctx.run("memory", "user", "add", "prefers", "dark", "mode", "always")

    # --- replace failure paths (py rc 2 -> die "replace failed", rc 1) --------
    # ambiguous: "prefers" now matches two entries
    ctx.run("memory", "user", "replace", "prefers", "adjusted", "preference", "text")
    # no match
    ctx.run("memory", "user", "replace", "nomatchstr", "whatever", "text")
    # remove no match (py rc 2 -> die "remove failed", rc 1)
    ctx.run("memory", "user", "remove", "nomatchstr")

    # --- read / list on the populated files ----------------------------------
    ctx.run("memory")          # list, now populated
    ctx.run("memory", "user")  # read, two entries

    # --- unsafe-unicode reject: U+202E (RIGHT-TO-LEFT OVERRIDE, category Cf) ---
    # py rc 4 -> die, rc 1. Acts on the current USER.md; add is rejected (no write).
    ctx.run("memory", "user", "add", "bad‮text")

    # --- over-cap reject: seed a near-cap USER.md, then add to overflow --------
    ctx.seed("memories/USER.md", _NEAR_CAP_USER)
    # Fixed words so the rendered result is exactly 1423 chars > cap 1375 -> rc 1.
    ctx.run("memory", "user", "add",
            "this", "entry", "should", "push", "it", "over", "the", "cap", "limit", "now")

    # --- trim: seed a multi-entry MEMORY.md, cap overridden small for this step
    ctx.seed("memories/MEMORY.md", _TRIM_MEMORY)
    ctx.run("memory", "agent", "trim", env={"CAIRN_MEMORY_CAP": "200"})

    # --- die paths -----------------------------------------------------------
    ctx.run("memory", "bogus")                      # which must be user|agent|memory
    ctx.run("memory", "user", "frobnicate")         # unknown action
    ctx.run("memory", "user", "add")                # add needs text
    ctx.run("memory", "user", "replace", "onlyone") # replace needs substr + text
    ctx.run("memory", "user", "remove")             # remove needs substr
