---
name: REPLACE-skill-name
description: REPLACE — what this skill does (a CLASS of task). Use when REPLACE trigger 1, REPLACE trigger 2, or the user says "REPLACE phrase". Keep ≤ 1024 chars; this field alone drives activation.
# optional — sharpen `cairn suggest` matching (both fields are matched bilingually):
# keywords: REPLACE, key terms, incl. the Polish phrases you'd type (weighted higher)
# platforms: macos, linux        # omit = all platforms; hides the skill elsewhere
---

# REPLACE Skill title

## Before you start
Read `learnings.md` in this skill's directory and apply any relevant entries.

## Procedure
1. REPLACE step
2. REPLACE step
3. REPLACE decision point: if X → do Y, otherwise → step 4
4. REPLACE step

## Success criteria
- REPLACE observable, self-checkable criterion
- REPLACE criterion

<!-- Support files (add as the skill grows; one-line pointer here per file):
  references/<topic>.md   condensed detail / knowledge banks / quirks
  templates/<name>.<ext>  starters meant to be copied and modified
  scripts/<name>.<ext>    re-runnable actions (probes, verifiers, generators) -->

## After execution (learnings loop)
If the user corrected the output, a step failed, or you found a better way,
append ONE dated line to `learnings.md`:

`YYYY-MM-DD — what happened → what to do differently next time`

A clean run is NOT a learning. If the run went as documented, append nothing —
`usage.md` already records that it ran. Never log "shipped clean" or a per-run
changelog; it buries the real traps.

When `learnings.md` exceeds ~15 entries, propose folding the stable ones into the
Procedure above and pruning the log (`/skill-fold`).
