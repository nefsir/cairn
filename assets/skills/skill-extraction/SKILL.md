---
name: skill-extraction
description: Converts a solved problem or repeated procedure from the current session into a well-formed, class-level Claude Code skill. Use when the user runs /learn or /skill-review, accepts a proposal to extract a skill, or says "save this as a skill", "zapisz to jako skill", "zrób z tego skill", "wyciągnij z tego skill". Also use when creating any new skill, so it follows the house format (class-level umbrella, description contract, support dirs, learnings loop, evals).
---

# Skill extraction

Turn session knowledge into a reusable skill. A skill captures **how to do a
class of task**, never a transcript of one session.

## 1. Apply the decision tree first
Before creating anything, check whether the lesson belongs in an existing skill:
1. a skill loaded/consulted this session covers it → patch THAT one,
2. an existing umbrella covers it → broaden a trigger or add a subsection,
3. it's session detail / a starter / a re-runnable action → add a support file
   (`references/` · `templates/` · `scripts/`) + a SKILL.md pointer.
Only create a new skill if none of these fit.

## 2. Class-level, not one-off
The test: erase the proper nouns (service names, hostnames, ticket IDs). If a
procedure remains, it's a skill. If nothing remains, it was a runbook — keep it
as a `references/` file under a broader skill, not a standalone skill. One
umbrella with N labelled subsections beats five narrow siblings.

## 3. Name
kebab-case, domain-or-verb first, class-level: `mongo-compaction-rollout`, not
`database-stuff` and not `fix-march-12-incident`.

## 4. Description — the activation contract
The `description` frontmatter is the ONLY thing visible when deciding whether to
activate the skill. Rules:
- third person, starts with what the skill does,
- then `Use when ...` with 3–6 concrete trigger situations and phrases, including
  wording the user would actually type (Polish phrases welcome),
- narrow enough not to fire on adjacent topics; ≤ 1024 characters,
- if it could trigger on "any git task", it's too broad — name the exact workflow.

Optional frontmatter that sharpens the use-side matcher (`cairn suggest`):
- `keywords:` — a curated, comma-separated list of the strongest trigger terms,
  **including the Polish phrases the user actually types** (matched bilingually,
  diacritic-folded, and weighted higher than prose). The highest-precision lever.
- `platforms:` — e.g. `macos, linux`; omit for all. Hides the skill where it
  doesn't apply, so it never surfaces on the wrong OS.

## 5. Body + support files
- Start from `~/.claude/templates/skill-template/SKILL.md`.
- Numbered procedure with explicit decision points ("if X → go to step 6") and
  self-checkable success criteria.
- Keep SKILL.md under ~150 lines. Push heavy reference material to
  `references/<topic>.md`, copy-and-modify starters to `templates/`, and
  re-runnable actions (probes, verifiers, generators) to `scripts/` — each with a
  one-line pointer from SKILL.md (progressive disclosure).
- Preserve the learnings-loop sections from the template.

## 6. Scaffold + stamp
Create alongside SKILL.md: `learnings.md`, `usage.md` (headers only) and
`evals/cases.md` with 3 starter cases (`evals/runs.md` stays empty until the
first `/skill-improve`). Initialise `.meta` (`cairn` does this, or set
`provenance=managed`, `created=<today>`, `last_used=<today>`, `use_count=0`).

## 7. Confirm and commit
Show the draft (file tree + full SKILL.md) and wait for approval before writing,
unless the user granted autonomy. After writing, commit in `~/.claude/skills/`:
`git add -A && git commit -m "skill: add <name>"`.
