"""cairn review — post-session review pipeline.

``--enqueue``/``--hook`` (SessionEnd hook): validate the payload, drop a queue entry,
spawn a detached worker, return in milliseconds and always exit 0. The worker
(``--worker --after-session`` / ``--drain``) holds the review mutex, classifies each
entry, runs one scoped ``claude -p`` under a process-group timeout, reverts its edits
on failure and commits only the paths the run changed. The review never bumps
``use_count``/``last_used`` (the track hook owns those). A bare ``review [PATH]`` is the
manual, synchronous path.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from ..clock import epoch, today
from ..config import Config, _int_env
from ..context import Context
from ..gitutil import (_git, changed_since, commit_paths, revert_paths, skill_names,
                       skills_is_repo, snapshot_dirty)
from ..helpers import need_claude, need_python
from ..lockutil import mkdir_lock
from ..out import hdr, info, ok, say, warn
from ..reviewqueue import Queue, safe_sid

_ALLOWED = ("Read,Edit,Write,Glob,Grep,Bash(cairn memory:*),Bash(cairn provenance:*),"
            "Bash(cairn pin:*),Bash(cairn unpin:*)")

REVIEW_PROMPT = """You are running Cairn's post-session review. A flattened, redacted
transcript of the session just ended is on stdin. Decide what (if anything) to
save, and APPLY it directly — you act on files, you do not chat. Be ACTIVE:
most sessions produce at least one update.

Tools: use Read/Glob/Grep to inspect and Edit/Write to change files under
__SKILLS__ and __TEMPLATES__ (use ONLY these absolute paths — never any other
skills dir). Use Bash ONLY for `cairn memory ...`
(the harness commits for you — you do not need git, ls, cat, or any other shell
command; use Glob/Grep/Read to explore, never Bash). Do nothing destructive. Ask
no questions (no user is present); make conservative choices.

SKILLS — apply the update decision tree, stopping at the FIRST that fits:
  1. patch a skill loaded/consulted this session (fix a step, add a pitfall,
     broaden a description trigger),
  2. else patch an existing umbrella skill in __SKILLS__,
  3. else add a support file under the nearest umbrella —
     references/<topic>.md (detail/quirks), templates/<name> (starters), or
     scripts/<name> (re-runnable actions) — and add a one-line SKILL.md pointer,
  4. else create a new CLASS-LEVEL umbrella from __TEMPLATES__/skill-template/
     (class-level name only — never a ticket/error string/"fix-X-today").
  Re-read a file before editing; keep frontmatter valid (name + description
  <=1024 chars). NEVER edit a skill whose .meta says provenance=bundled or
  pinned=true (e.g. skill-extraction) — those are protected. Just edit files;
  the harness commits.

DO NOT capture: environment-dependent failures (save the FIX, not "X is broken"),
negative claims about tools, transient errors that resolved on retry, or one-off
task narratives. Route style/workflow corrections ("too verbose", "stop doing X")
into the governing skill's BODY.

MEMORY — only durable facts, respecting char caps (a rejection means trim/replace):
  - new lasting user preference/style/habit -> `cairn memory user add "..."`
  - new durable environment fact/convention/quirk -> `cairn memory agent add "..."`
  Memory is who-the-user-is + state-of-things; skills are how-to-do-a-class-of-task.
  Never store task procedures in memory, or this prompt's own text.

FEEDBACK — for each skill actually used this session, append one honest line to
its usage.md (YYYY-MM-DD | N/5 | context | helped/hindered); append dated
learnings.md lines for any corrections.
  A CLEAN RUN IS NOT A LEARNING. Write to learnings.md ONLY when the user
  corrected you, a step failed, or you found a genuinely better way. If the run
  went as the skill documents, append NOTHING there — usage.md already records
  that it ran. Never log "shipped clean" / "przebieg czysty" / a per-release
  changelog: that is the one-off task narrative excluded above, and it buries the
  real traps until someone has to fold the log by hand.
  Score usage.md honestly. If every entry is 4/5 or 5/5 the score carries no
  signal at all; a skill that fired but did not actually help is a 1 or a 2.

End by printing a 1-3 line summary of exactly what you changed (or "no changes")."""


_FLAT_MAX = "60000"


def _timeout_s() -> int:
    sec = _int_env("CAIRN_REVIEW_TIMEOUT_SEC", 0)
    return sec if sec > 0 else _int_env("CAIRN_REVIEW_TIMEOUT_MIN", 10) * 60


def _queue(cfg: Config) -> Queue:
    q = Queue(cfg.state / "queue")
    q.ensure()
    return q


def _spawn_worker(cfg: Config, lf) -> None:
    argv = [sys.executable, str(cfg.cairn_home / "bin" / "cairn"), "review", "--worker", "--after-session"]
    kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "posix":
        kw["start_new_session"] = True
    else:
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(argv, **kw)
    except OSError as e:
        say(lf, f"review-enqueue: could not spawn worker: {e}")


def _enqueue(ctx: Context, raw: str, lf) -> int:
    cfg = ctx.cfg
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except ValueError:
        say(lf, f"review-enqueue: bad hook JSON: {raw[:2048]}")
        return 0
    tp = str(payload.get("transcript_path") or "")
    sid = safe_sid(str(payload.get("session_id") or "")) or (safe_sid(Path(tp).stem) if tp else None)
    if not tp or not sid:
        say(lf, f"review-enqueue: no usable transcript_path/session_id: {raw[:2048]}")
        return 0
    try:
        return _enqueue_entry(ctx, tp, sid, payload, lf)
    except OSError as e:  # a worker renamed/rotated the file under us: never fail the hook
        say(lf, f"review-enqueue: {sid}: {e}")
        return 0


def _enqueue_entry(ctx: Context, tp: str, sid: str, payload: dict, lf) -> int:
    cfg = ctx.cfg
    q = _queue(cfg)
    now = epoch()
    found = q.find(sid)
    entry = {"transcript_path": tp, "cwd": str(payload.get("cwd") or ""),
             "reason": str(payload.get("reason") or ""), "enqueued_at": now,
             "from_user_msg": 0, "attempts": 0}
    if found is None:
        q.put("pending", sid, entry)
    else:
        state, p = found
        old = q.read(p)
        min_msgs = _int_env("CAIRN_REVIEW_MIN_USER_MSGS", 3)
        if state == "done":
            prev = int(old.get("user_msgs_reviewed", 0))
            n = int(ctx.lib.run("transcript", "count-user", tp).value() or 0)
            if n >= prev + _int_env("CAIRN_REVIEW_RESUME_MIN_NEW", 3):
                q.move(p, "pending", {**entry, "from_user_msg": prev})
            else:
                return 0
        elif state == "skipped" and old.get("why") == "skip:short":
            n = int(ctx.lib.run("transcript", "count-user", tp).value() or 0)
            if n >= min_msgs:
                q.move(p, "pending", entry)
            else:
                return 0
        elif state != "pending":
            return 0  # running / failed / other skips: nothing to do
        # already pending: fall through and (re)spawn a worker so it gets processed
    if not os.environ.get("CAIRN_REVIEW_NO_SPAWN"):
        _spawn_worker(cfg, lf)
    return 0


def _kill_group(p: subprocess.Popen) -> None:
    if os.name == "posix":
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                return
            try:
                p.wait(5)
                return
            except subprocess.TimeoutExpired:
                continue
    else:
        p.kill()


def _run_claude(prompt: str, model: str, flat: str, lf, timeout_s: int) -> tuple[int, str]:
    env = os.environ.copy()
    env["CAIRN_REVIEW_HOOK"] = "1"
    kw: dict = {"start_new_session": True} if os.name == "posix" else {}
    with open(lf, "ab") as log:
        p = subprocess.Popen(
            ["claude", "-p", prompt, "--model", model, "--max-turns", "30",
             "--permission-mode", "acceptEdits", "--allowedTools", _ALLOWED],
            stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, env=env, **kw)
        try:
            p.communicate(flat.encode("utf-8"), timeout=timeout_s)
            return p.returncode, "" if p.returncode == 0 else f"claude exited {p.returncode}"
        except subprocess.TimeoutExpired:
            _kill_group(p)
            return 124, f"timeout after {timeout_s}s"


def _head(cfg: Config) -> str:
    r = _git(cfg, "rev-parse", "--verify", "-q", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def _review_one(ctx: Context, transcript: str, model: str, from_user: int, lf) -> dict:
    """Run one review end to end. Returns the result fields for the queue entry."""
    cfg = ctx.cfg
    flat = ctx.lib.run("transcript", "flatten-file", transcript, _FLAT_MAX, str(from_user)).out.rstrip("\n")
    if flat == "":
        return {"outcome": "skipped", "why": "skip:empty", "rc": 0, "changed_skills": []}
    prompt = REVIEW_PROMPT.replace("__SKILLS__", str(cfg.skills)).replace("__TEMPLATES__", str(cfg.templates))
    say(lf, f"review: {transcript} (model {model}, from user msg {from_user})")
    repo = skills_is_repo(cfg)
    snap = snapshot_dirty(cfg) if repo else {}
    rc, why = _run_claude(prompt, model, flat, lf, _timeout_s())
    if not repo:
        return {"outcome": "done" if rc == 0 else "failed", "why": why, "rc": rc, "changed_skills": []}
    changed = changed_since(cfg, snap)
    if rc != 0:
        revert_paths(cfg, snap, changed)
        say(lf, f"review: {why}; reverted {len(changed)} path(s)")
        return {"outcome": "failed", "why": why, "rc": rc, "changed_skills": []}
    names = [s for s in skill_names(changed)
             if s != "skill-extraction" and (cfg.skills / s / "SKILL.md").is_file()]
    day = today()
    for s in names:
        meta = str(cfg.skills / s / ".meta")
        ctx.lib.run("meta", "init", meta, f"created={day}")
        ctx.lib.run("meta", "set", meta, "last_patched", day)
    to_commit = changed_since(cfg, snap)
    head0 = _head(cfg)
    commit_paths(cfg, to_commit, f"cairn: review of {os.path.basename(transcript)}")
    committed = bool(to_commit) and _head(cfg) != head0
    if to_commit and not committed:
        say(lf, f"review: WARNING {len(to_commit)} changed path(s) were not committed (HEAD did not move)")
    say(lf, f"review: done ({', '.join(names) or 'no skill changes'}; committed={committed})")
    return {"outcome": "done", "why": "", "rc": 0, "changed_skills": names if committed else []}


def _worker(ctx: Context, mode: str, model: str, lf) -> int:
    cfg = ctx.cfg
    q = _queue(cfg)
    stale = _timeout_s() + 300
    with mkdir_lock(cfg.state / ".review.lock", stale, lambda m: say(lf, f"review-worker: {m}"),
                    "review-worker: another worker is running") as held:
        if not held:
            return 0
        q.recover_orphans(epoch(), stale)
        if mode == "drain":
            q.retry_failed()
        gap_s = _int_env("CAIRN_REVIEW_MIN_GAP_MIN", 10) * 60
        cap = _int_env("CAIRN_REVIEW_DAILY_CAP", 25)
        min_msgs = _int_env("CAIRN_REVIEW_MIN_USER_MSGS", 3)
        while True:
            p = q.next_pending()
            if p is None:
                break
            if safe_sid(p.stem) is None:
                say(lf, f"review-worker: ignoring entry with unsafe name {p.name!r}")
                p.unlink(missing_ok=True)
                continue
            e = q.read(p)
            tp = str(e.get("transcript_path", ""))
            verdict, _, n = ctx.lib.run("transcript", "classify", tp, str(min_msgs)).value().partition("\t")
            n_msgs = int(n or 0)
            if verdict != "review":
                q.move(p, "skipped", {"outcome": "skipped", "why": verdict,
                                      "user_msgs_reviewed": n_msgs, "finished_at": epoch()})
                say(lf, f"review: skipped {p.stem} ({verdict})")
                continue
            allowed, why = q.may_start(epoch(), mode, gap_s, cap)
            if not allowed:
                say(lf, f"review-worker: deferring {p.stem} ({why})")
                break
            q.note_start(epoch())
            r = q.move(p, "running", {"started_at": epoch()})
            res = _review_one(ctx, tp, model, int(e.get("from_user_msg", 0)), lf)
            attempts = int(e.get("attempts", 0)) + (1 if res["outcome"] == "failed" else 0)
            q.move(r, res["outcome"], {**res, "attempts": attempts, "finished_at": epoch(),
                                       "user_msgs_reviewed": n_msgs})
            if mode == "after-session":
                break
        if mode == "drain":
            q.rotate(epoch(), 30)
            _rotate_log(lf)
    return 0


def _rotate_log(lf) -> None:
    try:
        if os.path.getsize(lf) > 1_000_000:
            os.replace(lf, f"{lf}.1")
    except OSError:
        pass


def cmd_review(ctx: Context, args: list[str]) -> int:
    cfg = ctx.cfg
    if os.environ.get("CAIRN_DISABLE"):
        return 0
    transcript, model, dry, mode = "", cfg.model_default, 0, "manual"
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--hook", "--enqueue"):
            mode = "enqueue"
        elif a == "--worker":
            mode = "after-session" if mode == "manual" else mode
        elif a == "--after-session":
            mode = "after-session"
        elif a == "--drain":
            mode = "drain"
        elif a == "--model":
            model = args[i + 1] if i + 1 < len(args) else cfg.model_default
            i += 1
        elif a == "--dry-run":
            dry = 1
        elif a.startswith("--"):
            from ..out import die
            die(f"review: unknown option {a}")
        else:
            transcript = a
        i += 1

    need_python()
    cfg.logs.mkdir(parents=True, exist_ok=True)
    lf = cfg.logs / "review.log"

    # recursion guard: never review (or enqueue) from inside a review's own claude run
    if os.environ.get("CAIRN_REVIEW_HOOK"):
        return 0
    if mode == "enqueue":
        return _enqueue(ctx, sys.stdin.read(), lf)
    if mode in ("after-session", "drain"):
        need_claude()
        return _worker(ctx, mode, model, lf)

    # manual: explicit path or discover-by-cwd, synchronous, no classify
    if not transcript:
        out = ctx.lib.run("transcript", "discover", str(cfg.claude_dir / "projects"),
                          os.getcwd(), "0", "0").out
        transcript = (out.split("\n")[0] if out else "").split("\t")[0]
    if not transcript or not os.path.isfile(transcript):
        from ..out import die
        die("no transcript to review (pass a path)")
    if dry == 1:
        flat = ctx.lib.run("transcript", "flatten-file", transcript, _FLAT_MAX).out.rstrip("\n")
        hdr("review (dry run)")
        info(f"transcript: {transcript}")
        info(f"flattened: {len(flat.encode('utf-8'))} chars")
        info(f"model: {model} — would run one scoped claude -p with the review prompt")
        return 0
    need_claude()
    with mkdir_lock(cfg.state / ".review.lock", _timeout_s() + 300, lambda m: say(lf, m),
                    "review: another review is running; try again shortly") as held:
        if not held:
            warn("another review is running; try again shortly")
            return 0
        res = _review_one(ctx, transcript, model, 0, lf)
    if res["outcome"] == "done":
        ok(f"review complete (log: {lf})")
    elif res["outcome"] == "failed":
        warn(f"review ended: {res['why']} (see {lf})")
    return 0
