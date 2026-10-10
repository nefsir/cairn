DIVERGED = "review pipeline v2 (queue + detached worker); covered by tests/run-tests.sh"

import json

NAME = "suggest-track-surface"

# Golden master for the USE-side pair: `cairn suggest` (surface matching skills at
# task start / mid-task) and `cairn track` (real activation telemetry). Exercises
# every mode and gate:
#   suggest  — manual STRONG match, the warm-but-no-match ROSTER safety net, a
#              below-floor warm prompt (silent), off-topic chatter (silent), and
#              CAIRN_SUGGEST_ROSTER=0 disabling the roster.
#   suggest --hook — the UserPromptSubmit path: prompt arrives as JSON on stdin
#              ({"prompt":"..."}); strong, roster, empty-prompt and malformed-JSON.
#   suggest --tick — the PostToolUse re-surface: reads session_id + transcript_path
#              from JSON, last-user text from the transcript fixture, and only
#              emits every Nth call (CAIRN_SUGGEST_TICK). Covers the non-numeric /
#              zero / missing-transcript guards and the modulo gate (silent on
#              call 1 of 2, additionalContext JSON on call 2) + its counter file.
#   track --hook — a Skill tool_input bumps use_count + last_used (plain name AND
#              the plugin:skill split form); a Bash tool_input, an unknown skill
#              and empty stdin are all ignored; the no-flag form warns.
#
# What this pins (the harness diffs it all, oracle vs candidate, byte-for-byte):
#   * STDOUT PURITY / no @@ROSTER@@ leak — the roster steps prove the internal
#     @@ROSTER@@ sentinel is rewritten into a human nudge and never reaches stdout;
#     a port that leaked it would diverge here. Silent steps must stay byte-empty.
#   * .meta use_count — flywheel (plain) and barnacle (plugin form) go 0 -> 1 with
#     last_used stamped to today; lantern is the CONTROL that stays use_count=0,
#     proving the Bash / unknown / empty-stdin calls bump nothing.
#   * the tick counter file cairn/.suggest-tick-<sid> (content = call count).
#
# Determinism notes:
#   * All seeded .meta use ABSOLUTE dates; meta.py init never clobbers an existing
#     .meta, so install's stamp_meta leaves them alone. track stamps last_used with
#     today() -> both dates collapse to <DATE> under the normalizer.
#   * Skill dir names are ASCII lowercase/hyphen slugs -> C-locale glob + idf are
#     fully determined (barnacle < flywheel < lantern).
#   * The transcript fixture lives under $HOME (NOT $CLAUDE_DIR), so it is not part
#     of the snapshot; its absolute path only ever travels through stdin (never an
#     observable), so the differing tmp home cannot leak into any diff.
#   * suggest is READ-ONLY (never writes .meta); the only telemetry writer is track,
#     so the use_count assertions are unambiguous regardless of step order.

_FLYWHEEL = """---
name: flywheel-torque-calibration
description: Calibrate the flywheel torque governor on a spindle rig. Use when the flywheel overspins, when torque telemetry drifts past the calibration band, when a spindle stalls under load, or the user says "flywheel wobble", "torque calibration", "spindle stall".
keywords: flywheel, torque, spindle, calibration, governor
---
Body of flywheel-torque-calibration.
"""

_BARNACLE = """---
name: barnacle-hull-scrub-scheduler
description: Schedule hull barnacle scrubbing for a marine vessel fleet. Use when barnacle growth exceeds the drag threshold, when hull fouling slows a vessel, or the user says "barnacle buildup", "hull scrub", "fouling schedule".
keywords: barnacle, hull, scrub, fouling, vessel
---
Body of barnacle-hull-scrub-scheduler.
"""

_LANTERN = """---
name: lantern-wick-trimming-guide
description: Trim and maintain oil lantern wicks for even flame. Use when a lantern smokes, when the wick chars unevenly, or the user says "lantern smoking", "wick trim", "uneven flame".
keywords: lantern, wick, flame, trimming, oil
---
Body of lantern-wick-trimming-guide.
"""

# Canonical key order (lib/meta.py CANON), absolute dates, use_count=0.
_META0 = (
    "provenance=managed\n"
    "pinned=false\n"
    "state=active\n"
    "created=2020-06-15\n"
    "last_used=2020-06-15\n"
    "last_patched=\n"
    "use_count=0\n"
    "quality=\n"
)

# Two real user turns; last-user (the tick's task-intent probe) picks the strong one.
_TRANSCRIPT = (
    json.dumps({"type": "user", "message": {"content": "some earlier unrelated chatter"}}) + "\n"
    + json.dumps({"type": "user",
                  "message": {"content": "my flywheel torque calibration spindle rig is stalling"}}) + "\n"
)


def run(ctx):
    # --- seed three distinctively-triggered skills WITH absolute-dated .meta
    #     BEFORE install, so install git-inits/commits them and stamp_meta (which
    #     only stamps skills lacking a .meta) leaves the dates untouched. ---
    ctx.seed("skills/flywheel-torque-calibration/SKILL.md", _FLYWHEEL)
    ctx.seed("skills/flywheel-torque-calibration/.meta", _META0)
    ctx.seed("skills/barnacle-hull-scrub-scheduler/SKILL.md", _BARNACLE)
    ctx.seed("skills/barnacle-hull-scrub-scheduler/.meta", _META0)
    ctx.seed("skills/lantern-wick-trimming-guide/SKILL.md", _LANTERN)
    ctx.seed("skills/lantern-wick-trimming-guide/.meta", _META0)

    # transcript fixture OUTSIDE $CLAUDE_DIR (kept out of the tree snapshot).
    ctx.seed_home("cairn-fixtures/transcript.jsonl", _TRANSCRIPT)
    tp = str(ctx.home / "cairn-fixtures" / "transcript.jsonl")

    # install (+ wire the UserPromptSubmit suggest / PostToolUse track hooks so the
    # settings.json hook block is captured too). No assess -> no model/shim calls.
    ctx.run("install", "--enable-hooks")

    # =====================================================================
    # suggest — manual
    # =====================================================================
    ctx.run("suggest")                                    # no arg -> silent (return 0)

    # STRONG: distinctive flywheel/torque/spindle vocab clears the threshold ->
    # prints the single matching-skill nudge block (score elided; no @@ROSTER@@).
    ctx.run("suggest",
            "my flywheel torque calibration on the spindle rig drifted and the spindle stall under load")

    # WARM but no strong match: one distinctive token ('hull') -> best score sits
    # between floor and threshold -> the names-only ROSTER safety net. stdout must
    # be the human nudge, NOT the raw @@ROSTER@@ sentinel.
    ctx.run("suggest", "the hull looks dirty")

    # Same warm prompt with the roster disabled -> silent.
    ctx.run("suggest", "the hull looks dirty", env={"CAIRN_SUGGEST_ROSTER": "0"})

    # Off-topic chatter (zero skill-vocab overlap) -> silent.
    ctx.run("suggest", "let us refactor the database schema please")

    # Warm-but-below-floor: a single non-keyword desc token ('telemetry') scores
    # under the roster floor -> silent (distinct from the zero-overlap case).
    ctx.run("suggest", "check the telemetry dashboard now")

    # =====================================================================
    # suggest --hook  (UserPromptSubmit: prompt as JSON on stdin)
    # =====================================================================
    ctx.run("suggest", "--hook",
            stdin=json.dumps({"prompt": "my flywheel torque calibration spindle rig is stalling"}))
    ctx.run("suggest", "--hook", stdin=json.dumps({"prompt": "the hull looks dirty"}))
    ctx.run("suggest", "--hook", stdin=json.dumps({"prompt": ""}))       # empty prompt -> silent
    ctx.run("suggest", "--hook", stdin=b"not json at all")              # malformed -> silent
    ctx.run("suggest", "--hook", stdin=b"")                             # no stdin -> silent

    # =====================================================================
    # suggest --tick  (PostToolUse re-surface; CAIRN_SUGGEST_TICK gates emission)
    # =====================================================================
    tick_in = json.dumps({"session_id": "ticksess", "transcript_path": tp})

    # guards: non-numeric N, N=0, and a missing transcript_path -> all silent, and
    # none of them create a counter file (they return before the counter bumps).
    ctx.run("suggest", "--tick", stdin=tick_in, env={"CAIRN_SUGGEST_TICK": "abc"})
    ctx.run("suggest", "--tick", stdin=tick_in, env={"CAIRN_SUGGEST_TICK": "0"})
    ctx.run("suggest", "--tick",
            stdin=json.dumps({"session_id": "ticknop"}), env={"CAIRN_SUGGEST_TICK": "1"})

    # modulo gate at N=2: call 1 increments to 1 -> silent; call 2 hits 2 % 2 == 0
    # -> emits the additionalContext JSON. counter file ends holding "2".
    ctx.run("suggest", "--tick", stdin=tick_in, env={"CAIRN_SUGGEST_TICK": "2"})
    ctx.run("suggest", "--tick", stdin=tick_in, env={"CAIRN_SUGGEST_TICK": "2"})

    # =====================================================================
    # track --hook  (real activation telemetry)
    # =====================================================================
    ctx.run("track")                                       # no --hook -> warn, rc 0
    ctx.run("track", "--hook", stdin=b"")                  # empty stdin -> ignored
    ctx.run("track", "--hook",
            stdin=json.dumps({"tool_input": {"skill": "no-such-skill"}}))   # unknown -> ignored
    ctx.run("track", "--hook",
            stdin=json.dumps({"tool_name": "Bash",
                              "tool_input": {"command": "ls -la", "description": "list files"}}))  # Bash -> ignored

    # Skill tool_input -> bump. Plain name: flywheel use_count 0 -> 1, last_used=today.
    ctx.run("track", "--hook",
            stdin=json.dumps({"tool_name": "Skill",
                              "tool_input": {"skill": "flywheel-torque-calibration", "args": ""}}))
    # plugin:skill form -> the v.split(":")[-1] path bumps barnacle 0 -> 1.
    ctx.run("track", "--hook",
            stdin=json.dumps({"tool_name": "Skill",
                              "tool_input": {"skill": "someplugin:barnacle-hull-scrub-scheduler"}}))
    # lantern is never a track target -> stays use_count=0 (control for the ignores).
