import json

NAME = "mine-backfill"

# Golden master for the backfill miner (cmd_mine in bin/cairn -> lib/transcript.py
# discover/flatten + the shared run_claude rc contract). Exercises the WHOLE mine
# surface and asserts, per step, exit code + stdout + stderr AND the resulting tree
# (the harness diffs the full $CLAUDE_DIR: the .mined/ stamps, candidates.jsonl,
# PROPOSALS.md, cairn/logs/mine.log) + the deterministic `claude` shim logs
# (.claude-calls / .claude-stdin.N — the redaction/flatten + model-arg oracle).
#
# No `install` step on purpose: mine is Layer-A backfill (the help lists it under
# "Backfill (Layer A, one-time)", separate from install under "Lifecycle"). cmd_mine
# is self-contained — it mkdir -p's its own $STATE/harvest + $STATE/logs, reads only
# $CLAUDE_DIR/projects, and never touches skills/ — so it runs on a bare tree. This
# also keeps the golden master focused on mine and its wall-clock footprint small.
#
# Because the deterministic `claude` shim selects its rc purely from the per-step
# CAIRN_SHIM_CLAUDE_RC env (it does NOT branch on argv/stdin), the three rc paths
# (0 ok / 1 transient-HALT / 2 deterministic-fail) are driven by env on the whole
# mine step, with a single un-mined session per rc!=0 step so the outcome is
# unambiguous. --max-retries 0 on the transient (rc1) step is REQUIRED: run_claude
# retries transients with sleep attempt^2 * 5s (5+20+45 with the default 3), which
# would both hang the harness and blow up the wall-clock footprint.
#
# Session files are named 01..05 so that alphabetical order == seed order; discovery
# sorts by (mtime, path) descending, so the processing order is a stable reverse
# 05,04,03,02,01 regardless of whether the sub-second mtimes tie (then path breaks
# the tie the same relative way in both homes). --all is used everywhere so match is
# independent of the sandbox $HOME (which the transcript cwd can't know at authoring
# time); one step uses a positional ROOT to prove the cwd-scoped no-match path.
#
# Determinism note (a genuine cairn finding, reported out-of-band, NOT masked here):
# cmd_mine writes PROPOSALS.md with `date '+%Y-%m-%d %H:%M'` (minute granularity, no
# seconds). The harness normalizer only erases the second-granularity `%H:%M:%S` that
# `say` emits; the bare `%H:%M` in the PROPOSALS.md header survives as `<DATE> 12:34`
# and would differ if the oracle and candidate runs straddle a minute boundary. Every
# other observable here is fully deterministic.

CWD = "/work/demo-project"  # baked into each transcript; only surfaces in dry-run/discover

# The scripted extractor/aggregator output. Mixed lines prove the candidates.jsonl
# shape filter (grep '^[[:space:]]*\{.*\}[[:space:]]*$'): only the two brace-delimited
# object lines survive (leading whitespace is kept verbatim); the prose line and the
# object-with-trailing-junk line are dropped.
CAND_OUT = (
    "Here is prose the shape filter must drop.\n"
    '{"name":"flux-precondition-debug","description":"Debug an unexpectedly empty reactor Flux. '
    'Use when a Flux completes empty and a downstream step is silently skipped.",'
    '"evidence":"recurred across several services","procedure":"trace the upstream publisher; add switchIfEmpty"}\n'
    '{"name":"json-with-trailing"} <- trailing text means this whole line is dropped\n'
    '  {"name":"reactor-retry-backoff","description":"Bounded retry with exponential backoff. '
    'Use when a transient downstream error should be retried a few times.",'
    '"evidence":"a common resilience pattern","procedure":"retryWhen with capped attempts"}'
)


def _transcript(*turns):
    # Build a Claude Code JSONL session: first line carries cwd for discover().
    lines = []
    for i, (role, text) in enumerate(turns):
        obj = {"type": role, "message": {"content": text}}
        if i == 0:
            obj["cwd"] = CWD
        lines.append(json.dumps(obj, ensure_ascii=False))
    return "\n".join(lines) + "\n"


T01 = _transcript(("user", "Investigate why the nightly batch job stalls"),
                  ("assistant", "It was lock contention; add an index and shorten the txn"))
T02 = _transcript(("user", "Refactor the payment retry logic"),
                  ("assistant", "Extract a backoff helper and cap the attempts"))
T03 = _transcript(("user", "Debug the empty flux precondition"),
                  ("assistant", "Add switchIfEmpty and verify the upstream publisher"))
T04 = _transcript(("user", "Speed up the mongo aggregation query"),
                  ("assistant", "Add a compound index on status and createdAt"))
T05 = _transcript(("user", "Fix the flaky spock test"),
                  ("assistant", "Inject the clock and drop the real sleep"))

RC1 = {"CAIRN_SHIM_CLAUDE_RC": "1"}                                   # transient -> HALT
RC2 = {"CAIRN_SHIM_CLAUDE_RC": "2"}                                   # deterministic fail -> quarantine
RC0 = {"CAIRN_SHIM_CLAUDE_OUT": CAND_OUT}                             # success -> scripted candidates


def run(ctx):
    # 1. bare tree, no projects/ dir yet -> die "no transcripts dir", rc 1 (stderr).
    ctx.run("mine")

    # seed the two sessions that will be deterministically failed/quarantined.
    ctx.seed("projects/demo/01-fail-a.jsonl", T01)
    ctx.seed("projects/demo/02-fail-b.jsonl", T02)

    # 2. positional ROOT + default (non-all) scope: transcript cwd (/work/demo-project)
    #    is not under this root -> 0 matches -> "No matching transcripts", rc 0.
    ctx.run("mine", "/no/such/root")

    # 3. rc2 deterministic-fail over both sessions: each is quarantined to .failed and
    #    the loop CONTINUES to the next; 0 candidates -> "No candidates emitted", rc 0.
    ctx.run("mine", "--all", "--max-retries", "0", env=RC2)

    # 4. --retry-failed: rm the .failed stamps and re-extract; rc2 again re-quarantines
    #    (proves the retry re-ran the sessions), .failed preserved.
    ctx.run("mine", "--all", "--retry-failed", "--max-retries", "0", env=RC2)

    # 5. --reset: wipe every stamp + truncate candidates.jsonl, then re-mine from
    #    scratch; rc2 re-quarantines both -> .failed preserved, candidates empty.
    ctx.run("mine", "--all", "--reset", "--max-retries", "0", env=RC2)

    # seed the session that will HALT (transient) and later be resumed.
    ctx.seed("projects/demo/03-halt.jsonl", T03)

    # 6. rc1 transient with --max-retries 0: the newest un-mined session (03) HALTs
    #    immediately (no retry/sleep) -> exit 1, 03 left UNSTAMPED (resumable), the two
    #    .failed sessions are never reached, and NO PROPOSALS.md is produced on halt.
    ctx.run("mine", "--all", "--max-retries", "0", env=RC1)

    # seed the two clean sessions.
    ctx.seed("projects/demo/04-good-a.jsonl", T04)
    ctx.seed("projects/demo/05-good-b.jsonl", T05)

    # 7. normal mine (rc0) with a non-default --model: 05,04 mined, 03 RESUMED (the halt
    #    left no stamp), 02,01 skipped (.failed); the shape filter keeps 2 object lines
    #    per session -> candidates.jsonl, then aggregate -> PROPOSALS.md. --model haiku
    #    is echoed into the shim call log.
    ctx.run("mine", "--all", "--model", "haiku", "--max-retries", "0", env=RC0)

    # 8. --dry-run: list every discovered session (MSGS/AGE/cwd) + token estimate; sends
    #    nothing, mines nothing, writes no stamps.
    ctx.run("mine", "--all", "--dry-run")

    # 9. --dry-run with the remaining numeric knobs: --max-sessions caps the listing,
    #    --since sets the age window (all fresh -> all included), --max-chars re-scales
    #    the token estimate. Still no model calls.
    ctx.run("mine", "--all", "--dry-run", "--max-sessions", "2", "--since", "30", "--max-chars", "500")

    # 10. unknown option -> die "mine: unknown option ...", rc 1 (stderr).
    ctx.run("mine", "--all", "--frobnicate")
