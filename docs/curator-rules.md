# How `cairn curate` works

Skills accumulate. Left alone, a library drifts: five narrow siblings where one
umbrella belongs, a `learnings.md` that has outgrown its `SKILL.md`, a skill that
scores poorly every time it fires, a skill nobody has loaded in three months. The
curator walks the library and tells you where it has drifted — and, only when you
ask, applies the one safe change it is allowed to make on its own: aging skills
through the lifecycle.

`cairn curate` is **read-only by default.** It writes a report and prints the top
of it. Nothing in your library moves until you act on the report.

```bash
cairn curate                      # scan, write the report, change nothing
cairn curate --threshold 0.30     # loosen the overlap bar for clustering
cairn curate --apply-lifecycle    # also age stale/archivable skills (the one write)
```

The report lands at `~/.claude/cairn/harvest/CURATE.md` and has four sections:
merge candidates, fold candidates, low-usefulness flags, and lifecycle
transitions. Each is a suggestion with the exact command to act on it — the
curator points; you decide.

## Merge into umbrellas

The bar is not pairwise deduplication. It is umbrella-building: **would a
maintainer write these as N skills, or as one skill with N labelled
subsections?** Merge only when the latter.

To find candidates, the curator tokenizes each skill's name and description
(stopwords and short tokens dropped), then measures pairwise Jaccard overlap. Any
pair scoring at or above the threshold (default `0.40`) is an edge; connected
edges cluster transitively via union-find, so three skills that overlap in a chain
land in one cluster. Clusters are sorted by their tightest internal overlap, and
each is printed with the ready-to-run command:

```text
### offer-store-currency + offer-pricing-pipeline  (overlap 0.52)
- offer-store-currency — Root-causes MonetaryException "Currency mismatch"…
- offer-pricing-pipeline — Fixes pricing/dedup/expand ordering on the read path…

    /skill-merge offer-store-currency offer-pricing-pipeline
```

The curator never merges for you. `/skill-merge` is a manual, destructive command
that always shows the full proposed umbrella and waits for approval before writing
anything — uniting the distinct triggers into one description, merging procedures
into labelled subsections, demoting narrow siblings to `references/` /
`templates/` / `scripts/`, and concatenating each skill's `learnings.md` and
`usage.md`. Originals are archived, never deleted.

## Fold candidates

A `learnings.md` is a running log. Once it grows past `fold-at` entries (default
`15` — counting dated lines and bullets, skipping comments), the stable lessons
belong folded back into the procedure itself. The curator flags it and hands you
`/skill-fold <name>`; it does not rewrite the skill on its own.

### The quality score is not a fold target

The `.meta` `quality` (1–5, set by the assessment scorer) rates **reusability /
transferability**, which is *not* the same as a skill's value to you — and for a
personal library of domain runbooks the two can be **inversely correlated**.
Observed directly: folding transferable *principles* into a design skill raised it
q3→q4; folding concrete *bespoke recovery steps* into a domain-specific runbook
dropped it q3→q2 (four consistent re-scores) — because more setup-specific detail
reads as "hyper-specific runbook", the q2 rung. Both folds made the skill **better**.

So do **not** treat `quality` as a fold/improve target, and do not re-score after a
fold to "check progress": you'd be optimizing a proxy that rewards deleting the very
runbook detail that makes a domain skill useful (Goodhart). Fold for completeness —
measure the *knowledge captured*, not the number. A genuinely low score is a signal
to improve or absorb a skill, never a dial to crank; a domain runbook that is
honestly a q2 is a fine, valuable q2.

## Low-usefulness flags

Every time a skill is genuinely used, a line lands in its `usage.md` rating the
activation 1–5. The curator reads those scores and flags a skill when it has been
used at least `CAIRN_USE_MIN` times (default `3`) **and** its average sits at or
below `CAIRN_USE_AVG` (default `2.5`). A single bad day is noise; a low average
over several real uses is signal — the skill is misfiring or stale.

```text
## Low-usefulness (1)
- some-skill — avg 1.7/5 over 4 use(s)
      /skill-improve some-skill
```

The suggestion is to improve or absorb it, never to retire it for scoring badly.

## Lifecycle transitions

Skills age by **inactivity**, not by score. "Activity" is the most recent of
`last_used`, `last_patched`, or `created` from a skill's `.meta`. The math is:

- idle ≥ `CAIRN_STALE_DAYS` (default **30**) → **stale**
- idle ≥ `CAIRN_ARCHIVE_DAYS` (default **90**) → **archived**
- otherwise → **active**

A skill with no activity stamp at all is left active. The report lists only the
skills whose proposed state differs from their current one:

```text
## Lifecycle transitions (by inactivity)
| skill | from | to | idle (days) |
|---|---|---|---|
| old-runbook-thing | active | stale | 41 |
| ancient-experiment | stale | archived | 103 |
```

This is the one place the curator will act on its own — but only when you pass
`--apply-lifecycle`. On apply:

- skills going **stale** have their `.meta` `state` set to `stale` in place;
- skills going **archived** are **moved** to
  `~/.claude/cairn/skill-archive/<name>-<timestamp>/`, then the change is
  committed.

**Archiving moves; it never deletes.** An archived skill stops activating but
stays fully recoverable — from `skill-archive/` and from git history. That is the
most destructive thing the curator can do.

## Batch modes — one run over hundreds of skills

The plain report is read-only and per-cluster commands are manual. For a large
library accumulated over time, two batch modes do the sweep in one run. Both
**preview by default** and only act with `--yes`, both **archive (never delete)**,
and both **skip pinned and bundled** skills.

### `cairn curate --merge` — consolidate overlapping clusters into umbrellas

For every trigger-overlap cluster (tunable with `--threshold`), Cairn asks the
model to synthesize one class-level umbrella — the union of the distinct triggers
plus the merged, de-duplicated procedure — writes it, concatenates the sources'
`learnings.md`/`usage.md` into it, and archives the originals. A merged skill that
fails frontmatter validation is skipped, its sources left intact.

```bash
cairn curate --merge                 # preview: "would merge: a b → one umbrella"
cairn curate --merge --yes           # execute (originals → cairn/skill-archive)
cairn curate --merge --yes --threshold 0.5   # tighter clustering = fewer, surer merges
```

### `cairn curate --archive-weak` — retire skills that aren't earning their place

Archives skills judged weak: `quality` 1–2 in `.meta`, or a usage average ≤ 2.5
over ≥ 3 ratings. Quality scores come from `cairn migrate`'s assessment; add
`--assess` to score unscored skills first (one model call each).

```bash
cairn curate --archive-weak          # preview what would be archived + why
cairn curate --archive-weak --yes    # archive them (recoverable)
cairn curate --archive-weak --assess --yes   # score unscored skills, then archive 1–2
```

Everything both modes touch lands in `cairn/skill-archive/<name>-<timestamp>/` and
in git history — recover any of it with a move back or `git`.

## What is never touched

Two kinds of skill are protected everywhere — clustering, fold, low-usefulness,
lifecycle, and the batch modes alike:

- **bundled** skills (`provenance=bundled` in `.meta`) — shipped, not yours to age;
- **pinned** skills (`pinned=true`) — frozen by you with `cairn pin <name>`.

`skill-extraction` is also skipped from clustering, since it is meant to overlap
with everything. Pin anything you want to keep exactly as it is:

```bash
cairn pin my-load-bearing-skill      # never auto-merged, flagged, or aged
cairn unpin my-load-bearing-skill    # let it rejoin the trail
```

A tidy library reports nothing: no clusters, no folds, no flags, no transitions.
Run `cairn curate` after a busy stretch, read the trail it marks, and decide which
stones to move.
