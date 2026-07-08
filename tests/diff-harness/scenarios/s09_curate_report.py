NAME = "curate-report-and-lifecycle"

# Golden master for `cairn curate` (Layer B — consolidation + lifecycle):
#   * the read-only report itself (cmd_curate + lib/lifecycle.py), byte-for-byte —
#     every section the analyser can emit: overlapping-trigger CLUSTERS, FOLD
#     candidates (learnings.md past fold-at), LOW-USEFULNESS (usage.md avg),
#     LOW-QUALITY (.meta quality 1-2), and the LIFECYCLE transitions table
#     (active -> stale, active -> archived) driven by ABSOLUTE .meta dates;
#   * the edge/empty paths (a tidy library; a raised --threshold that collapses
#     the only cluster) and the two die paths (uninstalled; unknown option);
#   * `curate --apply-lifecycle`, which MOVES an archivable skill into
#     cairn/skill-archive (never deletes), stamps the stale one, commits the
#     whole skills tree, and PROTECTS pinned + bundled skills from both.
#
# The harness diffs the whole $CLAUDE_DIR tree + every .meta + settings.json +
# the skills git log/status + shim logs automatically; the steps below just drive
# cairn and let that comparison BE the assertion of "exact CURATE.md bytes".
#
# ---------------------------------------------------------------------------
# Determinism design (why this is a stable golden master):
#   * Fixtures use ABSOLUTE dates only. "Archivable" = last_used 2005-01-01,
#     "stale" = 2015-01-01, "active" = 2026-06-01. Combined with the pinned
#     thresholds passed on each step (CAIRN_STALE_DAYS=2000, CAIRN_ARCHIVE_DAYS
#     =6000) the active/stale/archived CLASSIFICATION is invariant for any run
#     day ~2026-2031 (verified against lib/lifecycle.py). The idle-days integers
#     printed in the table are today-relative, but the oracle and candidate runs
#     share the same wall-clock day, so they match — the differential comparison
#     stays byte-equal.
#   * Skill dir names are ASCII lowercase/hyphen slugs, so the C-locale glob sort
#     used by the analyser and by `lifecycle propose` is fully determined.
#   * Every seeded .meta is written in lib/meta.py's canonical key order, so the
#     `py meta set state stale` rewrite during --apply-lifecycle reproduces the
#     exact bytes on both sides.
#   * Skills are seeded AFTER install so install's stamp_meta/seed_feedback never
#     touch them (I supply the full .meta and only the learnings/usage I want);
#     they land untracked, and --apply-lifecycle's skills_commit records them.
#
# KNOWN NON-DETERMINISM this scenario deliberately surfaces (see the module
# docstring returned with the task): archive_skill() names its destination
# "$ARCHIVE/<name>-$(ts)" with a SECOND-precision wall-clock stamp, and
# diff-cairn compares raw tree-path SETS *before* normalisation. The oracle and
# candidate runs never share that second, so the archived skill's files land
# under different paths and the tree-path set diverges every run. The move is
# still fully asserted deterministically via normalised stdout ("... -> archived
# (<CLAUDE_DIR>/cairn/skill-archive/ancient-jenkins-runner-<TS>)") and the git
# commit subject ("cairn: lifecycle (1 stale, 1 archived)"); only the physical
# archived path is irreducibly non-deterministic. Per the harness policy the
# required --apply-lifecycle move is KEPT (not deleted to force green) and the
# finding is reported. (This is the same limitation s99_probe.py exercises.)
# ---------------------------------------------------------------------------

# lifecycle thresholds, pinned so absolute-date classification is run-day-stable
LIFE_ENV = {"CAIRN_STALE_DAYS": "2000", "CAIRN_ARCHIVE_DAYS": "6000"}


def _skill(name, desc):
    return ("---\n"
            "name: %s\n"
            "description: %s\n"
            "---\n"
            "# %s\n"
            "Body of %s.\n" % (name, desc, name, name))


def _meta(created, last_used, provenance="managed", pinned="false",
          state="active", quality=""):
    # canonical key order (lib/meta.py CANON) so any py-meta rewrite is byte-equal
    return ("provenance=%s\n"
            "pinned=%s\n"
            "state=%s\n"
            "created=%s\n"
            "last_used=%s\n"
            "last_patched=\n"
            "use_count=0\n"
            "quality=%s\n" % (provenance, pinned, state, created, last_used, quality))


# 16 dated learnings (>= fold-at 15) -> fold candidate. The '#'/'<!--' lines are
# not counted by learn_count; each "YYYY-MM-DD — ..." line is.
_FOLD_LEARNINGS = ("# Learnings — fold-heavy-vault\n"
                   "<!-- YYYY-MM-DD — what happened → what to do differently -->\n"
                   + "".join("2020-%02d-01 — lesson %d → adjust step %d\n" % (m, m, m)
                             for m in range(1, 13))
                   + "".join("2021-%02d-01 — lesson %d → adjust step %d\n" % (m, m + 12, m + 12)
                             for m in range(1, 5)))

# 3 usage rows, avg (2+1+2)/3 = 1.7/5 <= 2.5 over >= 3 uses -> low-usefulness
_LOWUSE_USAGE = ("# Usage ratings — sparse-usage-grafana\n"
                 "<!-- YYYY-MM-DD | N/5 | task context | helped or hindered -->\n"
                 "2020-01-01 | 2/5 | grafana embed attempt | hindered\n"
                 "2020-02-01 | 1/5 | dashboard helm chart | useless\n"
                 "2020-03-01 | 2/5 | panels layout | misleading\n")


def run(ctx):
    # 1. die path: curate with no skills dir yet (fresh HOME) -> rc 1, stderr.
    ctx.run("curate")

    # 2. install: git-inits skills/, seeds the bundled skill-extraction, commits.
    ctx.run("install")

    # 3. edge/empty: only the (protected) bundled skill exists -> both the
    #    "library looks tidy" and "nothing ages out" branches.
    ctx.run("curate", env=LIFE_ENV)

    # 4. seed the fixture library AFTER install (full control; untracked). ----
    # -- overlapping-trigger cluster (two near-identical descriptions) --
    ctx.seed("skills/cluster-redis-one/SKILL.md",
             _skill("cluster-redis-one", "Diagnose redis lettuce command timeout saturation"))
    ctx.seed("skills/cluster-redis-one/.meta", _meta("2024-01-01", "2026-06-01"))
    ctx.seed("skills/cluster-redis-two/SKILL.md",
             _skill("cluster-redis-two", "Diagnose redis lettuce command timeout saturation"))
    ctx.seed("skills/cluster-redis-two/.meta", _meta("2024-01-01", "2026-06-01"))

    # -- fold candidate: learnings.md over fold-at --
    ctx.seed("skills/fold-heavy-vault/SKILL.md",
             _skill("fold-heavy-vault", "Rotate postgres credentials sidecar renewal"))
    ctx.seed("skills/fold-heavy-vault/.meta", _meta("2024-01-01", "2026-06-01"))
    ctx.seed("skills/fold-heavy-vault/learnings.md", _FOLD_LEARNINGS)

    # -- low-usefulness: usage.md avg <= 2.5 over >= 3 uses --
    ctx.seed("skills/sparse-usage-grafana/SKILL.md",
             _skill("sparse-usage-grafana", "Embed grafana dashboard helm panels"))
    ctx.seed("skills/sparse-usage-grafana/.meta", _meta("2024-01-01", "2026-06-01"))
    ctx.seed("skills/sparse-usage-grafana/usage.md", _LOWUSE_USAGE)

    # -- low-quality: .meta quality=1 --
    ctx.seed("skills/poor-quality-mongo/SKILL.md",
             _skill("poor-quality-mongo", "Optimize mongo compound index prefix dedup"))
    ctx.seed("skills/poor-quality-mongo/.meta", _meta("2024-01-01", "2026-06-01", quality="1"))

    # -- lifecycle: stale (idle in [2000,6000)) --
    ctx.seed("skills/stale-kafka-consumer/SKILL.md",
             _skill("stale-kafka-consumer", "Rebalance kafka partition offsets lag"))
    ctx.seed("skills/stale-kafka-consumer/.meta", _meta("2010-01-01", "2015-01-01"))

    # -- lifecycle: archivable (idle >= 6000) and NOT protected -> gets MOVED --
    ctx.seed("skills/ancient-jenkins-runner/SKILL.md",
             _skill("ancient-jenkins-runner", "Provision jenkins nodes autoscale ephemeral"))
    ctx.seed("skills/ancient-jenkins-runner/.meta", _meta("2000-01-01", "2005-01-01"))

    # -- protected: pinned + archivable-by-date -> must be SKIPPED by lifecycle --
    ctx.seed("skills/pinned-terraform-plan/SKILL.md",
             _skill("pinned-terraform-plan", "Preview terraform plan drift remediation"))
    ctx.seed("skills/pinned-terraform-plan/.meta",
             _meta("2000-01-01", "2005-01-01", pinned="true"))

    # -- protected: bundled + archivable-by-date -> must be SKIPPED everywhere --
    ctx.seed("skills/bundled-ansible-play/SKILL.md",
             _skill("bundled-ansible-play", "Apply ansible playbook idempotent hosts"))
    ctx.seed("skills/bundled-ansible-play/.meta",
             _meta("2000-01-01", "2005-01-01", provenance="bundled"))

    # 5. die path: unknown option -> rc 1, stderr.
    ctx.run("curate", "--bogus", env=LIFE_ENV)

    # 6. --threshold flag: raise overlap to 0.99 so the redis pair (0.78) no
    #    longer clusters -> report keeps fold/low-use/low-quality/lifecycle but
    #    drops the "Merge into umbrellas" section.
    ctx.run("curate", "--threshold", "0.99", env=LIFE_ENV)

    # 7. the full read-only report: every section present. Writes CURATE.md.
    ctx.run("curate", env=LIFE_ENV)

    # 8. apply lifecycle: stale-kafka -> stale (.meta), ancient-jenkins MOVED to
    #    cairn/skill-archive (never deleted), pinned + bundled left untouched,
    #    whole tree committed. Rewrites CURATE.md (same report as step 7).
    ctx.run("curate", "--apply-lifecycle", env=LIFE_ENV)
