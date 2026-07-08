# Troubleshooting

Cairn keeps everything as plain files in git, so most problems are visible and
reversible. This is a symptom → fix list. Each entry tells you what Cairn
actually did and the one command that puts it right.

If you only remember one thing: nothing here deletes your work. The most
destructive action Cairn takes is a *move* into `~/.claude/cairn/skill-archive/`,
which both `mv` and git can undo.

---

## `cairn` isn't found after install

**Symptom.** `command not found: cairn`, even though install reported success.

**What happened.** Install copies the dispatcher into `~/.claude/cairn/` and
symlinks it to `~/.local/bin/cairn`. If `~/.local/bin` isn't on your `PATH`, the
link exists but your shell can't see it — install warned about exactly this:

```
! add ~/.local/bin to PATH to run 'cairn' directly
```

**Fix.** Add the directory to your shell profile, or run the dispatcher by its
full path:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc   # then restart the shell
# or, right now:
~/.claude/cairn/bin/cairn status
```

If the link is missing entirely (`ls -l ~/.local/bin/cairn`), re-run
`cairn migrate` — relinking is idempotent and safe.

---

## `claude not on PATH`

**Symptom.** `ERROR: claude not on PATH (install Claude Code first)`, or install
warns and skips the assessment step.

**What happened.** Every Cairn command splits into file steps (pure shell +
python3) and model steps (`claude -p`). The file steps run without Claude Code;
the model steps — `mine`, `distill`, `refine`, `review`, and the quality
assessment during `migrate` — need the `claude` binary. Install deliberately
proceeds without it so the library is laid down, then tells you which steps are
waiting:

```
! claude not on PATH — file install proceeds; model steps (mine/review/assess) need it
```

**Fix.** Install Claude Code, confirm `claude --version`, then re-run the step
that was skipped. To backfill the quality scores that were skipped during
install:

```bash
cairn migrate          # scores existing skills' quality (model calls)
```

---

## The SessionEnd review hook didn't fire (or fired on itself)

**Symptom.** You enabled hooks but `~/.claude/cairn/logs/review-hook.log` stays
empty — or you worry the review's own `claude -p` call will trigger another
review, and another, forever.

**What happened.** `cairn install --enable-hooks` (or `cairn migrate
--enable-hooks`) adds one `SessionEnd` hook to `settings.json`, merged in by
python3 with a backup taken first. The command it installs carries a recursion
guard:

```bash
[ -n "${CAIRN_REVIEW_HOOK:-}" ] && exit 0; "…/cairn" review --hook >> "…/review-hook.log" 2>&1
```

When `cairn review` runs, it exports `CAIRN_REVIEW_HOOK=1` onto the nested
`claude -p` it spawns. If that nested session ends and fires `SessionEnd` again,
the guard sees the marker and exits immediately — so a review never reviews
itself. This is by design, not a missed run.

**Fix.**

- If you never enabled hooks, the review still runs as a soft rule in your
  managed `CLAUDE.md` block, or on demand: `cairn review`.
- To check the hook is wired up, look for a `cairn … review` command under
  `hooks.SessionEnd` in `~/.claude/settings.json`.
- The guard means the log is silent for *cairn's own* review sessions. To
  review the last real session by hand: `cairn review` (it discovers the newest
  transcript whose cwd is under your current directory).

---

## Memory rejected my entry: "over cap"

**Symptom.**

```
REJECTED: adding this entry would make USER.md 1402 chars (cap 1375). Trim or replace an existing entry first.
ERROR: memory add rejected (see reason above) — over cap 1375, or unsafe characters
```

**What happened.** Memory is bounded on purpose. `USER.md` and `MEMORY.md` are
char-capped (defaults 1375 and 2200), and `cairn memory … add` refuses anything
that would push a file past its cap rather than silently growing it (it also
rejects control/invisible characters). The cap is the feature — small memory
stays useful. Fix it with `cairn memory <user|agent> trim` or `… replace`.

**Fix.** Make room, then add. You have three moves:

```bash
cairn memory                                   # see both files + current char counts
cairn memory user trim                         # drop the oldest entry to free space
cairn memory user replace "old substring" "shorter rewrite"   # swap in place
cairn memory user add "the new durable preference"
```

Use `agent` instead of `user` for environment facts and conventions. To raise
the ceiling instead, set `CAIRN_USER_CAP` / `CAIRN_MEMORY_CAP` in your
environment — but prefer trimming; the bound is what keeps memory readable.

---

## A mine / distill / refine run stopped partway

**Symptom.** A Layer A backfill printed something like:

```
Stopped early without losing progress — re-run to resume.
```

…or you cancelled it yourself.

**What happened.** Cairn checkpoints these pipelines per item under
`~/.claude/cairn/harvest/`. Each mined session gets a `.done` stamp once its
candidates are safely appended to `candidates.jsonl`; `distill` and `refine`
stamp each cluster/item `.done` as it completes. On a *persistent* transient
error (rate limit, overload, timeout that survived the retries), the current
item is **not** stamped done and the run halts cleanly, leaving every finished
stamp in place. A *deterministic* failure on one item is quarantined with a
`.failed` stamp and the run continues past it.

**Fix.** Just run the same command again — it skips everything already stamped
`.done` and picks up where it left off:

```bash
cairn mine             # resumes; skips sessions already marked done
cairn distill
cairn refine
```

Other recoveries:

```bash
cairn mine --retry-failed   # re-attempt the quarantined (.failed) items
cairn mine --reset          # clear all stamps and start the pipeline over
```

Aggregation at the end of `mine` is also safe to retry — if it fails, your
candidates are untouched and re-running picks them back up.

---

## Restoring an archived skill

**Symptom.** `cairn curate --apply-lifecycle` retired a skill you still want —
it's gone from `~/.claude/skills/` and its `.meta` reads `state=archived`.

**What happened.** Lifecycle never deletes. An archived skill is *moved*, intact,
to `~/.claude/cairn/skill-archive/<name>-<timestamp>/`, and the move is committed
to the skills git repo. Pinned and bundled skills are never auto-archived in the
first place — so if something you cared about aged out, pin it after you restore.

**Fix.** Move the directory back, or use git:

```bash
ls ~/.claude/cairn/skill-archive/                       # find <name>-<timestamp>
mv ~/.claude/cairn/skill-archive/my-skill-20260614-101500 ~/.claude/skills/my-skill
cairn pin my-skill                                       # so it can't age out again
```

To recover from git instead (it sees the archive as a rename within the repo):

```bash
git -C ~/.claude/skills log --oneline -- '*my-skill*'    # find the lifecycle commit
git -C ~/.claude/skills checkout <commit>~1 -- my-skill  # restore the pre-move copy
```

---

## I want to undo an install or migrate

**Symptom.** You changed your mind, or a migrate touched a file you'd rather
keep as it was.

**What happened.** Install and migrate are idempotent and back up before they
overwrite. Any file Cairn replaces is copied to `<file>.bak-<timestamp>`
alongside it — your `CLAUDE.md`, your `settings.json`, every replaced asset.
Re-running converges byte-for-byte: an unchanged file is reported `(unchanged)`
and left alone.

**Fix.** Restore the specific file from its backup, or revert the skills repo:

```bash
ls ~/.claude/*.bak-*                                     # find the backups
cp ~/.claude/CLAUDE.md.bak-20260614-101500 ~/.claude/CLAUDE.md
git -C ~/.claude/skills log --oneline                    # cairn commits each change
git -C ~/.claude/skills checkout <commit> -- .           # roll skills back
```

To preview a migrate without touching anything first:

```bash
cairn migrate --dry-run     # describes every action; changes nothing
```

---

## Uninstalling, and what it leaves behind

**Symptom.** You want Cairn out of the way.

**What happened.** `cairn uninstall` removes the slash commands, the skill
template, the bundled meta-skill, the managed block from `CLAUDE.md`, the
`SessionEnd` hook, and the `~/.local/bin/cairn` link — backing up `CLAUDE.md` and
`settings.json` first. It deliberately **leaves your skills, their `.meta`, your
memory, the git repo, and `~/.claude/cairn/` untouched.** It tells you so:

```
Left untouched: your skills, their .meta, memory, the git repo, …/cairn.
```

**Fix.** Nothing is broken — that's the design. If you genuinely want the rest
gone, do it yourself; the archive lives there too, so be sure:

```bash
rm -rf ~/.claude/cairn     # removes the dispatcher + skill-archive + logs
```

---

## Confirming a command is safe to re-run

When in doubt, lean on idempotency. Re-running install, migrate, pin, or a
halted backfill is safe by construction — unchanged files are skipped, finished
work is checkpointed, and every skill write is committed to git. If a run looks
wrong, `git -C ~/.claude/skills status` and `cairn status` will show you the
state of every stone before you touch anything.
