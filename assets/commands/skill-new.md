---
description: Scaffold a new skill with learnings loop and evals from the house template
argument-hint: <skill-name> [one-line purpose]
---
Create a new skill scaffold.

Arguments: $ARGUMENTS

1. Derive a kebab-case, **class-level** name from the arguments; if missing, ask
   for name + purpose (one question, then proceed). The name must describe a
   *class* of task — never a ticket number, error string, or "fix-X-today".
2. Copy `~/.claude/templates/skill-template/` to `~/.claude/skills/<name>/`
   (use the project's `.claude/skills/<name>/` instead if I say "project scope").
3. Fill in SKILL.md frontmatter:
   - `name`: the skill name,
   - `description`: what it does + "Use when ..." with 3–6 concrete trigger
     situations/phrases, including wording I'd actually type (Polish phrases are
     fine). This field alone drives activation — be specific, ≤ 1024 chars.
4. Draft the Procedure with me; derive steps from this session if possible. Keep
   SKILL.md tight (~150 lines); push heavy detail to `references/`, starters to
   `templates/`, re-runnable actions to `scripts/`, each with a SKILL.md pointer.
5. Seed `evals/cases.md` with 3 realistic starter cases (input → pass criteria).
6. Stamp `.meta`: `cairn` will initialise it, or write
   `provenance=managed`, `created=<today>`, `last_used=<today>`, `use_count=0`.
7. Show the final tree + SKILL.md, then commit in `~/.claude/skills/`:
   `git add -A && git commit -m "skill-new: <name>"`.
   Keep the learnings-loop sections from the template intact.
