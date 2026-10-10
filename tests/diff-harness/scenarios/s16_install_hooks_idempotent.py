DIVERGED = "review pipeline v2 (queue + detached worker); covered by tests/run-tests.sh"

NAME = "install-hooks-idempotent"

# Golden master for `cairn install --enable-hooks` and its idempotency, closing the
# "install --enable-hooks + idempotency" coverage gap. s07 wires the hooks once (to
# capture their JSON) but never re-runs install to prove the merge is a no-op, never
# asserts the exact three-way upsert in isolation, and never guards
# skillListingBudgetFraction. This scenario pins all three.
#
# What this pins (the harness diffs it all, oracle vs candidate, byte-for-byte):
#
#   * THE EXACT settings.json HOOK UPSERT (as JSON, captured in the tree snapshot).
#     enable_hooks() writes three groups under "hooks":
#       - SessionEnd  -> the review CAPTURE hook, WITH the recursion guard
#         `[ -n "${CAIRN_REVIEW_HOOK:-}" ] && exit 0; "<cairn>" review --hook >> "<log>" 2>&1`
#       - UserPromptSubmit -> `"<cairn>" suggest --hook 2>/dev/null || true`
#       - PostToolUse -> `"<cairn>" track --hook 2>/dev/null || true`, and this group
#         alone carries  "matcher": "Skill"  (the other two have no matcher key).
#     The absolute cairn-bin / review-hook.log paths inside the command strings live
#     under $CLAUDE_DIR, so the normalizer collapses them to <CLAUDE_DIR>/... in both
#     builds; the JSON shape, key order (json.dump indent=2), and the Skill matcher
#     are what a port must reproduce.
#
#   * IDEMPOTENCY / NO GRATUITOUS .bak CHURN. Step 2 re-runs `install --enable-hooks`.
#     enable_hooks() re-serialises the merged dict and compares it to the pre-merge
#     snapshot: since the three hooks are already present with identical command
#     strings, upsert() only reassigns h["command"] to the same value -> the JSON is
#     byte-identical -> it prints "cairn hooks already present (no change)" and NEVER
#     touches settings.json, so NO `settings.json.bak-<ts>` is created. The whole
#     provision pass is likewise idempotent (put -> "(unchanged)", swap_block -> "up
#     to date", stamp_meta/seed_feedback skip existing, skills_commit finds nothing
#     staged), so the final tree holds exactly one settings.json and zero backups.
#     A regression that rewrote settings.json on the second run would surface here as
#     both a changed step-2 stdout AND a spurious .bak path in the tree.
#
#   * skillListingBudgetFraction IS NEVER TOUCHED. cairn deliberately does not set
#     this key (an earlier version set it to 0, which Claude Code's validator
#     rejects). The captured settings.json is proof by absence: it contains ONLY the
#     "hooks" object and no "skillListingBudgetFraction". A port that re-introduced
#     the key would diverge on the settings.json file diff.
#
#   * status HOOK READBACK. Step 3 runs `status`, whose settings.json probe
#     (`grep -q 'cairn.*review'`) must now report `SessionEnd hook:   on` — the
#     branch s02/s04 (no hooks) never reach, tying the written JSON back to cairn's
#     own recognition of it.
#
# Determinism notes:
#   * FRESH install (no pre-seeded settings.json) is deliberate. enable_hooks() only
#     writes a `settings.json.bak-<YYYYMMDD-HHMMSS>` when it CHANGES an existing file;
#     a pre-existing settings.json would force exactly that timestamped backup on the
#     first hook-add. The harness normalizes file *contents* but compares the tree
#     *path set* raw (diff-cairn.py: `set(os_["tree"])`), so a second-granularity
#     .bak filename that lands on different seconds across the oracle vs candidate
#     runs would be an un-erasable path divergence. Driving a fresh install keeps the
#     changed->.bak branch out of the tree entirely, so the scenario stays a stable
#     golden master while still exercising the create + idempotent-no-op paths.
#   * No seeded skills -> the only skill is the bundled skill-extraction (created via
#     dir_date == today in BOTH builds, same calendar day) -> git tree hashes and the
#     status lifecycle math are identical; all absolute-date content collapses to
#     <DATE> under the normalizer. This mirrors the already-green s02.
#   * No model/shim calls: install runs with assess=0, so `claude` is never invoked
#     and no shim log is produced.


def run(ctx):
    # 1. fresh install WITH hooks -> creates settings.json holding exactly the three
    #    hook groups (SessionEnd review guard, UserPromptSubmit suggest, PostToolUse
    #    track matcher=Skill). No pre-existing settings.json -> no .bak is written.
    ctx.run("install", "--enable-hooks")

    # 2. run it AGAIN -> the merge is a no-op: "cairn hooks already present (no
    #    change)", settings.json byte-unchanged, no gratuitous settings.json.bak.
    ctx.run("install", "--enable-hooks")

    # 3. status must now recognise the written hook -> "SessionEnd hook:   on",
    #    exercising the readback branch that the hook-less scenarios never hit.
    ctx.run("status")
