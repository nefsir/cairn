# Concepts

The mental model behind Cairn. Read this once and the commands stop looking like
a grab-bag — they're all the same few ideas seen from different angles. Cairn is
a self-improving skill and memory system for Claude Code; every session leaves a
stone that marks the trail. This page explains what a stone is, where it lives,
and how the pieces relate.

## What a skill is

A skill captures *how to do a class of task* — not a single incident. "Diagnose
a metrics-not-appearing problem" is a skill. "Fix the March 12 outage on
checkout-api" is a runbook.

The test is simple: **erase the proper nouns.** Strike out the service names,
hostnames, ticket IDs, dates. If a usable procedure remains, you have a skill —
keep it. If nothing remains, you had a runbook — keep it as a reference file
inside a skill, not as a skill of its own.

This is why Cairn pushes toward *umbrella* skills. One broad skill with labelled
subsections beats five narrow siblings that each cover one variant. When the
curator finds overlap, it consolidates upward rather than letting the library
sprawl.

## A skill is a directory

Each skill is a folder under `~/.claude/skills/<name>/`. The only required file
is `SKILL.md`: YAML frontmatter with a `name` and a `description` (the
description is what Claude Code matches against to decide when to load the
skill), followed by a Markdown body — the actual procedure.

Everything else is optional support, and each kind has a job:

| Path | Holds |
|---|---|
| `references/` | session-specific detail, condensed knowledge banks |
| `templates/` | starter files meant to be copied and modified |
| `scripts/` | re-runnable actions the skill invokes |
| `learnings.md` | what was learned about the *task* |
| `usage.md` | whether activating the skill was *worth it* (1–5 per use) |
| `.meta` | provenance, pinned, state, quality, dates, use counts |
| `evals/cases.md` `evals/runs.md` | eval cases and their run history |

The two feedback files are distinct on purpose. `learnings.md` grows the
procedure ("the flag is `--strict`, not `--stron`"); `usage.md` rates the skill
itself ("activated but useless here, 1/5"). The first feeds `cairn improve`; the
second feeds the curator's low-usefulness flag.

## Skills vs. memory

Skills and memory answer different questions, and Cairn keeps them apart so the
review loop routes each correction to the right place.

- **Skills** answer *how do I do this class of task?* They live in
  `~/.claude/skills/`.
- **Memory** answers *who is this user, and what's the state of things?* It lives
  in two char-capped files under `~/.claude/memories/`:
  - `USER.md` — preferences and style (cap ~1375 chars).
  - `MEMORY.md` — environment facts, conventions, tool quirks (cap ~2200 chars).

Memory is bounded by design. When a file is full you trim, replace, or remove
before you add — the cap is enforced, not advisory:

```bash
cairn memory                              # read both files with char counts
cairn memory user add "prefers tabs, no emoji in commits"
cairn memory agent add "build needs JDK 21; gradle daemon flaky on CI"
cairn memory agent trim                   # drop oldest entries to fit the cap
```

A preference is *not* memory if it really governs a task — "always run the
formatter before committing this kind of change" belongs in the body of the
skill that governs that change, not loosely in `USER.md`. Routing corrections
into the governing skill is exactly what the review loop does.

What Cairn **does not** capture, in either store: environment-dependent failures
(capture the fix, not "X is broken"), negative claims about tools, transient
errors that resolved on retry, and one-off task narratives. These harden into
constraints that bite later.

## Provenance, state, and pinning

Every skill carries a `.meta` file that decides whether the curator may touch
it. Three fields matter most:

- **provenance** — `managed` means Cairn created or adopted it and may curate it;
  `bundled` means it shipped with a plugin or registry and Cairn leaves it alone.
- **pinned** — `true` freezes a skill from auto-curation regardless of
  provenance. Pin a skill you depend on and don't want consolidated or archived.
- **state** — the lifecycle position: `active` → `stale` (untouched ~30 days) →
  `archived` (~90 days). Archiving is the most destructive thing Cairn does, and
  it's a *move*, not a delete — the skill goes to `~/.claude/cairn/skill-archive/`
  and stays in git history. Pinned and `bundled` skills bypass the lifecycle.

Inspect the whole catalogue at once, and adjust:

```bash
cairn provenance --list                   # SKILL / PROVENANCE / PINNED / STATE / QUALITY
cairn pin mysql-read-latency-triage       # freeze it
cairn provenance some-skill bundled       # mark it hands-off
```

## On-disk layout

Nothing is hidden in a database. Your skills stay where Claude Code loads them;
Cairn's own working state lives under `~/.claude/cairn/`.

```text
~/.claude/
  CLAUDE.md                 managed block: the review rule + command index
  memories/
    USER.md  MEMORY.md      bounded, char-capped memory
  skills/<name>/
    SKILL.md
    references/  templates/  scripts/
    learnings.md  usage.md  .meta  evals/
  cairn/
    bin/cairn               the dispatcher
    harvest/                mine / distill / refine output
    skill-archive/          retired skills (recoverable, never deleted)
    logs/
  commands/                 slash commands (manual overrides)
```

## The two loops

Cairn runs as two layers. You meet them through the `cairn` command.

**Layer A — backfill (one-time).** Mine your past sessions into a starting
library so you don't begin from a blank slate:

```bash
cairn mine        # extract skill candidates from past transcripts
cairn distill     # cluster thousands of candidates into a few proposals
cairn refine      # generalize and reusability-score the proposals (1–5)
```

**Layer B — the ongoing closed loop.** Three primitives keep the library alive:

```bash
cairn review      # after a session: patch a loaded skill, else patch an umbrella,
                  #   else add a support file, else create a class-level skill;
                  #   update usage.md / learnings.md and write to memory
cairn curate      # read-only report: consolidate overlap into umbrellas, run the
                  #   lifecycle, flag low-usefulness skills
cairn improve     # eval → fix → re-eval pass, worst-rated first
```

`review` runs automatically via the `SessionEnd` hook if you opted in
(`cairn install --enable-hooks`); otherwise it lives as a soft rule in
`CLAUDE.md` and you run it by hand. `cairn status` is the dashboard tying it
together — library size, lifecycle state, whether the hook is on.

Inside Claude Code, the slash commands `/skill-new`, `/skill-improve`,
`/skill-merge`, `/skill-fold`, and `/learn` are manual overrides for the same
operations. The default path is the review loop; the commands are there when you
want to drive a single step yourself.

## The whole thing in one breath

A skill store and a bounded memory store, two loops over them, and a one-time
backfill to seed them — all plain files in git, every stone open to read, diff,
and revert.
