<div align="center">

# Cairn

**A self-improving skill and memory system for Claude Code.**

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![For Claude Code](https://img.shields.io/badge/for-Claude%20Code-8A63D2)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-informational)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Bash](https://img.shields.io/badge/bash-3.2%2B%20(reference)-lightgrey)
![Status](https://img.shields.io/badge/status-in%20development-orange)

by [nefsir](https://github.com/nefsir)

</div>

```text
                   .-~-.
                  (     )             ___      _      ___   ___   _  _
                   `-~-'            / __|    /_\    |_ _| | _ \ | \| |
               .-~~~~~~~-.          | (__    / _ \    | |  |   / | .` |
              (           )          \___|  /_/ \_\  |___| |_|_\ |_|\_|
               `-~~~~~~~-'
            .-~~~~~~~~~~~~~-.         self-improving skills & memory
           (                 )            for Claude Code
            `-~~~~~~~~~~~~~-'
        .-~~~~~~~~~~~~~~~~~~~~~-.
       (                         )
        `-._-._-._-._-._-._-._-._'
   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

   every session leaves a stone that marks the trail
```

A cairn is a pile of stones that travellers add to one at a time, marking the
trail for everyone who comes after. Cairn does the same for your work: each
session leaves a stone — a reusable skill, a learning, a note about how you like
things done — so the next session starts already knowing the way. Everything is
plain files in a git repo, so you can read, diff, and revert every stone.

> **Status:** in active development. Follow [`CHANGELOG.md`](CHANGELOG.md) for progress.

---

## Contents

- [What Cairn does](#what-cairn-does)
- [Quick start](#quick-start)
- [Requirements &amp; platforms](#requirements--platforms)
- [Core ideas](#core-ideas)
- [The loop](#the-loop)
- [The `cairn` command](#the-cairn-command)
- [Layout](#layout)
- [Documentation](#documentation)
- [Safety &amp; design](#safety--design)
- [Non-goals](#non-goals)
- [License](#license)

---

## What Cairn does

- **Captures skills from your work.** When a session produces a reusable
  procedure, debugging pattern, or convention, Cairn turns it into a skill
  document Claude loads automatically next time a similar task comes up.
- **Improves skills as you use them.** When a loaded skill turns out wrong,
  incomplete, or outdated, Cairn patches it in place — and when you correct
  Claude's style or approach, that correction is folded into the skill that
  governs the task, not just remembered loosely.
- **Remembers who you are and how you work.** A small, bounded user model and a
  notes file persist across sessions, so you stop re-explaining context.
- **Keeps the library healthy.** A curator periodically consolidates overlapping
  skills into broader "umbrella" skills, retires ones that stop being used, and
  flags skills that score poorly in practice.
- **Backfills from your history.** A one-time pipeline mines your past sessions,
  distils thousands of candidates into a handful of clean proposals, and scores
  them for reusability — so you start with a library, not a blank slate.

## Quick start

```bash
# get it
git clone https://github.com/nefsir/cairn && cd cairn

# fresh install, or migrate an existing skill setup in place
./cairn-setup.sh

# turn on automatic post-session review (optional, reversible)
./cairn-setup.sh --enable-hooks

# see the library at a glance
cairn status
```

The installer copies the dispatcher into `~/.claude/cairn/`, links `cairn` onto
your `PATH` (`~/.local/bin`), lays down the commands, templates, and memory
files, and swaps in the managed `CLAUDE.md` block. It is idempotent and
reversible (`cairn uninstall`). Start a new Claude Code session afterwards so the
skills and commands load.

Already have a skill setup? See [`docs/MIGRATION.md`](docs/MIGRATION.md) — your
existing skills are scored and curated like any other, nothing is walled off.

## Requirements &amp; platforms

- **Claude Code** with CLI access (`claude`).
- **python 3.11+** — Cairn is a single cross-platform Python program that runs
  **natively on Linux, macOS, and Windows** (no shell or coreutils dependency).
- A behavior-preserving **bash 3.2+** implementation ships alongside as the reference
  oracle (`bin/cairn.bash`). A differential golden-master harness
  (`tests/diff-harness`) proves the Python port **byte-for-byte identical** to it on
  macOS/Linux — same output, files, exit codes, and git state — and CI runs both on
  every push (see `port/PLAN.md`). Windows-specific backends (Task Scheduler, power
  probe) are validated by the Windows CI runner.

## Core ideas

**Skills are class-level, not one-off.** A good skill captures *how to do a class
of task* — "diagnose a metrics-not-appearing problem", not "fix the March 12
incident". One broad skill with labelled subsections beats five narrow siblings.
The test: erase the proper nouns (service names, hostnames, ticket IDs). If a
procedure remains, it's a skill. If nothing remains, it was a runbook — keep it
as a reference file, not a skill.

**A skill is a directory** — a `SKILL.md` (YAML frontmatter with `name` +
`description`, then a Markdown body), plus optional support files:

| Directory | Holds |
|---|---|
| `references/` | session-specific detail and condensed knowledge banks |
| `templates/` | starter files meant to be copied and modified |
| `scripts/` | re-runnable actions the skill invokes |

**Two kinds of feedback live beside each skill.** `learnings.md` records what was
learned about the *task*; `usage.md` records whether activating the skill was
*worth it* (a 1-5 rating per use) — which feeds the curator and the improver.

**Memory is separate from skills, and bounded.** Two small, char-capped files
under `~/.claude/memories/`: `USER.md` (who you are: preferences, style) and
`MEMORY.md` (environment facts, conventions, tool quirks). Memory captures *who
you are and the state of things*; skills capture *how to do a class of task*.

**What Cairn does NOT capture** (these harden into constraints that bite later):
environment-dependent failures (capture the *fix*, not "X is broken"), negative
claims about tools, transient errors that resolved on retry, and one-off task
narratives.

## The loop

Cairn runs as two layers.

**Layer A — backfill (one-time).** `cairn mine` -> `cairn distill` -> `cairn refine`:
extract candidates from past sessions, cluster thousands into a few clean
proposals, generalize and score them 1-5. Review, then scaffold the good ones.

**Layer B — the ongoing closed loop.**

- **review** — after a session: patch a skill loaded this session -> else patch an
  existing umbrella -> else add a support file -> else create a new class-level
  skill; update `usage.md`, append honest `learnings.md`, write preferences/facts
  to memory. Runs via the `SessionEnd` hook (opt-in) or as a soft rule in `CLAUDE.md`.
  With hooks on, the `cairn-status` mod (`assets/mods/cairn-status`, loaded through
  `CLAUDE_CODE_PLUGIN_DIRS`) shows the review queue under the prompt and toasts a
  failed review or one that changed skills; `cairn uninstall` removes it.
- **curate** — consolidate overlapping skills into umbrellas; move unused skills
  through a lifecycle (active -> stale -> archived; archive is recoverable, never
  deleted); flag low-usefulness ones.
- **improve** — the nightly picker selects skills with enough eval cases and fresh
  signal, worst-rated first, and runs an eval -> fix -> re-eval pass.

## The `cairn` command

```text
cairn mine | distill | refine      Layer A backfill
cairn review                       run the post-session review now
cairn curate                       consolidation + lifecycle report (read-only)
cairn curate --merge | --archive-weak    batch consolidation (preview unless --yes)
cairn improve                      improvement pass (eval -> fix -> re-eval)
cairn maintain                     the nightly job: improve + inactivity-archive
cairn schedule [HH:MM] | --off     run maintain nightly (launchd / cron)
cairn status                       health dashboard
cairn lint [name]                  validate skill frontmatter
cairn suggest "<text>"             skills matching a prompt (the use-side hook)
cairn memory                       read / append / trim USER.md & MEMORY.md
cairn pin | unpin <name>           freeze a skill from auto-curation
cairn install | migrate | uninstall
cairn test | --version
```

Slash commands inside Claude Code (manual overrides; the default path is the
review loop): `/skill-new`, `/skill-improve`, `/skill-merge`, `/skill-fold`,
`/skill-review`, `/learn`.

## Layout

```text
~/.claude/
  CLAUDE.md                 managed block: the review rule + command index
  memories/USER.md  MEMORY.md          bounded memory
  skills/<name>/
    SKILL.md  references/ templates/ scripts/
    learnings.md  usage.md  .meta  evals/{cases,runs}.md
  cairn/
    bin/cairn               the dispatcher (Python entry)
    port/cairn/             the Python package (self-contained deploy)
    assets/mods/cairn-status/  Claude Code mod: review queue in the status line
    harvest/ skill-archive/ logs/
  commands/                 slash commands
```

Your skills stay in `~/.claude/skills`, where Claude Code loads them. Cairn's own
state lives under `~/.claude/cairn/`. Nothing is hidden in a database — it's all
files you can open.

## Documentation

| Doc | What's in it |
|---|---|
| [`docs/concepts.md`](docs/concepts.md) | The mental model: skills, memory, the on-disk layout |
| [`docs/the-loop.md`](docs/the-loop.md) | The two layers — backfill and the ongoing loop — and how they chain |
| [`docs/meta-format.md`](docs/meta-format.md) | The `.meta` format and the bounded-memory format |
| [`docs/review-tree.md`](docs/review-tree.md) | The post-session review rule, in full |
| [`docs/curator-rules.md`](docs/curator-rules.md) | How `cairn curate` consolidates and ages skills |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Common symptoms and their fixes |
| [`docs/MIGRATION.md`](docs/MIGRATION.md) | Upgrading an existing skill setup, safely and in place |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |

## Safety &amp; design

- **Everything is a file in git** — inspect and revert every change.
- **Never deletes** — the most destructive action is archiving (a move git and
  `skill-archive/` both preserve).
- **Idempotent and backed up** — re-running install/migrate is safe.
- **Your skills are assessed, not walled off** — migration scores every existing
  skill the same way it scores a new one; only plugin/registry skills and ones you
  explicitly `pin` are left untouched.
- **Bounded by design** — memory is char-capped, descriptions are capped, the
  system stays small on purpose.
- **Local by default** — the only thing that leaves your machine is the text
  Cairn sends to `claude -p` (mining, review, assessment, improvement). That text
  is flattened from your transcripts with best-effort secret redaction first;
  everything else — skills, memory, `.meta`, logs — is local files in git.

## Non-goals

Cairn deliberately does **not** include a full-text search index (Claude Code's
native skill loading covers discovery), a background memory daemon, multi-platform
messaging, model fine-tuning, or any component that rewrites Cairn's own code. If
a feature isn't "skill store, memory, or the two loops", it doesn't go in.

## License

[MIT](LICENSE) (c) 2026 [nefsir](https://github.com/nefsir)
