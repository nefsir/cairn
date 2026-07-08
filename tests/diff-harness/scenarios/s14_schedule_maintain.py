NAME = "schedule-maintain-launchd-and-lock"

# Golden master for `cairn schedule` (nightly-maintenance wiring) and `cairn
# maintain` (the unattended improve + curate --apply-lifecycle job + its lock).
#
# PLATFORM FORK. sched_enable/sched_disable/sched_status branch on `uname`:
#   * Darwin -> launchd: writes ~/Library/LaunchAgents/com.cairn.maintain.plist
#     and calls `launchctl bootout`/`bootstrap`.
#   * else   -> cron: rewrites the crontab (the `# cairn maintain` line CONTENT
#     lands in the crontab shim's $HOME/.crontab-installed).
# This harness host is Darwin, so we DRIVE THE LAUNCHD BRANCH and assert its
# shim payload. The plist itself lives under ~/Library/LaunchAgents, which is
# OUTSIDE the snapshot roots ($CLAUDE_DIR + the shim logs), so the observable
# surface on Darwin is (a) each schedule command's stdout/stderr/rc and (b) the
# accumulated `launchctl` argv in $HOME/.launchctl-calls. (On a Linux port the
# same scenario would instead pin the cron line via $HOME/.crontab-installed;
# note that even on Darwin, sched_status/sched_disable probe `crontab -l`, so
# $HOME/.crontab-calls accumulates `args=-l` lines here too.)
#
# Determinism (why this is a stable golden master, not just green-today):
#   * schedule enable/disable/status observables are pure functions of the argv
#     and `id -u` (identical for both builds in one run) and fixed label strings.
#     HH:MM is parsed with base-10 forcing (`10#08`), so "08:09"/"00:00" never
#     hit the octal trap; the case globs make "24:00"/"12:60"/garbage die.
#   * maintain's lifecycle applies NOTHING: alpha-improvable carries EMPTY date
#     stamps (state_for -> active forever) and beta-pinned-old is pinned (propose
#     SKIPS it), so no skill ever ages into stale/archived. This is deliberate:
#     an ARCHIVE transition renames the dir to `<name>-$(ts)` (second-granular)
#     and the harness does NOT normalize tree-PATH keys (only file contents), so
#     any archive-apply is non-deterministic across the oracle/candidate run gap
#     (see s90_probe_arch, which is red for exactly this reason). We keep the
#     library "tidy" so curate reports "nothing ages out" and moves no dirs.
#   * Exactly ONE skill is improvable (alpha-improvable: >=5 eval cases, no
#     .last-improve stamp), so the improve picker's mtime tie-breaker never runs
#     and the model step (the deterministic `claude` shim) is invoked exactly
#     once. The shim edits no files; improve only stamps last_patched=<today> and
#     touches evals/.last-improve, both same-day-identical for the two builds.
#   * The lock is a directory: run 1 acquires+releases it (EXIT-trap rmdir of the
#     empty dir); we then SEED a non-empty lock dir so run 2 deterministically
#     takes the "another maintain holds the lock" SKIP branch (fresh mtime => the
#     <6h staleness reclaim never fires).
#   * All skill dir names are ASCII lowercase/hyphen slugs (C-locale glob sort).
#   * maintain re-prepends system dirs to PATH before finding `claude`, but $HOME
#     is the sandbox, so $HOME/.local/bin has no claude and the shims dir (still
#     on PATH) wins -> the shim, never a real claude.
#
# NON-DETERMINISM NOTE (shared with s01/s02/s04): curate's report header embeds
# `date '+%Y-%m-%d %H:%M'`; the normalizer collapses the date to <DATE> but the
# HH:MM minute is left raw, and it reaches CURATE.md + maintain.log. Both builds
# run sub-second apart, so this is green in practice; a port must emit the
# identical minute-granularity format. (The lifecycle `idle days` integer is
# similarly same-day-stable rather than run-date-invariant, but no fixture sits
# in a window where it flips a transition, so it never reaches an observable.)


def _skill_md(name, desc, body="Body of the skill."):
    return "---\nname: %s\ndescription: %s\n---\n%s\n" % (name, desc, body)


def _meta(provenance="managed", pinned="false", state="active",
          created="", last_used="", last_patched="", use_count="0", quality=""):
    return ("provenance=%s\npinned=%s\nstate=%s\ncreated=%s\nlast_used=%s\n"
            "last_patched=%s\nuse_count=%s\nquality=%s\n"
            % (provenance, pinned, state, created, last_used,
               last_patched, use_count, quality))


def _cases(name, n):
    lines = ["# Eval cases — %s" % name]
    for i in range(n):
        lines.append("## Case %d: scenario number %d" % (i + 1, i + 1))
        lines.append("input -> expected output")
    return "\n".join(lines) + "\n"


def run(ctx):
    # 0. install: lays down $STATE/bin/cairn (the dispatcher sched_enable requires)
    #    and git-inits skills/. Everything schedule/maintain touch depends on it.
    ctx.run("install")

    # =========================================================================
    # SCHEDULE  (Darwin -> launchd branch)
    # =========================================================================

    # --- status while OFF: no plist yet, so sched_status falls through to the
    #     `crontab -l` probe (-> $HOME/.crontab-calls) and prints "off". Three
    #     spellings of the status request all route to the same branch.
    ctx.run("schedule", "--status")
    ctx.run("schedule")            # no arg -> status
    ctx.run("schedule", "status")  # bareword -> status

    # --- enable at 03:30 (the canonical example): launchd branch does
    #     `launchctl bootout gui/<uid>/com.cairn.maintain` then
    #     `launchctl bootstrap gui/<uid> <plist>` (both logged to
    #     $HOME/.launchctl-calls) and prints "scheduled at 03:30 (launchd: ...)".
    ctx.run("schedule", "03:30")

    # --- status now reports "on (launchd)" (plist present -> returns before the
    #     crontab probe) and adds the second "runs cairn maintain ..." info line.
    ctx.run("schedule", "--status")
    ctx.run("schedule", "status")

    # --- HH:MM parsing edges. Each is a valid re-enable that overwrites the plist
    #     and appends another bootout+bootstrap pair, with distinct Hour/Minute:
    ctx.run("schedule", "9:05")    # single-digit hour       -> h=9  m=5
    ctx.run("schedule", "08:09")   # base-10 (08/09 = bad octal) -> h=8 m=9
    ctx.run("schedule", "00:00")   # midnight, double-zero base-10 -> h=0 m=0
    ctx.run("schedule", "23:59")   # upper boundary          -> h=23 m=59

    # --- reject edges: none match the time globs -> die (rc 1, usage on stderr,
    #     no shim touched):
    ctx.run("schedule", "24:00")   # hour out of range (fails 2[0-3] and [01][0-9])
    ctx.run("schedule", "12:60")   # minute out of range (fails the [0-5] tens digit)
    ctx.run("schedule", "3pm")     # non-numeric garbage

    # --- disable, exercising all three aliases AND both outcomes:
    ctx.run("schedule", "--off")      # plist present -> bootout + rm -> "removed"
    ctx.run("schedule", "off")        # plist gone    -> "no maintenance schedule was set"
    ctx.run("schedule", "--disable")  # plist gone    -> same "no ... was set"
    ctx.run("schedule", "--status")   # back to "off"

    # =========================================================================
    # MAINTAIN
    # =========================================================================
    # Seed the library AFTER install so install's stamp_meta/seed_feedback never
    # rewrite these fixtures — every byte is exactly what we write here.

    # alpha-improvable: the SOLE improve target (>=5 eval cases, no .last-improve
    # stamp -> picked). EMPTY dates -> lifecycle keeps it active (never aged).
    ctx.seed("skills/alpha-improvable/SKILL.md",
             _skill_md("alpha-improvable",
                       "Improve target; triggers on widget calibration tasks."))
    ctx.seed("skills/alpha-improvable/.meta", _meta())
    ctx.seed("skills/alpha-improvable/evals/cases.md", _cases("alpha-improvable", 5))

    # beta-pinned-old: ancient dates BUT pinned -> lifecycle propose SKIPS it, so
    # --apply-lifecycle never archives it. Proves protection without a dir move.
    ctx.seed("skills/beta-pinned-old/SKILL.md",
             _skill_md("beta-pinned-old",
                       "Frozen reference; triggers on invoice reconciliation."))
    ctx.seed("skills/beta-pinned-old/.meta",
             _meta(pinned="true", created="2000-01-01", last_used="2000-01-01",
                   use_count="7", quality="4"))

    # --- run 1: the FULL nightly job. Acquires the lock, runs `cairn improve`
    #     (invokes the claude shim once on alpha-improvable -> $HOME/.claude-*),
    #     runs `cairn curate --apply-lifecycle` (tidy library -> "nothing ages
    #     out", no dir moves), releases the lock via the EXIT trap. improve/curate
    #     output is redirected into $STATE/logs/maintain.log (snapshotted).
    ctx.run("maintain")

    # --- seed a held lock so run 2 takes the SKIP branch. Seeding a file INSIDE
    #     the lock dir materializes the directory `mkdir "$MAINTAIN_LOCK"` will
    #     collide with; its mtime is fresh, so the >6h stale-reclaim never fires.
    ctx.seed("cairn/.maintain.lock/.keep", "")

    # --- run 2: `mkdir` fails -> "SKIP: another maintain run holds ..." (rc 0),
    #     no improve, no curate, no trap (lock left intact for the snapshot).
    ctx.run("maintain")
