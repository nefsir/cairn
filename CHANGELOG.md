# Changelog

All notable changes to Cairn are documented here.
Format loosely follows Keep a Changelog; dates are ISO-8601.

## [Unreleased] — 2.0 (Cairn)
The 2.0 rewrite. One `cairn` dispatcher, every artifact a plain file in git.

### Added
- **`cairn` dispatcher** (`bin/cairn`) — one entry point replacing the v1
  `skill-*.sh` sprawl: `mine | distill | refine | review | curate | improve |
  status | memory | pin | unpin | provenance | install | migrate | uninstall |
  test`, plus `--version`, `--help`, and a no-arg banner.
- **`.meta` per skill** (`lib/meta.py`) — provenance (managed/bundled), pinned,
  lifecycle state, created/last_used/last_patched, use_count, quality score.
  Atomic, never clobbers, canonical key order.
- **Bounded memory** (`lib/memory.py`) — `memories/USER.md` (1375) +
  `MEMORY.md` (2200), char-capped, `§`-delimited; `cairn memory` reads / adds /
  replaces / removes / trims, rejecting over-cap writes.
- **Review loop** — one managed `CLAUDE.md` block (decision tree + do-not-capture
  guardrails + preference→skill-body routing + memory boundary + mid-session
  nudge) and `cairn review` (silent, scoped, redacted transcript → one `claude -p`).
  Opt-in `SessionEnd` hook with a recursion guard.
- **Umbrella curator** (`cairn curate`) — trigger-overlap clustering framed as
  umbrella-building, fold + low-usefulness flags, and a lifecycle
  (active → stale@30d → archived@90d) that **moves, never deletes**; pinned and
  bundled skills are protected. Read-only by default; `--apply-lifecycle` applies.
  Batch modes for large libraries (preview unless `--yes`, archive-only):
  `cairn curate --merge` auto-consolidates overlapping clusters into umbrellas;
  `cairn curate --archive-weak [--assess]` archives low-quality/low-usefulness skills.
- **Backfill** — `mine` / `distill` / `refine` ported onto shared, resumable
  `claude -p` resilience and the lib helpers; best-effort secret redaction.
- **Improvement picker** (`cairn improve`) — eval → fix → re-eval, worst-rated /
  lowest-quality first, only skills with ≥5 cases and fresh signal.
- **Nightly maintenance** — `cairn maintain` (improve + inactivity-archive only,
  never auto-merge/quality-delete) and `cairn schedule [HH:MM]` to run it via
  launchd (macOS) / cron (Linux); reversible with `cairn schedule --off`.
- **Migration** that assesses existing skills (scores them 1–5 into `.meta`)
  rather than walling them off; only `bundled` and `pinned` skills are exempt.
- **Use-side surfacing** — `cairn suggest` scores a prompt against the library
  (IDF-weighted token overlap, diacritic-folded + prefix-tolerant so it matches
  PL/EN and inflected forms; optional `keywords:` / `platforms:` frontmatter;
  silent on chatter) and a `UserPromptSubmit` hook pushes the top matches forward
  at the moment a task starts — so a large library actually gets used, not just
  stored. Installed alongside the review hook by `--enable-hooks`. It complements
  Claude Code's own native skill listing (which already collapses the long tail to
  bare names under its context budget) rather than replacing it — cairn does **not**
  touch `skillListingBudgetFraction`.
  **Names-only safety net** — a ranked, prompt-relevant fallback: when no skill
  clears the match bar but the prompt is topically *warm* (best score ≥
  `CAIRN_ROSTER_FLOOR`, default 2.0), the hook lists the **near-miss** skill names
  — every skill with any token overlap, ranked by score — so a token-overlap false
  negative stays one `Skill` call away (a names-only category demotion — keep names
  visible when descriptions drop). Zero-overlap skills are deliberately *not* dumped: a name buried in an
  unranked tail is a needle-in-a-haystack; a true zero-overlap miss is recovered
  with `cairn suggest "<other words>"`. Silent on chatter/off-topic (cold band);
  disable with `CAIRN_SUGGEST_ROSTER=0`; `CAIRN_ROSTER_MAX` (default 40) ceilings
  the list for very common words. A mid-task
  re-surface (`cairn suggest --tick`, `PostToolUse`) exists but is OFF by default
  and opt-in: `PostToolUse` context is only an advisory system reminder, so it's a
  weak nudge for per-call overhead — the prompt-time hook is the reliable lever.
- **`cairn lint`** — programmatic frontmatter validation (name, description
  ≤1024, non-empty body); surfaced in `cairn status` and gating the merge mode.
- **`cairn test`** — static (`bash -n` under the real `/bin/bash` for the
  bash-3.2 contract, `py_compile`, optional `shellcheck`),
  unit (the `lib/` helpers in isolation), integration (install / migrate / review
  / curate in a throwaway `$HOME` with shimmed `claude`/`crontab`/`pmset`,
  asserting idempotency and that installed assets are byte-identical to source).
- **Packaging** — `cairn-setup.sh` bootstrap, MIT license, this changelog, the
  `docs/` set (concepts, the loop, `.meta` format, the review tree, curator
  rules, troubleshooting), ASCII banner.

## [1.x] — prior (claude-skill-system)
- Single-file installer; skill mining, distillation (map-reduce clustering),
  reusability refinement; read-only audit; status dashboard; nightly auto-improve
  picker (usefulness-prioritized); usage-rating loop; slash commands
  (/learn, /skill-new, /skill-improve, /skill-merge, /skill-fold).
- Preserved locally as the basis for the 2.0 port.
