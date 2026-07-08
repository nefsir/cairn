# =============================================================================
# s13_distill_refine — golden master for Layer-A backfill: `cairn distill` +
# `cairn refine` (the two model steps that turn mined candidates into a scored
# PROPOSALS.md). Zero e2e coverage existed for this pair before.
#
# The pipeline under test:
#   candidates.jsonl --(py cluster, mechanical/no-AI)--> distill/clusters/*.json
#     --(SYN_PROMPT via the claude shim)--> distill/proposals/cluster_*.md
#     --(assemble)--> PROPOSALS.md                      [distill OVERWRITES, no backup]
#   distill/proposals/*.md --(split)--> refine/items/*  --(batch)--> refine/batches/*
#     --(REFINE_PROMPT via the shim)--> refine/out/*.md
#     --(aggregate, bucket by Reusability)--> PROPOSALS.md   [refine BACKS UP first,
#                                                             atomic `mv` of each batch]
#
# What this pins (the harness diffs it all, oracle vs candidate, byte-for-byte):
#   * MECHANICAL CLUSTERING — cluster_0000..0002.json are deterministic given the
#     seeded candidates: a 3-member redis cluster, a 2-member mongo cluster, and a
#     gradle singleton (sorted largest-first). --threshold 0.9 breaks every group
#     into singletons; --min-cluster 3 leaves exactly one eligible cluster.
#   * PER-CLUSTER / PER-BATCH RESUME STAMPS — distill/.done/cluster_NNNN.done and
#     refine/.done/batch_NNNN.done drive resume: a second run SKIPS a done unit
#     ("skip (done): ...") and synthesizes/refines 0; --reset clears the stamps and
#     re-runs. The stamp file names/contents are fully determined.
#   * THE MODEL FEED (.claude-stdin.N) — every SYN/REFINE call's exact stdin is
#     snapshotted by the shim, pinning the cluster feed ("Total in group: N
#     (showing M)" honoring --max-members) and the batched item text.
#   * PROPOSALS.md BYTES — the final refine-format doc (Highly reusable / Reusable
#     with parameterization / Specific buckets, ordered by Reusability score).
#   * run_claude's 3-way rc contract, exercised on BOTH commands: rc0 success, rc2
#     deterministic-fail (quarantine -> .failed, distill keeps going / refine still
#     backs up), rc1 transient with --max-retries 0 (HALT + "resume" exit 1, NO
#     sleep, NO backup — refine returns before the backup line).
#   * DIE paths: missing candidates, missing proposals dir, unknown option.
#
# Determinism notes:
#   * The candidates fixture is a byte-fixed, mine-like JSONL with ASCII
#     lowercase-hyphen slug names, so C-locale tokenization + the union-find
#     clustering (Jaccard >= threshold) are fully determined and stable.
#   * No fixture carries a date; every stamp/log timestamp cairn emits itself is
#     full-second ("YYYY-MM-DD HH:MM:SS") and collapses to <DATETIME> under the
#     normalizer, or is a git-pinned commit.
#   * install runs first (skills git-init/commit), and neither distill nor refine
#     touches skills/ or memory -> the skills git log stays at the install commit.
#
# KNOWN NON-DETERMINISM (reported, not worked around — same class as s10/s90):
#   `cairn refine` backs the existing PROPOSALS.md up to `PROPOSALS.md.bak-$(ts)`
#   before every rewrite, where ts()=YYYYMMDD-HHMMSS is WALL CLOCK. The harness
#   passes only file *content* through _norm; the $CLAUDE_DIR *tree path set* is
#   compared RAW, so the two sequential oracle/candidate runs (seconds apart) name
#   their backups in different seconds and the `.bak-<ts>` paths diverge as
#   "TREE PATHS differ". Every full refine invocation (rc2-fail, success, resume,
#   reset) emits one such backup. A secondary, minute-boundary-only leak: the
#   PROPOSALS.md header itself is stamped `$(date '+%Y-%m-%d %H:%M')` (distill) /
#   `%Y-%m-%d %H:%M` (refine) — the normalizer erases the date but NOT the
#   surviving `HH:MM`, so the header content also diverges if the two runs straddle
#   a minute boundary. Both are wall-clock leaks in cairn's own output that the
#   normalizer cannot erase; see the structured report for the precise observable.
# =============================================================================

NAME = "distill-refine-backfill"

# A mine-like candidates.jsonl. Three redis candidates cluster (Jaccard >= 0.50),
# two mongo candidates cluster, gradle is a singleton. Fixed key order so the
# member JSON re-dumped into the cluster files (and the model feed) is byte-stable.
CANDIDATES = (
    '{"name": "redis-timeout-triage", "description": "Diagnose redis lettuce command timeout latency."}\n'
    '{"name": "redis-latency-triage", "description": "Diagnose redis lettuce command timeout latency spikes."}\n'
    '{"name": "redis-command-timeout-fix", "description": "Fix redis lettuce command timeout latency triage."}\n'
    '{"name": "mongo-index-audit", "description": "Audit mongo compound index prefix coverage."}\n'
    '{"name": "mongo-index-prefix-audit", "description": "Audit mongo compound index prefix coverage dedup."}\n'
    '{"name": "gradle-cache-purge", "description": "Purge stale gradle build cache directories."}\n'
)

# The synthesized proposal the shim replays for EVERY cluster in a distill run
# (one CAIRN_SHIM_CLAUDE_OUT per invocation). Must open with "### " so refine's
# item splitter recognizes it.
DISTILL_OUT = (
    "### redis-timeout-triage\n"
    "Diagnose redis lettuce command timeout. Use when RedisCommandTimeoutException "
    "appears, when lettuce command timeout is ignored, when latency spikes after "
    "adding commons pool.\n"
    "1. Reproduce the timeout under load.\n"
    "2. Inspect the command-timeout configuration.\n"
    "3. Apply the fix and verify.\n"
    "Supported by: 3 candidate(s)"
)

# The refined batch the shim replays for a refine run: two proposals (scores 4 and
# 3) separated by a bare `---`, so the aggregator lands one in the "Highly
# reusable (4-5)" bucket and one in "Reusable with parameterization (3)".
REFINE_OUT = (
    "### redis-timeout-triage\n"
    "**Reusability: 4/5** - applies across any Spring or Lettuce Redis stack.\n"
    "Diagnose redis lettuce command timeout. Use when RedisCommandTimeoutException "
    "appears or lettuce command timeout is ignored.\n"
    "1. Reproduce under load.\n"
    "2. Inspect the command-timeout config.\n"
    "3. Fix and verify.\n"
    "\n"
    "---\n"
    "\n"
    "### mongo-index-prefix-audit\n"
    "**Reusability: 3/5** - one setup but parameterizable per collection.\n"
    "Audit mongo compound index prefixes. Use when reviewing index coverage or "
    "removing redundant prefixes.\n"
    "1. List the indexes.\n"
    "2. Find redundant prefixes.\n"
    "3. Drop the redundant ones."
)


def run(ctx):
    # install: baseline tree + skills git (distill/refine never commit -> the git
    # log stays here for the whole scenario).
    ctx.run("install")

    # -- distill DIE paths (before candidates exist) ---------------------------
    ctx.run("distill")            # default candidates.jsonl absent -> die (rc 1)
    ctx.run("distill", "--bogus") # unknown option -> die during arg parse (rc 1)

    # -- seed the mine-like candidates fixture --------------------------------
    ctx.seed("cairn/harvest/candidates.jsonl", CANDIDATES)

    # -- distill --dry-run: mechanical clustering + eligibility, NO model call --
    ctx.run("distill", "--dry-run")                         # eligible=2, up to 60
    ctx.run("distill", "--dry-run", "--threshold", "0.9")   # tight -> 0 multi-clusters
    ctx.run("distill", "--dry-run", "--min-cluster", "3", "--max-clusters", "5")  # eligible=1

    # -- distill FAILURE path: rc2 deterministic-fail quarantines every cluster --
    #    (.failed stamps), keeps going, writes a proposal-less PROPOSALS.md.
    ctx.run("distill", env={"CAIRN_SHIM_CLAUDE_RC": "2"})

    # -- distill TRANSIENT-HALT: rc1 + --max-retries 0 -> HALT on the first
    #    cluster (no sleep), "Stopped early", exit 1. The .failed clusters aren't
    #    .done, so they're still eligible here; nothing is stamped .done.
    ctx.run("distill", "--max-retries", "0", env={"CAIRN_SHIM_CLAUDE_RC": "1"})

    # -- distill SUCCESS: --reset clears the .failed stamps, --model opus flows to
    #    the shim arg log, --max-members 1 truncates each cluster feed to 1 member.
    #    Synthesizes both eligible clusters -> proposals/*.md + .done stamps +
    #    PROPOSALS.md (distill format).
    ctx.run("distill", "--reset", "--model", "opus", "--max-members", "1",
            env={"CAIRN_SHIM_CLAUDE_OUT": DISTILL_OUT})

    # -- distill RESUME: both clusters .done -> "skip (done)" x2, synthesized 0,
    #    but STILL rebuilds/overwrites PROPOSALS.md (no backup — distill overwrites).
    ctx.run("distill", env={"CAIRN_SHIM_CLAUDE_OUT": DISTILL_OUT})

    # -- refine DIE paths ------------------------------------------------------
    ctx.run("refine", "--bogus")                                     # unknown option -> die
    ctx.run("refine", str(ctx.claude_dir / "cairn/harvest/nodir"))   # missing SRC dir -> die

    # -- refine --dry-run: splits proposals into items, reports batch plan, NO
    #    model call and NO backup (returns before the backup line).
    ctx.run("refine", "--dry-run")                 # 2 items -> 1 batch of 8
    ctx.run("refine", "--dry-run", "--batch", "1") # 2 items -> 2 batches of 1

    # -- refine FAILURE path: rc2 quarantines the batch (.failed), but refine
    #    STILL backs PROPOSALS.md up and rewrites it (0 proposals -> "_None._").
    ctx.run("refine", env={"CAIRN_SHIM_CLAUDE_RC": "2"})

    # -- refine SUCCESS: batch isn't .done (only .failed) -> refined; atomic `mv`
    #    of the batch output into refine/out/, .done stamp, backup-before-write,
    #    PROPOSALS.md rewritten in refine format. --model/--min-score exercised.
    ctx.run("refine", "--model", "opus", "--min-score", "5",
            env={"CAIRN_SHIM_CLAUDE_OUT": REFINE_OUT})

    # -- refine RESUME: batch .done -> "skip (done)", refined 0, still backs up +
    #    rewrites PROPOSALS.md identically (proves batch resume-stamp determinism).
    ctx.run("refine", env={"CAIRN_SHIM_CLAUDE_OUT": REFINE_OUT})

    # -- refine --reset: clears .done/out/items/batches, re-splits + re-refines
    #    cleanly (final PROPOSALS.md byte-asserted from this run).
    ctx.run("refine", "--reset", env={"CAIRN_SHIM_CLAUDE_OUT": REFINE_OUT})
