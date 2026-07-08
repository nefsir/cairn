---
description: Karpathy-style improvement loop for a skill — execute evals, grade, fix, re-eval
argument-hint: <skill-name> [iterations, default 1]
---
Run an improvement loop on skill: $ARGUMENTS

0. Locate the skill in `~/.claude/skills/` or `.claude/skills/`. Read SKILL.md,
   `learnings.md`, `usage.md`, `evals/cases.md`.
   - If `evals/cases.md` is missing or has fewer than 5 cases: STOP and help me
     write 5–10 cases first (each: a realistic input prompt + observable pass
     criteria). Never "improve" against a weak eval set.
   - If the `skill-creator` plugin is installed, prefer delegating execution and
     grading to its Eval / Improve / Benchmark modes; otherwise run the manual
     loop below.
1. EXECUTE — for each case, perform the task following SKILL.md literally
   (one subagent per case if available, to avoid cross-contamination).
2. GRADE — score each case pass/fail against its criteria; compute the pass rate.
3. ANALYZE — cluster failures by root cause:
   - triggering problem → fix the `description`,
   - procedure gap → fix the body,
   - missing knowledge → add to `learnings.md` or a `references/` file.
4. FIX — propose minimal, targeted edits as a diff. Re-read before patching,
   tolerate formatting drift, keep frontmatter valid. Apply only after my approval
   (unless I explicitly granted autonomy for this run).
5. RE-EVAL the previously failing cases; report the delta (pass rate before → after).
6. LOG a dated summary to `evals/runs.md`; stamp `.meta` `last_patched=<today>`.
   Commit in `~/.claude/skills/`:
   `git add -A && git commit -m "skill-improve: <name> <before>→<after>"`.

Repeat for the requested number of iterations or until the pass rate stops improving.
