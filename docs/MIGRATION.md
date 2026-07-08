# Migrating to Cairn

How an existing skill setup becomes a Cairn 2.0 setup, safely and in place.
`cairn migrate` (and `cairn install`, which calls it when it detects an existing
setup) performs every step below. It is idempotent, backs up anything it changes,
never deletes, and git-commits `~/.claude/skills` before and after.

---

## What 2.0 adds on top of an existing setup

| Area | Before | After (Cairn 2.0) |
|---|---|---|
| Skill metadata | none | `.meta` per skill (provenance, lifecycle, counts, timestamps, quality score) |
| Existing skills | as-is | assessed on migration (scored like any new skill), then curated normally |
| Support files | `references/` (ad hoc) | `references/` + `templates/` + `scripts/`, created lazily |
| Memory | `CLAUDE.md` only | bounded `memories/USER.md` + `memories/MEMORY.md` |
| Capture/improve | three soft `CLAUDE.md` rules | one review rule (decision tree + guardrails) |
| Consolidation | pairwise merge | umbrella-building curator + lifecycle |
| Entry point | several `skill-*.sh` scripts | one `cairn` dispatcher (old scripts still work) |

Nothing existing is removed. Skills keep their location and content; 2.0 layers
metadata and behaviour around them.

---

## What `cairn migrate` does, step by step

1. **Detect.** Look for an existing setup: `~/.claude/skills/` with skill dirs,
   and/or a previous managed `CLAUDE.md` block, and/or old `skill-*.sh` scripts.
   If none, this is a fresh install instead (same script, no migration steps).

2. **Snapshot.** If `~/.claude/skills` is a git repo, commit current state
   (`cairn: pre-migration snapshot`). If not, `git init` it first. This is the
   rollback point.

3. **Add `.meta` to every skill that lacks one.** Defaults:
   ```
   provenance=managed       # your skill — curated and assessed like any other
   pinned=false
   state=active
   created=<dir mtime or today>
   last_used=<dir mtime or today>
   last_patched=
   use_count=0
   quality=                 # filled by the assessment pass in step 4
   ```
   Existing `.meta` files are never overwritten. Only skills shipped by a plugin
   or installed from a registry are stamped `provenance=bundled` (protected) —
   and those normally live outside `~/.claude/skills` anyway.

4. **Assess every migrated skill (the important one).** Run the same reusability/
   quality scorer used on fresh proposals over each existing skill: score it 1–5,
   write `quality=<n>` into `.meta`, and surface low scorers in the migration
   summary. Existing skills are held to the same bar as any new tool — nothing is
   walled off from evaluation. (Model-calling step; batched and resumable like the
   rest. `cairn migrate --no-assess` skips it if you want a pure metadata pass.)

5. **Seed feedback files where missing.** Create empty `learnings.md` and
   `usage.md` (with headers) for skills that don't have them. Never touch
   existing ones.

6. **Initialise memory.** Create `~/.claude/memories/USER.md` and `MEMORY.md`
   with headers and the char caps recorded, only if absent. If you already keep
   user facts in `CLAUDE.md`, migration leaves them; you can move them into
   `USER.md` later with `cairn memory`.

7. **Swap the `CLAUDE.md` managed block.** The old marker-delimited block (three
   soft rules) is replaced by the single review rule (decision tree + do-not-
   capture guardrails + preference routing + memory boundary + command index).
   The old block is backed up; anything outside the markers is untouched.

8. **Install the `cairn` dispatcher + scripts** under `~/.claude/cairn/bin/`, and
   the slash commands under `~/.claude/commands/`. Existing standalone
   `skill-*.sh` scripts are left in place (they still work) but `cairn <sub>` is
   the documented path going forward.

9. **Move working state into `~/.claude/cairn/`.** Mining/distill/refine output
   (`skill-harvest/`) and the skill archive are relocated under `cairn/` with
   symlinks or a one-time move; logs go to `cairn/logs/`. Idempotent.

10. **Commit.** `cairn: migrated to 2.0`. Print a summary: skills stamped &
    scored, low-quality skills flagged, memory initialised, block swapped, backup path.

11. **(Optional) `--enable-hooks`.** Adds the `SessionEnd` review hook via a
    backed-up, reversible settings edit. Off by default.

---

## Provenance: assessed, not walled off

Your existing skills are *your* library, so Cairn evaluates them the same way it
evaluates any new candidate — it does not treat them as untouchable. Migration
stamps them `provenance=managed` and scores each one (step 4), so a weak legacy
skill surfaces for improvement or consolidation exactly like a fresh proposal
would.

Only two things are ever left out of automatic curation:
- **`provenance=bundled`** — skills shipped by a plugin or installed from a
  registry. They're maintained upstream, not yours to curate, and normally live
  outside `~/.claude/skills` anyway.
- **`pinned=true`** — a skill *you* explicitly freeze. Pinned skills never
  auto-archive or get merged away, but they can still be content-improved.

```bash
cairn pin <skill-name>            # freeze: no auto-archive/merge (still improvable)
cairn unpin <skill-name>
cairn provenance <name> bundled   # mark as upstream-maintained (rare, manual)
cairn provenance --list           # show every skill, its provenance, and quality score
```
Skills Cairn creates from here on are stamped `managed` and scored automatically.

---

## Lifecycle after migration

Once a skill is `provenance=managed` (the default), the curator tracks it:
- **active** → **stale** after 30 days with no use, view, or patch,
- **stale** → **archived** after 90 days,
- archived skills move to `~/.claude/cairn/skill-archive/` (recoverable; also in
  git history). Nothing is ever deleted.
- `pinned=true` skills never auto-transition (set with `cairn pin <name>`), but
  can still be content-improved.
`last_used` / `last_patched` / `use_count` update as you work and as the review
loop runs, so a freshly migrated library won't be considered stale immediately —
migration sets `last_used` to now.

---

## Safety & rollback

- **Idempotent.** Re-running `cairn migrate` changes nothing already in the 2.0
  shape.
- **Backed up.** The pre-migration `CLAUDE.md` block and any replaced file are
  saved with a timestamp suffix.
- **Git is the safety net.** Steps 2 and 9 bracket the migration with commits;
  to undo, `git -C ~/.claude/skills reset --hard <pre-migration snapshot>` and
  restore the `CLAUDE.md` block backup.
- **Never deletes.** Worst case is an archive move, which git preserves.
- **Dry run.** `cairn migrate --dry-run` prints every action it would take and
  changes nothing.

---

## After migrating: recommended first steps

1. `cairn status` — see the library: counts, quality scores, ratings, lifecycle.
2. Review the migration summary's **low-quality flags** — these are existing
   skills that scored 1–2; improve, merge, or pin them as you see fit.
3. `cairn curate` — read the first consolidation report (read-only; no changes
   without `/skill-merge`).
4. Pin anything you want frozen: `cairn pin <name>`.
5. Optionally `./cairn-setup.sh --enable-hooks` to turn on automatic post-session
   review.
