# The `.meta` file and bounded memory

Cairn keeps two kinds of plain-text state beside your work: a `.meta` file that
gives each skill provenance and a lifecycle, and two char-capped memory files
that remember who you are and how things are set up. Both are just files in your
git repo — open them, diff them, revert them. This page describes what each key
means, who writes it, and the operations that change it.

---

## The `.meta` file

Every managed skill carries a `.meta` sidecar — simple `key=value` lines, one per
line, `#` comments allowed. One helper (`lib/meta.py`) is the only writer: it
keeps a canonical key order, writes atomically (`.tmp` then `os.replace`),
preserves keys it doesn't recognise, and on `init` never clobbers a file that
already exists.

```
provenance=managed
pinned=false
state=active
created=2026-06-14
last_used=2026-06-15
last_patched=
use_count=3
quality=4
```

| Key | Meaning | Written by |
|---|---|---|
| `provenance` | `managed` (your skill — curated and assessed like any other) or `bundled` (shipped by a plugin/registry — maintained upstream, left out of auto-curation) | `cairn migrate` / `install` stamps it; `cairn provenance <name> <managed\|bundled>` changes it |
| `pinned` | `true` freezes the skill from auto-archive and auto-merge (it can still be content-improved); `false` lets the curator manage it | `cairn pin <name>` / `cairn unpin <name>` |
| `state` | lifecycle: `active`, `stale`, or `archived` | the curator, as the skill ages |
| `created` | first-seen date, `YYYY-MM-DD` | set once at `init` (dir mtime or today) |
| `last_used` | last time the skill was loaded, viewed, or patched | the review loop and `pin`/`provenance` touches |
| `last_patched` | last time the improver edited the body; empty until first patch | the improve / review pass |
| `use_count` | integer, how many times the skill has been activated | bumped by the review loop (`meta.py bump`) |
| `quality` | 1–5 reusability score; empty until first assessed | the assessment / refine scorer |

### Lifecycle

`provenance=managed` skills move through three states, driven by the dates above:

- **active** → **stale** after 30 days with no use, view, or patch,
- **stale** → **archived** after 90 days,
- archived skills move to `~/.claude/cairn/skill-archive/` — recoverable, and
  still in git history. Nothing is ever deleted.

A `pinned=true` skill never auto-transitions, but it can still be improved.
Because migration sets `last_used` to now, a freshly migrated library is never
considered stale on day one.

### Working with `.meta`

Most of the time the loop writes these for you. When you want to inspect or set
one by hand:

```bash
cairn provenance --list            # every skill: provenance, pinned, state, quality
cairn pin my-release-skill         # set pinned=true (and stamp last_used)
cairn unpin my-release-skill
cairn provenance some-skill bundled
```

Under the hood those call `meta.py` directly:

```bash
python3 lib/meta.py get  <dir>/.meta quality        # print a value (empty if absent)
python3 lib/meta.py set  <dir>/.meta state stale     # set/replace one key, keep the rest
python3 lib/meta.py bump  <dir>/.meta use_count       # integer increment
python3 lib/meta.py dump  <dir>/.meta                 # all keys, canonical order
```

`init` is the safe one to lean on: it writes defaults only if the file is absent,
so re-running it can't overwrite a skill's history.

---

## Bounded memory: `USER.md` and `MEMORY.md`

Memory is two small Markdown files under `~/.claude/memories/`, injected as a
frozen snapshot at the start of each session:

- **`USER.md`** — who you are: preferences, communication style, habits.
- **`MEMORY.md`** — agent notes: environment facts, conventions, tool quirks.

They are deliberately small. Each file has a **hard character cap** so it can
never bloat your context: `USER.md` is capped at **1375** chars, `MEMORY.md` at
**2200** (override with `CAIRN_USER_CAP` / `CAIRN_MEMORY_CAP`). Memory captures
*who you are and the state of things*; skills capture *how to do a class of task*.

### The section-mark format

Entries are delimited by a leading section mark, `§`. Everything before the first
`§` is the header (the title line and a comment recording the cap); each `§` opens
a new entry, and an entry may span several lines until the next `§`.

```markdown
# USER model (cairn)
<!-- cairn memory — char cap 1375 chars; small on purpose; one entry per section mark -->
§ Prefers concise answers with a short rationale up front.
§ Reviews database migrations before they merge.
§ Ships a small web service; deploys via CI on merge to main.
```

The `§` is intentionally kept *out* of the header text — a literal mark there
would be parsed as the start of the first entry.

### Operations: `cairn memory`

`cairn memory` with no argument prints both files and their current fill:

```text
USER.md  (412/1375 chars)
...
MEMORY.md  (1180/2200 chars)
...
```

To change an entry, name the file (`user` or `agent`) and an action:

```bash
cairn memory user add "Prefers metric units in all examples."
cairn memory agent add "Build with: mvn -T1C -q verify; tests need Docker up."
cairn memory user replace "metric units" "Prefers metric units everywhere."
cairn memory agent remove "Docker"          # remove the one matching entry
cairn memory user trim                       # drop oldest entries until under cap
```

- **add** appends a new `§` entry. If the result would exceed the cap, it is
  **rejected** (`meta.py`/`memory.py` exit 3, distinct from a usage error) and
  nothing is written — trim or replace an existing entry first.
- **replace** swaps the single entry whose text contains `<substr>`. If the
  substring matches zero or more than one entry, Cairn refuses and asks you to be
  more specific — the match must be unique.
- **remove** deletes the single matching entry, same uniqueness rule.
- **trim** drops the **oldest** entries (top of the file) one at a time until the
  file fits under its cap, and reports how many it dropped.

The cap is what keeps memory honest: it forces the loop to consolidate rather than
accumulate, so the snapshot you carry into each session stays a small, deliberate
set of stones rather than a growing pile.

---

## See also

- [`docs/MIGRATION.md`](MIGRATION.md) — how `.meta` and memory are first created
  when an existing skill setup migrates to Cairn.
- [`README.md`](../README.md) — the loop that writes these files: review, curate,
  improve.
