---
description: Run the Cairn post-session review decision tree now (patch a loaded skill → umbrella → support file → new), plus memory updates. Use at the end of a session, when the user says "review this session", "zrób review", "co warto zapisać", or as a manual stand-in for the SessionEnd hook.
argument-hint: [optional focus]
---
Run the Cairn review over this session. Focus: $ARGUMENTS

Be ACTIVE — most sessions produce at least one update. Work the decision tree and
the guardrails from the managed Cairn block in `~/.claude/CLAUDE.md`.

1. **Skills.** Identify what was learned that will recur. Apply the update
   decision tree, stopping at the first that fits:
   1. patch a skill loaded/consulted this session,
   2. else patch an existing umbrella (broaden a trigger / add a subsection),
   3. else add a `references/` · `templates/` · `scripts/` support file + pointer,
   4. else create a new class-level umbrella (class-level name only).
   Honour the do-not-capture guardrails. Route style/workflow corrections into the
   governing skill's body. Re-read before patching; keep frontmatter valid.
2. **Memory.** Update bounded memory only where it earns its place:
   - new lasting preference / style / habit → `cairn memory user add "..."`,
   - new durable environment fact / convention / tool quirk → `cairn memory agent add "..."`.
   Respect the char caps (a rejection means trim/replace first). Don't store task
   procedures (those are skills) or this review's own scaffolding text.
3. **Feedback.** Append honest `usage.md` ratings for skills actually used, and
   dated `learnings.md` lines for any corrections.
4. Show a short summary of every change, then commit the skills repo.
