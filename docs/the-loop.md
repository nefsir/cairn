# The loop

Cairn runs as two layers. Layer A is a one-time backfill — it turns the
transcripts you already have into a starting library. Layer B is the ongoing
loop that keeps that library honest as you keep working. Each layer is a chain
of `cairn` subcommands; everything they touch is a plain file under
`~/.claude`, so you can read, diff, and revert every stone they leave.

---

## Layer A — backfill (one-time, resumable)

You run this once, by hand, when you adopt Cairn: `mine` → `distill` → `refine`.
Nothing here writes to `skills/`. The output is a single reviewable document,
`~/.claude/cairn/harvest/PROPOSALS.md`, that each step rewrites in place. You
scaffold the good ones yourself with `/skill-new`.

### `cairn mine` — transcripts → candidates

```bash
cairn mine                 # sessions whose cwd is under the current directory
cairn mine --all --since 90  # every project, last 90 days
cairn mine ~/work --dry-run  # show what would be sent + a rough token estimate
```

`mine` discovers past session transcripts, flattens each one, and sends it
through a single scoped `claude -p` call that emits zero or more candidate
skills as JSON Lines. Candidates accumulate in `harvest/candidates.jsonl`.

It is **resumable by design**. Every finished session drops a stamp in
`harvest/.mined/`, so a re-run skips what it already mined. A session that fails
deterministically is quarantined (retry it later with `--retry-failed`); a
persistent rate-limit or network error *halts* the run without marking that
session done — you just run `cairn mine` again to pick up where it stopped. When
the candidate file is non-empty, `mine` writes a first-pass `PROPOSALS.md`.

### `cairn distill` — cluster candidates → synthesized proposals

```bash
cairn distill                  # cluster, then synthesize one skill per cluster
cairn distill --threshold 0.4  # looser grouping
cairn distill --dry-run        # how many clusters are eligible, no model calls
```

A few thousand raw candidates is not a library. `distill` clusters them by
trigger-word overlap (a pure-python Jaccard pass, no model), then sends each
cluster of size ≥2 through `claude -p` to synthesize **one** proposed skill —
a kebab-case name, a description that is the *deduplicated union* of the
distinct triggers, a short procedure, and a `Supported by: N candidate(s)`
line. It rewrites `PROPOSALS.md`, ordered by supporting evidence. Per-cluster
`.done` stamps make this resumable too.

### `cairn refine` — generalize + reusability-score

```bash
cairn refine               # generalize each proposal, score 1-5, re-rank
cairn refine --min-score 4 # (scores are always emitted; tune the cut yourself)
```

`refine` splits the distilled proposals into individual items, batches them, and
asks `claude -p` to judge each one's reusability **1–5** and rewrite it toward
project-agnostic form *where honest* — stripping service names and incident IDs
into general language, but leaving a genuine one-off specific and scoring it low.
The final `PROPOSALS.md` is sorted into three bands: highly reusable (4–5) at the
top, parameterizable (3) in the middle, probably-skip (1–2) at the bottom. Read
from the top, scaffold the keepers with `/skill-new`, and the backfill is done.

---

## Layer B — the ongoing loop

Once you have a library, three subcommands keep it alive: `review` after a
session, `curate` to consolidate and age skills out, `improve` to sharpen the
ones that score poorly. A fourth piece — `suggest` — closes the loop on the
*use* side, so the library you build actually gets used.

### `cairn suggest` — surface the right skill at decision time

A big library is worthless if nobody re-reads the index before acting. `suggest`
scores the prompt against every skill (IDF-weighted token overlap; diacritic-
folded and prefix-tolerant, so it matches PL/EN and inflected forms; optional
`keywords:` are weighted higher; `platforms:` hides off-OS skills) and, via a
`UserPromptSubmit` hook (installed by `--enable-hooks`), injects the top matches
as a "Skill check" note the moment a task starts. It's local and instant (no
model call) and silent below a threshold (`CAIRN_SUGGEST_THRESHOLD`, default 5)
so chat turns aren't spammed. `cairn suggest "<text>"` runs the matcher by hand.

**Names-only safety net.** A token-overlap *false negative* — the right skill exists
but scored just under the bar — should not vanish silently. So when nothing clears
the match bar but the prompt is topically **warm** (best score ≥
`CAIRN_ROSTER_FLOOR`, default 2.0), the hook falls back to a softer note listing the
**near-miss names** — every skill with *any* token overlap, ranked by score — so a
missed skill stays one `Skill` call away. Three bands: *strong* → the match note;
*warm* → the near-miss roster; *cold* (chatter/off-topic, best < floor) → silent.
Zero-overlap skills are **not** listed on purpose: a name buried in an unranked tail
is a needle-in-a-haystack, and it costs tokens every warm turn for ~no recall. A
genuine zero-overlap miss is recovered with `cairn suggest "<other words>"` (the
note points at it via `(+N more)`), which is targeted, not eyeballing the whole
library. This complements — does not replace — Claude Code's own native skill
listing (cairn leaves `skillListingBudgetFraction` alone; an earlier version set it
to `0`, but that is an undocumented value Claude Code rejects). Tunables:
`CAIRN_SUGGEST_ROSTER=0` disables it; `CAIRN_ROSTER_MAX` (default 40) ceilings the
list for very common words (`0` = uncapped). Modelled on a **names-only
category demotion**, which keeps names visible when descriptions are
dropped under context pressure.

> **Mid-task re-surface (opt-in, best-effort).** `cairn suggest --tick` exists for
> a `PostToolUse` hook that re-surfaces every Nth tool call (`CAIRN_SUGGEST_TICK`).
> It is **not** installed by default: Claude Code's `PostToolUse` `additionalContext`
> is only an advisory system reminder, not fed into the model's reasoning stream,
> so it's a weak nudge for per-call overhead. Wire it manually if you want to
> experiment; the prompt-time hook above is the reliable lever.

### `cairn review` — after a session

This is the heart of the loop. `review` flattens the transcript that just ended
and runs one scoped `claude -p` pass that *acts on files* — it does not chat. It
walks a decision tree, stopping at the first rung that fits:

1. patch a skill loaded this session (fix a step, add a pitfall, broaden a trigger),
2. else patch an existing umbrella skill,
3. else add a support file (`references/`, `templates/`, `scripts/`) with a one-line
   `SKILL.md` pointer,
4. else create a new **class-level** skill from the template.

It also appends an honest `usage.md` line for any skill it used, dated
`learnings.md` lines for corrections, and routes durable facts to memory via
`cairn memory`. Cairn then commits the change to git. The same decision tree
lives as a soft rule in the managed `CLAUDE.md` block, so the agent applies it
mid-session even when nothing automated runs.

**When it runs.** Two ways, same code path:

```bash
cairn install --enable-hooks   # register a SessionEnd hook
cairn review                   # or run it by hand on the last session
cairn review path/to/transcript.jsonl --dry-run   # show what it would do
```

With the hook on, `review --hook` fires automatically when a session ends; it
finds the transcript from the hook payload and reviews silently to a log. The
hook is opt-in, backed up when installed, and removed cleanly by
`cairn uninstall`. (A recursion guard stops the hook's own `claude -p` from
firing a nested review.) Or trigger the same pass yourself inside Claude Code
with `/skill-review`, or distill the current session into a skill with `/learn`.

### `cairn curate` — consolidate + age out (read-only by default)

```bash
cairn curate                       # write a report, change nothing
cairn curate --apply-lifecycle     # also move stale/idle skills through states
```

`curate` is **read-only by default** — it writes `harvest/CURATE.md` and prints
the head of it. The analysis is pure python (no model calls): it flags three
things. *Merge candidates* — clusters of skills whose triggers overlap, each
with a ready-to-paste `/skill-merge a b c` line. *Fold candidates* — skills
whose `learnings.md` has grown past ~15 entries, ready for `/skill-fold`.
*Low-usefulness* — skills that scored poorly across real `usage.md` ratings,
ready for `/skill-improve`. It also proposes **lifecycle transitions** by
inactivity: active → stale → archived. Merges and folds are always manual; only
`--apply-lifecycle` acts, and the most destructive thing it does is *archive*
(a `git`-tracked move into `skill-archive/`, never a delete). Pinned and bundled
skills are never auto-transitioned.

### `cairn improve` — eval → fix → re-eval

```bash
cairn improve                      # pick the neediest skills, improve them
cairn improve mysql-read-latency-triage   # one named skill
cairn improve --dry-run            # show who would be picked
```

`improve` only touches skills that are *ready*: at least 5 eval cases in
`evals/cases.md` **and** fresh signal (a `learnings.md` or `usage.md` change
since the last improve run). It picks worst-rated first. For each, one
autonomous `claude -p` iteration executes every eval case against `SKILL.md`,
grades the pass rate, applies minimal targeted edits, re-runs the failures, and
logs before → after to `evals/runs.md`. Cairn commits the result. This is the
pass meant to run unattended — `--battery-skip` even bows out on laptop battery.

### `cairn maintain` / `cairn schedule` — run the gentle pass nightly

```text
cairn maintain            # improve + curate --apply-lifecycle, now (one run, locked)
cairn schedule 03:30      # run maintain nightly via launchd (macOS) / cron (Linux)
cairn schedule --off      # remove the schedule
```

`maintain` is the **safe** subset meant to run on its own: it runs `improve`
(sharpen ready skills) and `curate --apply-lifecycle` (archive skills idle 90d+,
recoverable). It deliberately does **not** auto-merge or quality-archive — those
need your judgement, so `curate --merge` and `curate --archive-weak` stay manual.
`schedule` is opt-in and reversible; because `improve` calls the model, the
nightly run spends some tokens while you sleep.

---

## How it chains

```text
Layer A (once):   mine ──▶ distill ──▶ refine ──▶ PROPOSALS.md ──▶ /skill-new
Layer B (always): review (each session) ──▶ curate (consolidate + age) ──▶ improve (sharpen)
```

Layer A hands you a library instead of a blank slate. From then on, every
session leaves a stone: `review` adds and patches, `curate` keeps the pile
tidy, `improve` makes the stones you lean on most the most reliable. Check the
whole thing at a glance with `cairn status`.
