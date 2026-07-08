---
description: Fold a skill's accumulated learnings.md into its SKILL.md procedure, then prune the log. Use when the curate report flags a fold candidate, learnings.md has grown large, or the user says "fold learnings", "skróć learnings", "złóż learnings do skilla".
argument-hint: <skill-name>
---
Consolidate learnings into the skill body. Argument: $ARGUMENTS

1. Locate the skill in `~/.claude/skills/` (or the project's `.claude/skills/`).
   Read its SKILL.md and learnings.md.
2. Classify each learnings entry:
   - STABLE / recurring → should become part of the Procedure or Success criteria,
   - one-off / situational → leave in the log,
   - already reflected in SKILL.md → drop.
3. Propose an updated SKILL.md that folds the stable learnings into the relevant
   steps (edit in place, keep it under ~150 lines; push bulky detail to a
   `references/` file). Preserve the learnings-loop sections and valid frontmatter.
4. Propose a pruned learnings.md: remove folded/duplicate entries, keep the recent
   and not-yet-stable ones. Never empty it of its header.
5. Show me both diffs (SKILL.md and learnings.md) before writing.
6. On approval, write both files, stamp `.meta` `last_patched=<today>`, and commit:
   `git -C ~/.claude/skills add -A && git commit -m "fold: <name> learnings into SKILL.md"`.
