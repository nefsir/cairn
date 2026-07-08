---
description: Distill reusable knowledge from this session into a skill (create or update)
argument-hint: [optional focus, e.g. "the mongo compaction procedure"]
---
Review the current session and extract knowledge worth reusing, following the
Cairn update decision tree.

Focus: $ARGUMENTS (if empty, scan the whole session for candidates).

1. Identify 1–3 candidates: procedures, debugging patterns, conventions, decision
   rules. Skip one-off trivia, transient errors that resolved on retry, and
   anything already covered by project docs or an existing skill.
2. Apply the decision tree (stop at the first that fits):
   - a skill loaded/consulted this session covers it → patch THAT skill,
   - an existing umbrella covers it → broaden a trigger or add a subsection,
   - it's session detail / a starter file / a re-runnable action → add a
     `references/` · `templates/` · `scripts/` support file + a SKILL.md pointer,
   - nothing fits → follow the `skill-extraction` skill to draft a new
     class-level umbrella from `~/.claude/templates/skill-template/`.
3. Honour the do-not-capture guardrails. Route style/workflow corrections into the
   governing skill's body, not just memory.
4. Show me the draft / diff BEFORE writing anything.
5. After approval, write the files, stamp `.meta` (`last_patched`), and let
   `cairn` commit — or `git -C ~/.claude/skills add -A && git commit -m "learn: <name>"`.

Record procedures and decisions, not a session transcript.
