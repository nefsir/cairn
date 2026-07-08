NAME = "status-dashboard-seeded-library"

# Golden master for `cairn status` — the whole dashboard, on both an empty and a
# richly-seeded library. cmd_status is READ-ONLY (it prints; it never writes), so
# every observable here is a function of the fixtures + the two `date` reads in
# its header. This scenario pins:
#   * the bare/uninstalled dashboard  ("Skills: (none — ... run cairn install)")
#   * the populated dashboard: total, by-provenance histogram (managed/bundled/
#     (none)), by-state histogram (active/stale/archived/(none)), quality scored
#     line (avg + unscored), improvable (>=5 eval cases), never-rated count,
#     avg-usefulness, the LOW-usefulness selection (the <=2.5 avg AND >=3 uses
#     gate, sorted ascending, capped at 5) and its two exclusion gates, the
#     fold-candidate (>=15 learnings) hint, the lifecycle-ready hint (stable
#     0->stale / 1->archived), the frontmatter-issues (lint) hint, the memory
#     line, the mined/proposals/curate harvest lines, and BOTH hook states.
#   * `provenance --list` over the same library (use_count / quality / pinned /
#     state / last_used columns) — the use_count surface the dashboard omits.
#
# Determinism (why this is a stable golden master, not just green-today):
#   * Every skill's lifecycle classification is time-INVARIANT. Skills meant to
#     stay put carry EMPTY date stamps (state_for -> active, forever) or are
#     pinned/bundled (lifecycle skips them). The one archive-ready skill is dated
#     2000-01-01 (idle >> 90d for any realistic `today`, so it is proposed
#     `archived` on every calendar day). No fixture sits in the drifting 30-90d
#     stale window, so `lifecycle ready: 0 -> stale, 1 -> archived` never changes.
#   * All fixtures are seeded AFTER install, so install's stamp_meta (which would
#     stamp a non-deterministic mtime date) and seed_feedback never touch them;
#     the .meta-less orphan stays .meta-less -> the (none) provenance/state rows.
#   * Skill dir names are ASCII lowercase/hyphen slugs, so the C-locale glob sort
#     behind the histograms and the --list table is fully determined.
#   * Absolute dates in seeded usage.md/learnings.md are collapsed to <DATE> by
#     the normalizer and never reach status stdout (it prints only counts).
#
# NOTE ON NON-DETERMINISM (shared with s01/s02): the status header embeds
# `date '+%Y-%m-%d %H:%M'`. The normalizer collapses the YYYY-MM-DD to <DATE>
# but the HH:MM minute is left raw, so oracle and candidate must run within the
# same wall-clock minute. They run back-to-back (sub-second apart), so this is
# green in practice; a port must emit the identical minute-granularity format.


def _skill_md(name, desc="Fixture skill; triggers on foo, bar, baz.", body="Body."):
    return "---\nname: %s\ndescription: %s\n---\n%s\n" % (name, desc, body)


def _meta(provenance="managed", pinned="false", state="active",
          created="", last_used="", last_patched="", use_count="0", quality=""):
    return ("provenance=%s\npinned=%s\nstate=%s\ncreated=%s\nlast_used=%s\n"
            "last_patched=%s\nuse_count=%s\nquality=%s\n"
            % (provenance, pinned, state, created, last_used,
               last_patched, use_count, quality))


def _usage(name, scores):
    lines = ["# Usage ratings — %s" % name,
             "<!-- YYYY-MM-DD | N/5 | task context | helped or hindered -->"]
    for i, s in enumerate(scores):
        lines.append("2001-01-%02d | %d/5 | some task context | note" % (i + 1, s))
    return "\n".join(lines) + "\n"


def _cases(name, n):
    lines = ["# Eval cases — %s" % name]
    for i in range(n):
        lines.append("## Case %d: scenario number %d" % (i + 1, i + 1))
        lines.append("input -> expected")
    return "\n".join(lines) + "\n"


def _learnings(name, n):
    lines = ["# Learnings — %s" % name,
             "<!-- YYYY-MM-DD — what happened → what to do differently -->"]
    for i in range(n):
        lines.append("2001-02-%02d — hit issue %d → do Y instead of X" % (i + 1, i + 1))
    return "\n".join(lines) + "\n"


# A cairn SessionEnd review hook, byte-controlled, so the dashboard's hook probe
# (`grep -q 'cairn.*review' settings.json`) flips "off" -> "on" without a second
# install (which would re-run provision and mutate the tree).
_SETTINGS_HOOK_ON = (
    '{\n'
    '  "hooks": {\n'
    '    "SessionEnd": [\n'
    '      {\n'
    '        "hooks": [\n'
    '          {\n'
    '            "type": "command",\n'
    '            "command": "cairn review --hook"\n'
    '          }\n'
    '        ]\n'
    '      }\n'
    '    ]\n'
    '  }\n'
    '}\n'
)


def run(ctx):
    # 0. BARE dashboard: no $CLAUDE_DIR/skills yet -> "Skills: (none — ... run
    #    cairn install)", no memory line, harvest all-none, hook off. rc 0.
    ctx.run("status")

    # 1. install (no hooks): skill-extraction (bundled, excluded from the
    #    dashboard), dirs, memories/USER.md + MEMORY.md, CLAUDE.md, git-init.
    ctx.run("install")

    # 2. Seed the library AFTER install so stamp_meta/seed_feedback never touch
    #    these fixtures; every byte is exactly what I write (all untracked).

    # archived STATE + old date: proposed archived == current -> NOT lifecycle-
    # emitted. Never rated. quality set. -> archived bucket in by-state.
    ctx.seed("skills/archived-legacy/SKILL.md", _skill_md("archived-legacy"))
    ctx.seed("skills/archived-legacy/.meta",
             _meta(state="archived", created="2000-01-01", last_used="2000-01-01",
                   use_count="12", quality="4"))

    # bundled provenance: lifecycle SKIPS it; empty dates. Rated but not low.
    ctx.seed("skills/bundled-core-io/SKILL.md", _skill_md("bundled-core-io"))
    ctx.seed("skills/bundled-core-io/.meta",
             _meta(provenance="bundled", use_count="88", quality="5"))
    ctx.seed("skills/bundled-core-io/usage.md", _usage("bundled-core-io", [5, 5, 4]))

    # the ONE archive-ready skill: old date but state=active, managed, unpinned
    # -> proposed archived != active -> the sole "1 -> archived" in lifecycle.
    # quality UNSET (unscored). Never rated.
    ctx.seed("skills/lifecycle-archivable/SKILL.md", _skill_md("lifecycle-archivable"))
    ctx.seed("skills/lifecycle-archivable/.meta",
             _meta(state="active", created="2000-01-01", last_used="2000-01-01",
                   use_count="1", quality=""))

    # pinned + stale STATE: pinned -> lifecycle SKIPS it (so its old date does not
    # add to the archived count); shows the `stale` bucket in by-state.
    ctx.seed("skills/pinned-stable-ref/SKILL.md", _skill_md("pinned-stable-ref"))
    ctx.seed("skills/pinned-stable-ref/.meta",
             _meta(pinned="true", state="stale", created="2000-01-01",
                   last_used="2000-01-01", use_count="3", quality="3"))

    # PRIMARY low-usefulness: avg 1.7 over 3 -> selected, lowest avg -> sorts first.
    ctx.seed("skills/low-signal-flaky/SKILL.md", _skill_md("low-signal-flaky"))
    ctx.seed("skills/low-signal-flaky/.meta", _meta(use_count="9", quality="2"))
    ctx.seed("skills/low-signal-flaky/usage.md", _usage("low-signal-flaky", [1, 2, 2]))

    # SECOND low-usefulness at the <=2.5 boundary: avg 2.5 over 4 -> selected,
    # sorts AFTER the 1.7 one (proves the ascending sort + inclusive boundary).
    ctx.seed("skills/mixed-bag-helper/SKILL.md", _skill_md("mixed-bag-helper"))
    ctx.seed("skills/mixed-bag-helper/.meta", _meta(use_count="5", quality="1"))
    ctx.seed("skills/mixed-bag-helper/usage.md", _usage("mixed-bag-helper", [2, 3, 2, 3]))

    # rated but NOT low (avg 4.7): also carries >=5 eval cases -> the `improvable`
    # count. Exercises the avg-gate exclusion from LOW.
    ctx.seed("skills/high-value-core/SKILL.md", _skill_md("high-value-core"))
    ctx.seed("skills/high-value-core/.meta", _meta(use_count="20", quality="5"))
    ctx.seed("skills/high-value-core/usage.md", _usage("high-value-core", [5, 4, 5]))
    ctx.seed("skills/high-value-core/evals/cases.md", _cases("high-value-core", 5))

    # low avg (1.0) but only 2 uses -> EXCLUDED by the >=3-uses gate (rated, not low).
    ctx.seed("skills/few-uses-weak/SKILL.md", _skill_md("few-uses-weak"))
    ctx.seed("skills/few-uses-weak/.meta", _meta(use_count="2", quality=""))
    ctx.seed("skills/few-uses-weak/usage.md", _usage("few-uses-weak", [1, 1]))

    # fold candidate: 15 dated learnings -> the ">=15 learnings" hint. Never rated.
    ctx.seed("skills/fold-heavy-notes/SKILL.md", _skill_md("fold-heavy-notes"))
    ctx.seed("skills/fold-heavy-notes/.meta", _meta(use_count="6", quality="3"))
    ctx.seed("skills/fold-heavy-notes/learnings.md", _learnings("fold-heavy-notes", 15))

    # broken frontmatter (empty description) -> the "frontmatter issues -> cairn
    # lint" hint (inv=1). Still counts everywhere else in the dashboard.
    ctx.seed("skills/broken-frontmatter/SKILL.md",
             "---\nname: broken-frontmatter\ndescription:\n---\nBody with no description.\n")
    ctx.seed("skills/broken-frontmatter/.meta", _meta(use_count="0", quality=""))

    # .meta-less orphan (seeded after install so stamp_meta never stamps it) ->
    # (none) in BOTH the provenance and state histograms; never rated.
    ctx.seed("skills/orphan-no-meta/SKILL.md", _skill_md("orphan-no-meta"))

    # harvest state -> lights up the mined/proposals/curate dashboard lines.
    ctx.seed("cairn/harvest/candidates.jsonl",
             '{"id": 1, "note": "candidate one"}\n'
             '{"id": 2, "note": "candidate two"}\n'
             '{"id": 3, "note": "candidate three"}\n')
    ctx.seed("cairn/harvest/PROPOSALS.md",
             "# Proposals\n\n"
             "### first-proposed-skill\nsome body\n\n"
             "### second-proposed-skill\nmore body\n")
    ctx.seed("cairn/harvest/CURATE.md", "# Curate report\n\nmerge/fold/lifecycle detail.\n")

    # 3. FULL populated dashboard, hook OFF (no settings.json yet).
    ctx.run("status")

    # 4. provenance --list over the same library: the use_count / quality /
    #    pinned / state / last_used table (skill-extraction excluded, orphan is a
    #    "(none) - - - - -" row), C-locale-sorted.
    ctx.run("provenance", "--list")

    # 5. Seed a cairn review hook so the dashboard's hook probe flips on.
    ctx.seed("settings.json", _SETTINGS_HOOK_ON)

    # 6. Same dashboard, now "SessionEnd hook: on" — the only line that changes.
    ctx.run("status")
