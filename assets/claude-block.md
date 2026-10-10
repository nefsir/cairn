<!-- BEGIN cairn (managed by cairn) -->
## Cairn — skill & memory loop

Cairn keeps a library of **skills** (how to do a class of task) and a small,
bounded **memory** (who you are + the state of things) under `~/.claude`, all as
plain files in git. After a session that taught something reusable, run the
review below — the `SessionEnd` hook does it automatically when enabled,
otherwise apply this rule yourself. **Bias to action: most sessions produce at
least one update; a pass that captures nothing is usually a missed one.**

### Use the matching skill — first, not as an afterthought
A `Skill check` note may appear at the start of a turn, listing installed skills
whose triggers match the request. When it does, **invoke the matching skill via
the Skill tool BEFORE improvising** — or state in one line why it does not fit.
Acting on a surfaced match is the default, not an option; silently skipping a
clear match is the exact failure this loop exists to prevent. (No note means
nothing scored high enough — proceed normally.)

### The update decision tree (top-down; stop at the first that fits)
1. **Patch a skill loaded/consulted this session** if it covers the territory —
   fix a wrong step, add a pitfall, broaden a trigger.
2. **Else patch an existing umbrella skill** — a class-level skill the topic
   belongs under: broaden its `description` triggers or add a labelled subsection.
3. **Else add a support file** under the nearest umbrella, and add a one-line
   pointer to it from `SKILL.md`:
   - `references/<topic>.md` — session detail, condensed knowledge banks, quirks,
   - `templates/<name>.<ext>` — starter files meant to be copied and modified,
   - `scripts/<name>.<ext>` — re-runnable actions (probes, verifiers, generators),
   - `assets/<name>` — supporting binaries/fixtures the skill references.
4. **Else create a new class-level umbrella skill** — only if nothing fits. The
   name must be class-level (`mysql-read-latency-triage`), never a ticket / error
   string / feature codename / "fix-X-today".

Patch discipline: re-read the file first, tolerate whitespace/indent drift, keep
the frontmatter valid (`name` + `description ≤ 1024 chars`), write atomically,
and let git be the rollback (`cairn` commits skill changes).

### Do NOT capture (these harden into constraints that bite later)
- **Environment-dependent failures** (missing binary, unconfigured creds, fresh-
  install error) — capture the *fix* under a setup/troubleshooting skill, never
  "this tool doesn't work" as a standalone fact.
- **Negative claims about tools/features** ("X is broken", "browser tools don't
  work") — they become refusals the agent cites against itself months later.
- **Transient errors that resolved on retry** — the lesson is the retry pattern,
  not the failure.
- **One-off task narratives** ("summarise today's numbers"). Skills are
  procedures, never session transcripts.

### Preferences are first-class skill signals
When the user corrects *how* a task was handled ("too verbose", "stop doing X",
"just give me the answer"), fold that lesson into the `SKILL.md` body of the
skill governing that task — not only into memory.

### Memory vs skills (route correctly)
- **Memory** = who the user is + the state of operations. Two small char-capped
  files: `memories/USER.md` (preferences, style, habits) and `memories/MEMORY.md`
  (environment facts, conventions, tool quirks). Read/write with `cairn memory`.
  Memory is a frozen snapshot at session start — writes land next session.
- **Skills** = how to do a class of task. Don't put task procedures in memory, or
  user identity in skills.

Your current memory, auto-loaded each session (edit with `cairn memory`, never by hand):
@memories/USER.md
@memories/MEMORY.md

### Per-skill feedback (do these as you work)
- `learnings.md`: read it before running a skill; after a correction or a failed
  step, append one dated line — `YYYY-MM-DD — what happened → what to do
  differently`. **A clean run is not a learning** — if it went as documented,
  append nothing; `usage.md` already records that it ran. Never log "shipped
  clean" or a per-run changelog: it buries the real traps.
- `usage.md`: after a task in which you actually used a skill, append one line —
  `YYYY-MM-DD | N/5 | one-line task context | what it helped or hindered`. Score
  honestly (5 = directly sped up/corrected; 1 = activated but useless/misleading);
  a low score is signal, not failure. Rate only skills you genuinely used.

### Mid-session nudge
In a long session, every ~15 non-trivial tool actions, pause and ask whether a
skill should be created or patched. Reset the count whenever you write one.

### Commands
`/learn` distill this session · `/skill-new` scaffold · `/skill-improve` eval→fix
loop · `/skill-merge` consolidate · `/skill-fold` learnings→body · `/skill-review`
run the decision tree now.
`cairn review | curate | improve | status | memory | pin | unpin | provenance`.
<!-- END cairn -->
