---
description: Merge two or more overlapping skills into one umbrella, with review. Use when the curate report or the user flags skills with duplicated triggers, or the user says "merge these skills", "scal te skille", "połącz skille".
argument-hint: <skill-a> <skill-b> [skill-c ...]
---
Consolidate the named skills into a single class-level umbrella. Arguments: $ARGUMENTS

DESTRUCTIVE — always show the plan and get approval before writing or moving anything.

The bar is umbrella-building, not pairwise dedup: would a maintainer write these
as N skills, or as **one skill with N labelled subsections**? Merge when the latter.

1. Resolve each named skill in `~/.claude/skills/` (or the project's `.claude/skills/`).
   If any is missing, stop and list what was found. Never touch a skill whose
   `.meta` says `provenance=bundled` or `pinned=true` — report and skip it.
2. Read every skill's SKILL.md, learnings.md, usage.md, and evals/cases.md.
3. Propose ONE merged umbrella:
   - name: the clearest existing name, or a better umbrella name (ask if unsure),
   - description: union of the distinct triggers, deduplicated, still tight — not
     a concatenation. This is the activation contract (≤ 1024 chars).
   - body: merge procedures into labelled subsections, removing duplicate steps
     and reconciling conflicts (surface conflicts, don't silently pick one);
     demote narrow siblings to `references/` / `templates/` / `scripts/` where
     they're detail rather than procedure,
   - learnings.md / usage.md: concatenate, drop exact duplicates, keep dates,
   - evals/cases.md: union of cases, deduplicated.
4. Show me: the proposed merged SKILL.md in full, plus a one-line summary of what
   each source contributed and any conflicts you resolved.
5. On approval:
   - write the merged skill to `~/.claude/skills/<name>/` and stamp its `.meta`
     (`last_patched=<today>`),
   - move each ORIGINAL (except one reused as <name>) to
     `~/.claude/cairn/skill-archive/<dir>-<YYYYMMDD-HHMMSS>/` — archive, never delete,
   - commit: `git -C ~/.claude/skills add -A && git commit -m "merge: <names> -> <name>"`.
6. Confirm what moved where; archived skills no longer activate but are recoverable
   from `~/.claude/cairn/skill-archive/` and git history.
