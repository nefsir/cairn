# The review rule

A cairn grows one stone at a time. The review rule is how each session adds its
stone — the post-session pass that decides what (if anything) the session taught
that's worth keeping, and where it belongs.

It runs in one of two places, with the same logic in both:

- **Automatically**, via the `SessionEnd` hook, when you've opted in with
  `./cairn-setup.sh --enable-hooks`. The hook runs `cairn review --hook`, which
  finds the just-ended transcript, flattens it, and hands it to one scoped
  `claude -p` pass that acts on files directly.
- **By hand**, as a soft rule in the managed `~/.claude/CLAUDE.md` block — you
  (or Claude) apply the tree at the end of a session — or on demand with the
  `/skill-review` command.

**Bias to action.** Most sessions produce at least one update. A pass that
captures nothing is usually a missed one, not a clean one. The review prompt and
the managed block both say so plainly.

## The update decision tree

Work top-down. **Stop at the first rung that fits** — you're placing one stone,
not rebuilding the trail.

1. **Patch a skill loaded or consulted this session.** If a skill already covers
   the territory, fix the wrong step, add the pitfall you hit, or broaden a
   `description` trigger so it fires next time. This is the common case.
2. **Else patch an existing umbrella skill.** Find the class-level skill the
   topic belongs under and broaden its `description` triggers or add a labelled
   subsection. You're extending coverage, not spawning a sibling.
3. **Else add a support file** under the nearest umbrella, plus a one-line
   pointer to it from `SKILL.md`:
   - `references/<topic>.md` — session detail, condensed knowledge banks, quirks,
   - `templates/<name>.<ext>` — starter files meant to be copied and modified,
   - `scripts/<name>.<ext>` — re-runnable actions: probes, verifiers, generators.
4. **Else create a new class-level umbrella skill** — only when nothing above
   fits. The name must describe a *class of task* (`mysql-read-latency-triage`),
   never a ticket, an error string, a feature codename, or a "fix-X-today".

Why the order matters: each rung down is a bigger change to the library. Patching
an existing skill keeps knowledge dense and discoverable; minting a new skill for
something that belonged in an existing one scatters it into siblings that compete
to trigger. A new umbrella is the last resort, not the reflex.

**Patch discipline.** Re-read the file before editing. Tolerate whitespace and
indent drift. Keep the frontmatter valid — `name` plus a `description` of at most
1024 characters. Write atomically. You don't need to manage rollback by hand:
`cairn` commits every skill change, so git is your undo.

## Do NOT capture

Some "lessons" harden into constraints that bite you months later. The review
rule refuses these on purpose:

- **Environment-dependent failures** — a missing binary, unconfigured
  credentials, a fresh-install error. Capture the *fix* under a setup or
  troubleshooting skill. Never write "this tool doesn't work" as a standalone
  fact.
- **Negative claims about tools or features** — "X is broken", "the browser tools
  don't work". These become refusals the agent later cites against itself, long
  after the thing started working again.
- **Transient errors that resolved on retry** — the lesson is the retry pattern,
  if anything, not the failure that cleared itself.
- **One-off task narratives** — "summarise today's numbers". Skills are
  procedures, never session transcripts. If erasing the proper nouns leaves
  nothing behind, it was never a skill.

## Preferences route into the skill body

When you correct *how* a task was handled — "too verbose", "stop doing X", "just
give me the answer" — that's a first-class skill signal, not just a passing mood.
Fold the lesson into the `SKILL.md` **body** of the skill that governs that task,
so it shapes the work next time. Don't leave it loose in memory where it won't be
loaded alongside the procedure it's meant to correct.

## Memory vs skills

The review rule writes to two different places, and routing matters:

- **Memory** = who you are and the state of things. Two small, char-capped files:
  `memories/USER.md` (preferences, style, habits) and `memories/MEMORY.md`
  (environment facts, conventions, tool quirks). Read and write them with
  `cairn memory user add "..."` and `cairn memory agent add "..."`. A rejected
  write means you're over the cap — trim or replace first. Memory is a frozen
  snapshot taken at session start, so a write you make now lands *next* session.
- **Skills** = how to do a class of task.

Don't put task procedures in memory, and don't put user identity in skills. When
in doubt: if it's *who you are* or *the state of operations*, it's memory; if it's
*how to do something repeatable*, it's a skill.

## Per-skill feedback, done as you work

Two files live beside each skill and feed the curator and the improver:

- **`learnings.md`** — read it before running a skill. After a correction or a
  failed step, append one dated line:
  `YYYY-MM-DD — what happened → what to do differently`.
- **`usage.md`** — after a task where you actually used a skill, append one line:
  `YYYY-MM-DD | N/5 | one-line task context | what it helped or hindered`. Score
  honestly: 5 = it directly sped up or corrected the work; 1 = it activated but
  was useless or misleading. A low score is signal, not a failure. Rate only
  skills you genuinely used.

## The mid-session nudge

You don't have to wait for the end. In a long session, every ~15 non-trivial tool
actions, pause and ask whether a skill should be created or patched while the
context is fresh. Reset the count whenever you write one. Catching it mid-trail
is cheaper than reconstructing it from the transcript later.

## In short

```text
cairn review            # run the post-session pass now
cairn review --hook     # what the SessionEnd hook runs
/skill-review           # apply the tree by hand inside a session
cairn memory            # read USER.md + MEMORY.md and their caps
cairn curate            # the curator's read-only report on the library
```

Patch first, generalize second, create last — and let git hold every stone you
place.
