"""cairn review [TRANSCRIPT | --hook | --dry-run] [--model M] — post-session review.

Ports bash cmd_review: the two-layer recursion guard, transcript location (hook stdin
/ discover), redact-before-claude via the transcript lib, the single scoped claude -p
(output appended to review.log, CAIRN_REVIEW_HOOK on its env to guard the nested
SessionEnd), touched-skill telemetry, whole-tree commit, and always-exit-0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from ..clock import today
from ..config import Config
from ..context import Context
from ..gitutil import skills_changed_names, skills_commit, skills_is_repo
from ..helpers import need_claude, need_python
from ..out import hdr, info, ok, say, warn

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

End by printing a 1-3 line summary of exactly what you changed (or "no changes")."""


def _hook_transcript() -> str:
    try:
        return json.load(sys.stdin).get("transcript_path", "") or ""
    except Exception:
        return ""


def cmd_review(ctx: Context, args: list[str]) -> int:
    cfg = ctx.cfg
    transcript = ""
    hook = 0
    model = cfg.model_default
    dry = 0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--hook":
            hook = 1
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

    # recursion guard: the hook exports CAIRN_REVIEW_HOOK; never review our own run
    if os.environ.get("CAIRN_REVIEW_HOOK") and hook == 0:
        return 0

    if hook == 1 and not transcript:
        transcript = _hook_transcript()
    if not transcript:
        out = ctx.lib.run("transcript", "discover", str(cfg.claude_dir / "projects"),
                          os.getcwd(), "0", "0").out
        first = out.split("\n")[0] if out else ""
        transcript = first.split("\t")[0]

    if not transcript or not os.path.isfile(transcript):
        say(lf, "review: no transcript found")
        if hook == 1:
            return 0
        from ..out import die
        die("no transcript to review (pass a path)")

    flat = ctx.lib.run("transcript", "flatten-file", transcript, "60000").out.rstrip("\n")
    if flat == "":
        say(lf, f"review: empty transcript ({transcript})")
        return 0

    if dry == 1:
        hdr("review (dry run)")
        info(f"transcript: {transcript}")
        info(f"flattened: {len(flat.encode('utf-8'))} chars")
        info(f"model: {model} — would run one scoped claude -p with the review prompt")
        return 0

    need_claude()
    say(lf, f"review: {transcript} (model {model})")
    prompt = REVIEW_PROMPT.replace("__SKILLS__", str(cfg.skills)).replace("__TEMPLATES__", str(cfg.templates))

    env = os.environ.copy()
    env["CAIRN_REVIEW_HOOK"] = "1"
    with open(lf, "ab") as log:
        rc = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--max-turns", "30",
             "--permission-mode", "acceptEdits", "--allowedTools", _ALLOWED],
            input=flat.encode("utf-8"), stdout=log, stderr=subprocess.STDOUT, env=env,
        ).returncode

    if skills_is_repo(cfg):
        for s in skills_changed_names(cfg):
            if s and s != "skill-extraction" and (cfg.skills / s / "SKILL.md").is_file():
                meta = str(cfg.skills / s / ".meta")
                day = today()
                ctx.lib.run("meta", "init", meta, f"created={day}", f"last_used={day}")
                ctx.lib.run("meta", "set", meta, "last_used", day)
                ctx.lib.run("meta", "bump", meta, "use_count")
    skills_commit(cfg, f"cairn: review of {os.path.basename(transcript)}")

    if rc == 0:
        say(lf, "review: done")
        ok(f"review complete (log: {lf})")
    else:
        say(lf, f"review: claude exited {rc}")
        if hook == 0:
            warn(f"review ended with code {rc} (see {lf})")
    return 0
