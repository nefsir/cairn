# =============================================================================
# s10_curate_merge — golden master for `cairn curate --merge` (Layer B, G8).
#
# Drives the full auto-merge surface:
#   * preview (no --yes)              — clustering + "would merge", no side effects
#   * --yes with a VALID umbrella      — merge succeeds, originals ARCHIVED (moved,
#                                        not deleted), umbrella SKILL.md written
#   * --yes with a PATH-TRAVERSAL name — model `name:` is `../../../etc/passwd`;
#                                        cairn sanitises it and falls back to the
#                                        first member's (safe, in-tree) dir
#   * --yes with a claude HARD FAIL    — run_claude rc=2 -> "merge failed", intact
#   * --yes with MALFORMED output      — no frontmatter -> validation rejects it,
#                                        the live skills are never touched
#
# Clusters use DISJOINT vocabularies (mongodb-index / git-rebase / redis-timeout)
# so they never cross-cluster, and each destructive step is ordered so only ONE
# multi-member cluster is live when it runs. All fixture dates are ABSOLUTE:
# last_used is pinned to the far future (2099-01-01) so lifecycle math classifies
# every seeded skill "active" regardless of the wall-clock day the harness runs.
#
# KNOWN NON-DETERMINISM (reported, not worked around): a successful archive names
# its destination `<name>-$(ts)` where ts()=YYYYMMDD-HHMMSS (wall clock). The
# harness compares the $CLAUDE_DIR *tree path set* RAW (only file *content* is
# passed through _norm, never the path names), so the two sequential oracle/
# candidate runs land in different seconds and the archived dirs diverge. See the
# structured report for the precise observable.
# =============================================================================

NAME = "curate-merge-umbrellas"

META_ACTIVE = (
    "provenance=managed\n"
    "pinned=false\n"
    "state=active\n"
    "created=2025-01-01\n"
    "last_used=2099-01-01\n"   # far-future -> lifecycle stays 'active' invariantly
    "use_count=0\n"
    "quality=\n"
)


def _skill(name, desc, body):
    return "---\nname: %s\ndescription: %s\n---\n# %s\n\n%s\n" % (name, desc, name, body)


# ---- cluster A: mongodb compound-index audit (2 clearly-overlapping members) --
MONGO_DESC = ("Audit mongodb compound index prefixes and remove redundant duplicate "
              "indexes. Use when reviewing mongodb index coverage, diagnosing slow "
              "collection queries, finding redundant compound index prefixes, "
              "consolidating overlapping mongodb indexes.")

# ---- cluster C: git rebase history rewrite (2 members) -----------------------
GITR_DESC = ("Rewrite git commit history messages before merge. Use when injecting a "
             "jira ticket prefix, stripping co-author lines, normalizing unpushed "
             "commit messages with git filter-branch msg-filter.")

# ---- cluster B: redis lettuce command timeout (2 members) -------------------
REDIS_DESC = ("Diagnose redis lettuce command timeout exceptions. Use when "
              "RedisCommandTimeoutException appears, when lettuce command timeout is "
              "ignored, when redis timeouts start after adding commons pool.")


# ---- deterministic model outputs the claude shim replays (CAIRN_SHIM_CLAUDE_OUT)
UMBRELLA_OK = _skill(
    "mongo-index-umbrella",
    ("Umbrella for mongodb compound index auditing and dedup. Use when reviewing "
     "mongodb index coverage, diagnosing slow queries, removing redundant compound "
     "index prefixes, consolidating overlapping indexes."),
    ("Merged umbrella that combines the mongodb index-audit siblings.\n\n"
     "## Audit compound index prefixes\n"
     "Find indexes whose key prefix is covered by a longer index.\n\n"
     "## Dedup redundant indexes\n"
     "Drop the shorter prefix once coverage is confirmed."),
)

# path-traversal name in the frontmatter: must be sanitised, dir falls back to $1
UMBRELLA_TRAVERSAL = _skill(
    "../../../etc/passwd",
    ("Umbrella for git rebase history rewriting. Use when rewriting unpushed commit "
     "messages, injecting jira prefixes, stripping co-author lines with "
     "git filter-branch."),
    "Merged umbrella body for the git rebase rewrite siblings.",
)

# malformed: no YAML frontmatter at all -> py validate skill rejects it
UMBRELLA_MALFORMED = ("this is not a skill file - it has no yaml frontmatter at all, "
                      "so staging validation must reject it and leave the originals intact")


def run(ctx):
    ctx.run("install")

    # -- cluster A --------------------------------------------------------------
    ctx.seed("skills/mongo-index-audit-a/SKILL.md",
             _skill("mongo-index-audit-a", MONGO_DESC, "Audit the primary collection's indexes."))
    ctx.seed("skills/mongo-index-audit-a/.meta", META_ACTIVE)
    ctx.seed("skills/mongo-index-audit-a/learnings.md",
             "# Learnings\n- 2025-02-01 - prefix overlap missed -> always check key order\n")
    ctx.seed("skills/mongo-index-audit-a/usage.md",
             "# Usage\n2025-02-01 | 4/5 | audited orders coll | found 2 dupes\n")
    ctx.seed("skills/mongo-index-audit-b/SKILL.md",
             _skill("mongo-index-audit-b", MONGO_DESC, "Audit the secondary collection's indexes."))
    ctx.seed("skills/mongo-index-audit-b/.meta", META_ACTIVE)
    ctx.seed("skills/mongo-index-audit-b/learnings.md",
             "# Learnings\n- 2025-03-01 - TTL index counts as coverage too\n")
    ctx.seed("skills/mongo-index-audit-b/usage.md",
             "# Usage\n2025-03-01 | 5/5 | audited events coll | dropped a redundant prefix\n")

    # 1) PREVIEW: no --yes -> lists "would merge", calls nothing, changes nothing.
    ctx.run("curate", "--merge")

    # 2) SUCCESS: valid umbrella -> merge, archive both members, write umbrella.
    ctx.run("curate", "--merge", "--yes", env={"CAIRN_SHIM_CLAUDE_OUT": UMBRELLA_OK})

    # -- cluster C (git rebase) — seeded now so only C is live this step ---------
    ctx.seed("skills/git-rebase-rewrite-a/SKILL.md",
             _skill("git-rebase-rewrite-a", GITR_DESC, "Rewrite messages on the feature branch."))
    ctx.seed("skills/git-rebase-rewrite-a/.meta", META_ACTIVE)
    ctx.seed("skills/git-rebase-rewrite-b/SKILL.md",
             _skill("git-rebase-rewrite-b", GITR_DESC, "Rewrite messages on the release branch."))
    ctx.seed("skills/git-rebase-rewrite-b/.meta", META_ACTIVE)

    # 3) TRAVERSAL: model name is `../../../etc/passwd`. cairn rejects the unsafe
    #    name and falls back to the first member's dir (git-rebase-rewrite-a);
    #    git-rebase-rewrite-b is archived. No file escapes the skills tree.
    ctx.run("curate", "--merge", "--yes", env={"CAIRN_SHIM_CLAUDE_OUT": UMBRELLA_TRAVERSAL})

    # -- cluster B (redis) — seeded now so only B is live for the failure steps --
    ctx.seed("skills/redis-timeout-lettuce-a/SKILL.md",
             _skill("redis-timeout-lettuce-a", REDIS_DESC, "Timeouts on the session cache."))
    ctx.seed("skills/redis-timeout-lettuce-a/.meta", META_ACTIVE)
    ctx.seed("skills/redis-timeout-lettuce-b/SKILL.md",
             _skill("redis-timeout-lettuce-b", REDIS_DESC, "Timeouts on the rate-limit store."))
    ctx.seed("skills/redis-timeout-lettuce-b/.meta", META_ACTIVE)

    # 4) CLAUDE HARD FAIL: shim exits 2 -> run_claude returns 2 -> "merge failed",
    #    both members left intact (no archive, no umbrella).
    ctx.run("curate", "--merge", "--yes", env={"CAIRN_SHIM_CLAUDE_RC": "2"})

    # 5) MALFORMED OUTPUT: non-empty but no frontmatter -> staging validation
    #    rejects it -> both members left intact.
    ctx.run("curate", "--merge", "--yes", env={"CAIRN_SHIM_CLAUDE_OUT": UMBRELLA_MALFORMED})
