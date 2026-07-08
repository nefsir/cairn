NAME = "curate-archive-weak"

# Golden master for `cairn curate --archive-weak` (cmd_curate, the do_weak block).
# Drives the FULL surface of the flag:
#   * bare/uninstalled  -> die "no skills dir", rc 1
#   * PREVIEW (no --yes)     -> lists "would archive: <name> (<reason>)" for every
#                               weak skill, MAKES NO CHANGES to skills/
#   * unknown option         -> die "curate: unknown option", rc 1
#   * --yes                  -> MOVES weak skills into cairn/skill-archive/, commits;
#                               protected (pinned / bundled) skills SURVIVE untouched
#   * PREVIEW after archive   -> "no weak skills" (weak ones gone, protected excluded)
#   * --assess WITHOUT --yes  -> assessment is a NO-OP in preview: the claude shim is
#                               NOT called, the unscored skill stays unscored
#   * --assess --yes          -> assess_skills scores the one unscored skill via the
#                               claude shim (quality lands in .meta), THEN weak
#                               detection runs on the fresh scores
#
# Weakness has two independent triggers (see the do_weak python in bin/cairn):
#   quality 1|2 in .meta        -> weak-by-quality
#   usage avg <= 2.5 over >= 3  -> weak-by-usefulness
# Protection has two triggers (is_protected + the weak python's skip):
#   pinned=true  |  provenance=bundled
#
# ---------------------------------------------------------------------------
# DETERMINISM
#   * Every seeded .meta / usage.md uses ABSOLUTE dates (created=2000-01-01) so
#     the weak / lifecycle math is invariant to when the harness runs; the
#     normalizer collapses dates to <DATE> anyway. `py meta init` never clobbers
#     an existing .meta, so install leaves these bytes untouched.
#   * Skill dir names are ASCII lowercase/hyphen slugs -> the C-locale glob sort
#     the do_weak python relies on is fully determined
#     (weak-by-quality < weak-by-usefulness).
#   * Fixture descriptions are token-disjoint, so the consolidation clusterer
#     produces no merge clusters in CURATE.md (stable body).
#   * The claude shim is invoked EXACTLY ONCE in the whole scenario (the final
#     --assess --yes, scoring unscored-fresh); CAIRN_SHIM_CLAUDE_OUT="4" makes
#     that score land IN-PLACE in skills/unscored-fresh/.meta (deterministic
#     tree byte) instead of a non-deterministic archive dir, isolating the one
#     genuine non-determinism below.
#
# GENUINE NON-DETERMINISM (reported, not worked around — the --yes step is a
# required part of this gap, so it is kept, per the harness's own rule):
#   1. [reliably divergent] `--archive-weak --yes` MOVES each weak skill to
#      $ARCHIVE/<name>-$(ts)  where ts()=`date +%Y%m%d-%H%M%S` (wall-clock, second
#      granularity).  compare() diffs the $CLAUDE_DIR TREE-PATH KEYS RAW — only
#      file *contents*/stdout pass through _norm (which DOES have an archive-suffix
#      rule `-\d{8}-\d{6}` for exactly these stamps, but it is never applied to the
#      keys).  Oracle and candidate run as two sequential full passes, so their
#      archive dirs land on different seconds -> "TREE PATHS differ" on
#      cairn/skill-archive/<name>-<TS>/**.  Any scenario that physically archives
#      (curate --archive-weak --yes, curate --merge --yes, curate --apply-lifecycle)
#      hits this.
#   2. [latent, minute-boundary] Every curate run rewrites cairn/harvest/CURATE.md
#      whose header is `# Cairn curate report ($(date '+%Y-%m-%d %H:%M'))`.  The
#      normalizer's datetime rule requires SECONDS (\d{2}:\d{2}:\d{2}); the header
#      has only HH:MM, so `<DATE> HH:MM` keeps the un-erased minute.  Diverges only
#      if the two passes straddle a minute boundary.

# ---- canonical .meta blocks (lib/meta.py CANON order), absolute dates ----------

def _meta(pinned="false", provenance="managed", use_count="1", quality=""):
    return ("provenance=%s\n"
            "pinned=%s\n"
            "state=active\n"
            "created=2000-01-01\n"
            "last_used=2000-01-01\n"
            "last_patched=\n"
            "use_count=%s\n"
            "quality=%s\n") % (provenance, pinned, use_count, quality)


def _skill(name, desc):
    return "---\nname: %s\ndescription: %s\n---\nBody of %s.\n" % (name, desc, name)


# three low ratings -> avg (2+2+1)/3 = 1.7, n=3  -> weak-by-usefulness
_WEAK_USAGE = (
    "# Usage ratings — weak-by-usefulness\n"
    "2000-01-01 | 2/5 | first task context | activated but weak\n"
    "2000-02-01 | 2/5 | second task context | not helpful\n"
    "2000-03-01 | 1/5 | third task context | misleading\n"
)
# healthy: avg (5+5+4)/3 = 4.7, n=3 -> never weak
_HEALTHY_USAGE = (
    "# Usage ratings — healthy-umbrella\n"
    "2000-01-01 | 5/5 | migrated an index online | directly sped up\n"
    "2000-02-01 | 5/5 | another online migration | corrected my plan\n"
    "2000-03-01 | 4/5 | a third migration | solid guidance\n"
)


def run(ctx):
    # 0. BARE: no skills dir yet -> die "no skills dir", rc 1 (stderr). Must run
    #    before any seed, since ctx.seed materializes $CLAUDE_DIR/skills.
    ctx.run("curate", "--archive-weak")

    # ---- seed the fixture library BEFORE install so install git-inits + commits
    #      them and stamp_meta leaves their seeded .meta bytes alone. -------------
    # weak by quality (1/5), managed -> archivable
    ctx.seed("skills/weak-by-quality/SKILL.md",
             _skill("weak-by-quality",
                    "Poorly written throwaway note about renaming a spreadsheet column once."))
    ctx.seed("skills/weak-by-quality/.meta", _meta(quality="1"))

    # weak by usefulness (avg 1.7 over 3), managed, unscored -> archivable
    ctx.seed("skills/weak-by-usefulness/SKILL.md",
             _skill("weak-by-usefulness",
                    "Rarely helpful reminder concerning airport shuttle timetable colours."))
    ctx.seed("skills/weak-by-usefulness/.meta", _meta(use_count="3"))
    ctx.seed("skills/weak-by-usefulness/usage.md", _WEAK_USAGE)

    # pinned + quality 1: WOULD be weak, but pinned=true protects it -> survives
    ctx.seed("skills/pinned-lowq/SKILL.md",
             _skill("pinned-lowq",
                    "Load-bearing pinned runbook the operator insists on keeping around."))
    ctx.seed("skills/pinned-lowq/.meta", _meta(pinned="true", quality="1"))

    # bundled + quality 1: WOULD be weak, but provenance=bundled protects it
    ctx.seed("skills/bundled-lowq/SKILL.md",
             _skill("bundled-lowq",
                    "Infrastructure bundled helper shipped with the toolchain distribution."))
    ctx.seed("skills/bundled-lowq/.meta", _meta(provenance="bundled", quality="1"))

    # healthy, quality 5, good usage -> never weak -> survives
    ctx.seed("skills/healthy-umbrella/SKILL.md",
             _skill("healthy-umbrella",
                    "Robust reusable procedure for migrating database indexes online safely."))
    ctx.seed("skills/healthy-umbrella/.meta", _meta(use_count="9", quality="5"))
    ctx.seed("skills/healthy-umbrella/usage.md", _HEALTHY_USAGE)

    # unscored managed skill: the --assess target (no quality, no usage yet)
    ctx.seed("skills/unscored-fresh/SKILL.md",
             _skill("unscored-fresh",
                    "Brand new candidate covering keyboard shortcut muscle memory drills."))
    ctx.seed("skills/unscored-fresh/.meta", _meta(use_count="0"))

    # 1. install: git-init + commit the seeded library, add the bundled meta-skill.
    ctx.run("install")

    # 2. PREVIEW (no --yes): both weak skills listed as "would archive: ..." with
    #    their reason strings; skills/ is NOT modified (harness diffs the tree).
    #    Order is C-locale glob: weak-by-quality then weak-by-usefulness.
    ctx.run("curate", "--archive-weak")

    # 3. die path: an unknown option is rejected during arg parse (rc 1, stderr),
    #    before any report is written.
    ctx.run("curate", "--archive-weak", "--bogus")

    # 4. --yes: MOVES weak-by-quality + weak-by-usefulness into cairn/skill-archive/
    #    and commits "cairn: archived 2 weak skill(s)". Protected pinned-lowq /
    #    bundled-lowq and healthy-umbrella / unscored-fresh stay in skills/.
    #    NON-DETERMINISTIC: the two archive dirs are wall-clock-stamped (finding #1).
    ctx.run("curate", "--archive-weak", "--yes")

    # 5. PREVIEW after archive: the two weak skills are gone; pinned/bundled are
    #    excluded; healthy + unscored are not weak -> "no weak skills".
    ctx.run("curate", "--archive-weak")

    # 6. --assess WITHOUT --yes: assessment only runs under --yes, so this is a
    #    plain preview — the claude shim is NOT called and unscored-fresh stays
    #    unscored (its .meta keeps quality= empty). -> "no weak skills".
    ctx.run("curate", "--archive-weak", "--assess")

    # 7. --assess --yes: assess_skills scores the sole unscored skill (unscored-fresh)
    #    via the claude shim (the ONLY shim call in this scenario). CAIRN_SHIM_CLAUDE_OUT
    #    "4" makes the score land in skills/unscored-fresh/.meta (deterministic) and
    #    keeps it non-weak, so nothing new is archived. Then weak detection -> none.
    ctx.run("curate", "--archive-weak", "--assess", "--yes",
            env={"CAIRN_SHIM_CLAUDE_OUT": "4"})
