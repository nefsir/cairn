# Cairn Python port — plan & contract (behavior-preserving)

> **STATUS: behavior-preserving port COMPLETE & PROVEN.** All 21 commands native;
> the 17-scenario differential golden-master battery is byte-identical to bash
> (exit/stdout/stderr/tree/.meta/settings.json/git-log incl. un-normalized short-HEAD/
> shim logs); lib-parity 11/11; bash suite 128 green (bash untouched). Self-contained
> deploy done (self_install copies the port package; the deployed Python entry runs
> standalone). Windows backends (schtasks/GetSystemPowerStatus) added, platform-gated;
> CI matrix (ubuntu/macos equivalence + windows native smoke); `.gitattributes` LF.
>
> **✅ FLIP DONE.** `bin/cairn` is now the Python entry; the bash implementation is
> `bin/cairn.bash` (the CI equivalence oracle). Harness default = `bin/cairn.bash` (oracle)
> vs `bin/cairn` (candidate) → 17/17 byte-identical. `tests/run-tests.sh` = **129 green**
> with Python as the active dispatcher (static bash checks target `bin/cairn.bash`, a new
> py_compile-the-port check, integration runs against the Python `$CAIRN`). Reversible:
> `git mv bin/cairn bin/cairn.py && git mv bin/cairn.bash bin/cairn`. Deploy over an
> existing bash install with `./bin/cairn install --enable-hooks` (enable_hooks upserts →
> hooks repointed in place; skills/memory/foreign-hooks preserved). Windows still needs the
> CI runner to validate (can't test on macOS).
>
> **2026-10: bash frozen.** `bin/cairn.bash` stays the equivalence oracle only for commands unchanged since the flip. The review pipeline (queue, detached worker, `--enqueue` hook) is Python-only; scenarios touching it carry `DIVERGED` and are covered by `tests/run-tests.sh`.


**Goal:** replace the bash `bin/cairn` with a single cross-platform Python `cairn`
that runs natively on **macOS, Linux, and Windows** from one codebase, WITHOUT
changing observable behavior on macOS/Linux. Baseline oracle: bash `cairn` @ the
branch point (`tests/run-tests.sh` = 128 green).

The full extracted behavioral contract (98 command-contracts across 12 slices) and
the synthesis live in the workflow output; a copy is in the session scratchpad
(`cairn-contracts.json`, `cairn-synthesis.json`). This file is the durable summary.

## Decisions (locked)

- **Packaging: hybrid.** `lib/*.py` become in-process modules (`cairn/lib/…`) AND
  keep a thin `python3 -m cairn.lib.x`/`python3 lib/x.py` CLI shim, so the existing
  unit tier and the lib exit codes (memory 2/3/4, meta 2) stay directly observable.
- **Windows: hard requirement for v1.** Native Windows alongside mac/linux.
  Windows-only pieces are NET-NEW (no bash oracle): `schtasks` scheduler backend,
  `GetSystemPowerStatus` (ctypes) power probe, `where.exe`/`shutil.which` discovery,
  a PATH shim (`cairn.cmd`) instead of a symlink, hook commands that self-swallow
  (never rely on `2>/dev/null || true`). These are spec'd + shim-tested, not
  golden-mastered.
- **Strict-reproduce for v1.** Reproduce bash quirks byte-for-byte (put() non-atomic
  cp+backup, enable_hooks in-place json.dump, uninstall matcher-drop wart). Any
  "fix" is a separate, tested change AFTER equivalence is proven.
- **Frozen clock.** Inject a `today()`/`ts()` override (e.g. `CAIRN_NOW`) so both
  builds see the same wall-clock; avoids midnight-rollover spurious diffs.
- **Canonical ordering = C/codepoint.** Names are ASCII slugs; declare codepoint
  order canonical (`sorted()`), run the harness under `LC_ALL=C`.

## The certainty mechanism — differential golden-master harness ("diff-cairn")

Treat bash `cairn` as ORACLE, python `cairn` as CANDIDATE; prove byte-equivalence of
every observable. Per scenario: two isolated sandboxes (own `$HOME`, `CLAUDE_DIR`
default-derived), identical pinned env (`TZ=UTC`, `LC_ALL=C`, `NO_COLOR=1`, fixed
`GIT_*_DATE`, unset user git identity → both take the `cairn@localhost` branch),
identical deterministic shims (claude/crontab/pmset/launchctl that log argv + stdin).
Run the SAME argv-vector scenario against each; per step capture rc/stdout/stderr;
end-of-scenario snapshot the whole `$CLAUDE_DIR`.

**Diffed (after normalization):** (a) exit code per step; (b) stdout bytes;
(c) stderr bytes; (d) full recursive file tree of `$CLAUDE_DIR` (paths + contents,
excl. live `.git` objects), incl. every `.meta` raw-byte (pins key ORDER);
(e) `settings.json` three ways (raw indent=2 / structural / sort_keys); (f) skills
git `git log --pretty=%T%x09%an%x09%ae%x09%s` + `--porcelain`; (g) shim logs
(.claude-calls/.claude-stdin redaction oracle, .crontab-*/.launchctl-calls payloads).

**Normalization order (longest-first):** `$HOME`→`<HOME>`, `$CLAUDE_DIR`→`<CLAUDE_DIR>`,
mktemp paths→`<TMP>`, `.bak-\d{8}-\d{6}`→`.bak-<TS>`, archive/collision `-\d{8}-\d{6}(-\d+)?`
→`-<TS>`, PID temp names→`.<PID>`, datetimes/`<TS>`/`<DATE>` via STRICT patterns (a
`%Y/%m/%d` bug won't match → survives → diffs). Idle-day integers NOT normalized
(same fixtures+today → identical between builds; off-by-one diffs).

**Lib-parity mode:** run each `lib/*.py` entrypoint directly with the unit-tier argv
against both builds — pins the 2/3/4 exit codes the command layer collapses to 1.

**Harness self-validation:** before judging any port, run bash-vs-bash — MUST be
byte-identical after normalization, else the normalization is wrong.

## Migration order (18 units, low→high; each provable green)

1. [low] shared: `lib/*.py` adopted verbatim + CLI shim
2. [low] shared: bootstrap — CLAUDE_DIR-derived paths, CAIRN_VERSION, TRANSIENT_RE,
   BEGIN/END markers, caps, MODEL_DEFAULT; output helpers (✓ U+2713, 2-space indent,
   color only on tty & not NO_COLOR); die→stderr `ERROR:`+exit1; today()/ts() formats
3. [low] shared: dep gates (shutil.which), py() seam, resolve_skill_dir (global→project),
   mkd (DRY), single-per-run CAIRN_TS
4. [low] banner / --help / --version / empty  ← FIRST full command (dispatcher skeleton)
5. [low] lint [name]
6. [med] put() (cmp-skip / backup-before-clobber) + skills_git/commit + strip_block
7. [med] provenance --list / status  (UNTESTED at cmd level — capture golden first)
8. [med] memory (add/replace/remove/trim/read) — $*-join vs $1 asymmetry (untested cmd layer)
9. [med] pin / unpin / provenance <name>
10. [med] suggest (--hook/--tick/manual) + track --hook (roster sentinel, JSON schema)
11. [high] run_claude (3-way rc 0/1/2 + quadratic backoff) — spine of all model cmds
12. [high] review [--hook/--dry-run] — recursion guard, redact-before-claude, always-exit-0
13. [high] enable_hooks + uninstall JSON surgery + swap_block  ← subtlest surgery
14. [high] install / migrate / uninstall (provision pipeline; fixed stage order)
15. [high] curate (report / --apply-lifecycle / --merge / --archive-weak / --assess)
16. [high] mine / distill / refine (backfill; distill/refine UNTESTED e2e)
17. [high] schedule / maintain (launchd/cron + Windows schtasks NET-NEW)
18. [low] test (dispatch to run-tests.sh)

## Test coverage GAPS (capture bash golden BEFORE porting — where silent regressions hide)

memory (whole cmd layer) · pin/unpin/provenance · status (whole dashboard) ·
distill/refine (zero e2e) · improve · mine beyond rc1/rc2 · review internals ·
curate report+merge body/byte-format · schedule/maintain plist+cron CONTENT ·
uninstall preservation · lint failure path · suggest manual + tick persistence ·
transcript.py truncation/flatten · meta .bak-on-change + memory trim ordering ·
banner/--help/--version/`cairn test` itself.

## Risk register (top, all high unless noted)

- Dispatcher control flow: Python analogue of `set -uo pipefail` WITHOUT errexit —
  each cmd_* in try/except → mapped exit code; one failure must NOT crash dispatcher;
  hook paths swallow-all (never stderr/nonzero).
- settings.json key ordering: change-gate on `json.dumps(sort_keys=True)` snapshot,
  but WRITE `json.dump(indent=2)` insertion-order; stage temp in dest's own dir + os.replace.
- Atomic-rename + backup: keep put() cmp-skip + backup-changed-to-.bak; meta/memory
  os.replace on same dir.
- Exit codes: preserve lib 2/3/4 at lib seam; command-layer collapse-to-1 separately.
- sed/awk transforms: strip/swap_block column-1 anchor, trailing-blank trim,
  BEGIN-without-END refusal.
- Hook stdout: scorer/renderer split (never leak @@ROSTER@@), exact additionalContext
  JSON, track silent-on-success.
- Redaction: adopt transcript.py VERBATIM (8-substitution order; redact-then-truncate).
- [med] bash word-split vs argv: memory add/replace=`' '.join(rest)`, remove=`rest[0]`.
- [med] git determinism: pin GIT_*_DATE, unset identity → cairn@localhost branch;
  diff %T tree-hash + subject, not raw hashes.
- [med] locale/collation: harness under LC_ALL=C; port uses sorted() (codepoint).
- [med] dir_date GNU-first probe → os.path.getmtime→date with today() fallback.

## Progress (branch `python-port`)

- ✅ Harness framework `tests/diff-harness/` (driver + 4 shims) — proven bash≡bash AND
  mutation-sensitive (negative controls catch version + install-message mutations).
- ✅ **16-scenario golden-master battery** covering the full command surface (version,
  install, memory, status, pin/provenance, lint, suggest/track, review, curate
  report/merge/archive-weak, mine, distill/refine, schedule/maintain, uninstall/migrate,
  install-hooks). Full self-check **16/16 bash-equivalent**.
- ✅ Harness normalization hardened: rank-based path keys for repeated `ts()`-named dirs;
  `.bak-<TS>` backups excluded (multiplicity is second-boundary dependent — a real bash
  wart, not a contract; creation still verified via the announced stdout line); distinct
  seconds/minute datetime tokens (a `%H:%M` vs `%H:%M:%S` format change still diffs).
- ✅ Port units 2-4: `port/cairn/{config,out,clock,cli,__main__}.py` + `bin/cairn.py`
  entry — dispatcher (failure-isolation), version/help/banner, unknown-command.
- ✅ Unit 1: `libseam.py` (in-process `LibRunner`, hybrid — CLI shim kept) proven
  byte-identical to subprocess via `tests/diff-harness/lib_parity.py` (11 cases).
- ✅ **Strangler-fig delegation**: the dispatcher routes not-yet-ported KNOWN commands
  to the bash oracle (`_delegate_to_bash`), so the port passes the FULL 16-scenario
  battery THROUGHOUT the migration (unported == bash; ported == proven-native). Removed
  once all commands are native. This lets units be ported in any order, each validated
  against the full battery immediately.
- ✅ Unit 5: `lint` (native, via validate seam) + `helpers.py` + `context.py`.
- ✅ Unit 7: `status` (native, inline dashboard lifted verbatim + lib-seam orchestration).
- ✅ Unit 10: `suggest` (hook/tick/manual/@@ROSTER@@/additionalContext) + `track` — s07.
- ✅ Unit 8: `memory` (read/add/replace/remove/trim) — s03.
- ✅ Units 6+9: `gitutil.py` (skills_commit) + `pin`/`unpin`/`provenance` — s05 (incl. git-log).
- ✅ Unit 12: `review` (native) — recursion guard, redact-before-claude via transcript
  seam (proven byte-identical at the `.claude-stdin` oracle), scoped claude -p → review.log,
  telemetry, always-exit-0 — s08. (`run_claude` unit 11 deferred: only reached by
  mine/distill/refine/curate, ported with them.)
- **✅ ALL 21 commands native** — the behavior-preserving port is COMPLETE: full
  17-scenario battery byte-identical to bash, lib-parity 11/11, strangler delegation
  removed (no bash dependency in dispatch), bash `bin/cairn` untouched (128 green).
  Equivalence PROVEN. (Earlier progress detail below.)
- **11 commands native** (version/help/banner/unknown, lint, status, suggest, track,
  memory, pin, unpin, provenance, review); full 16-scenario battery green throughout.
- ⏭ NEXT (heaviest, most interdependent): the **provision pipeline** — `strip_block`/
  `swap_block` (column-1 anchor, trailing-blank trim, BEGIN-without-END guard), `put`
  (cmp-skip / backup), `self_install`/`link_cairn`, `enable_hooks`+`uninstall` (settings.json
  upsert: change-gate on sort_keys snapshot but WRITE insertion-order + os.replace;
  preserve foreign hooks; empty-{} drop) [s15/s16], then `install`/`migrate` (fixed stage
  order, assess asymmetry) [s02…], then `run_claude` (11) + `curate` (15) [s09-11] +
  `mine`/`distill`/`refine` (16) [s12/s13], `schedule`/`maintain` + **Windows backends**
  (schtasks/GetSystemPowerStatus/where.exe/PATH-shim) [s14], `test` (18). Then remove the
  strangler delegation (unported KNOWN → hard error), `.gitattributes`, CI matrix, flip
  hooks to python, retire bash (keep as CI oracle).

## Upgrade path — install over an EXISTING (bash) install  ← hard requirement

The port must cleanly upgrade a user who currently has the bash cairn installed
(STATE/bin/cairn = bash, settings.json hooks → bash, skills/.meta/memory present).

- **Phase 1 (strict-reproduce, now):** python install byte-reproduces bash install over
  an existing setup — provision is idempotent by design (`detect_existing` → migrate in
  place; `put` backup+update; `swap_block` REPLACES the block; `enable_hooks` UPSERTS
  (finds existing cairn hook by "cairn"+needle and replaces its command — never
  duplicates, preserves foreign hooks); `meta/memory init` never clobber). Proven by the
  harness (the install scenarios seed a prior state).
- **Phase 2 (deliberate deviation, after equivalence):** to actually deploy python:
  `self_install` writes the python entry to STATE/bin/cairn AND copies the `port/cairn/`
  package (bash copies only bin/lib/assets); `enable_hooks` points hook commands at the
  python entry (the upsert replaces the old bash commands in place). NEW test
  `iso_upgrade`: bash install → python install/migrate → assert hooks replaced not
  duplicated, skills/.meta/memory/foreign-hooks intact, STATE now python. Both bash and
  python entries coexist in repo/bin during migration; the flip is one controlled step.

## Findings — latent bash bugs surfaced (fix AFTER equivalence, as separate tested changes)

- `swap_block` decides its "swapped vs installed" stdout line with
  `[ -f "$md.bak-$CAIRN_TS" ]` — a filename stamped with the CURRENT second. A leftover
  backup from an earlier step in the same wall-clock second flips the message (a false
  "swapped (backup: …)" citing a backup it never made). See s15 header. The port should
  name backups deterministically / decide on the actual write, not a same-second probe.
- `.bak`/archive names are second-precision, so two writes in one second collide
  (backup overwrite) or land as two files across a boundary. Deterministic naming
  (monotonic counter, or include the source content hash) would remove the flake.

## Build sequence (this branch)

0. Harness framework + shims + fixtures; prove **bash≡bash** (oracle self-check). ✅ DONE
1. Capture bash golden-masters for the 15 gaps as new characterization scenarios.
2. Port units 1–4 (libs + bootstrap + skeleton); harness green.
3. Port 5–10, then 11–18; each unit harness-green before the next.
4. `.gitattributes` (LF), CI matrix (ubuntu/macos/windows), Windows backends.
5. Flip hooks/dispatch to python `cairn`; retire bash `bin/cairn` (keep as oracle in CI).
