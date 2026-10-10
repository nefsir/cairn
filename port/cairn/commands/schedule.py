"""cairn schedule [HH:MM|--off|--status] + cairn maintain — the nightly job. Ports
cmd_schedule + cmd_maintain: platform-forked launchd/cron enable, the mkdir-EXCL mutex
with 6h stale reclaim and cleanup-only-after-acquisition, and PATH augmentation so a
minimal launchd/cron env can still find claude. maintain shells out to the dispatcher
for improve + curate (matching bash's SELF_DIR/cairn subprocess).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from ..context import Context
from ..lockutil import mkdir_lock
from ..out import die, info, ok, say
from ..schedutil import sched_disable, sched_enable, sched_status

_HHMM = re.compile(r'([01][0-9]|2[0-3]|[0-9]):[0-5][0-9]')


def cmd_schedule(ctx: Context, args: list[str]) -> int:
    cfg = ctx.cfg
    first = args[0] if args else ""
    if first in ("", "--status", "status"):
        # bash calls sched_status twice (once per $(…)); each may hit crontab -l
        info(f"nightly maintenance: {sched_status(cfg)}")
        if sched_status(cfg) != "off":
            info("  runs cairn maintain (improve + curate --apply-lifecycle); disable: cairn schedule --off")
        return 0
    if first in ("--off", "off", "--disable"):
        sched_disable(cfg)
        return 0
    if _HHMM.fullmatch(first):
        sched_enable(cfg, first)
        return 0
    die("usage: cairn schedule HH:MM  |  --off  |  --status   (pass a time to enable, e.g. 03:30)")


def _sub(binp: Path, lf: Path, *cmd: str) -> int:
    with open(lf, "ab") as log:
        return subprocess.run([str(binp), *cmd], stdout=log, stderr=subprocess.STDOUT).returncode


def cmd_maintain(ctx: Context, args: list[str]) -> int:
    cfg = ctx.cfg
    cfg.logs.mkdir(parents=True, exist_ok=True)
    lf = cfg.logs / "maintain.log"
    binp = cfg.cairn_home / "bin" / "cairn"
    home = os.environ.get("HOME") or str(Path.home())
    os.environ["PATH"] = f"{home}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + os.environ.get("PATH", "")
    lock = cfg.state / ".maintain.lock"
    cfg.state.mkdir(parents=True, exist_ok=True)
    with mkdir_lock(lock, 21600, lambda m: say(lf, m),
                    f"SKIP: another maintain run holds {lock}") as held:
        if not held:
            return 0
        say(lf, "maintain: start")
        if shutil.which("claude"):
            if _sub(binp, lf, "improve") != 0:
                say(lf, "improve ended with errors (continuing)")
        else:
            say(lf, "improve skipped (claude not on PATH)")
        if _sub(binp, lf, "curate", "--apply-lifecycle") != 0:
            say(lf, "curate ended with errors")
        say(lf, "maintain: done")
        ok(f"maintenance complete (log: {lf})")
    return 0
