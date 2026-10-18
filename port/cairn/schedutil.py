"""Scheduler helpers — ports the SCHED_* vars + sched_disable. Platform-forked:
launchd (macOS) / cron (Linux); the macOS branch is gated on ``platform.system()``.
(schedule/maintain enable + the Windows schtasks backend land with unit 17.)
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from .config import Config
from .out import ok

SCHED_LABEL = "com.cairn.maintain"
SCHED_CRON_MARK = "# cairn maintain"
SCHED_WIN_TASK = "cairn-maintain"   # Windows Task Scheduler task name


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _win_task_exists() -> bool:
    return subprocess.run(["schtasks", "/Query", "/TN", SCHED_WIN_TASK],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def sched_plist() -> Path:
    home = Path(os.environ.get("HOME") or Path.home())
    return home / "Library" / "LaunchAgents" / f"{SCHED_LABEL}.plist"


def _has(cmd: str) -> bool:
    import shutil
    return shutil.which(cmd) is not None


_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{python}</string><string>{bin}</string><string>maintain</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{h}</integer><key>Minute</key><integer>{m}</integer></dict>
  <key>StandardOutPath</key><string>{logs}/maintain.launchd.log</string>
  <key>StandardErrorPath</key><string>{logs}/maintain.launchd.log</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
"""


def sched_status(cfg: Config) -> str:
    if _is_windows():
        return "on (schtasks)" if _has("schtasks") and _win_task_exists() else "off"
    if platform.system() == "Darwin" and sched_plist().is_file():
        return "on (launchd)"
    if _has("crontab"):
        cur = subprocess.run(["crontab", "-l"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             encoding="utf-8", errors="replace").stdout
        if any(SCHED_CRON_MARK in line for line in cur.split("\n")):
            return "on (cron)"
    return "off"


def sched_enable(cfg: Config, t: str) -> None:
    from .out import die, info, ok, warn
    h = int(t.split(":")[0], 10)
    m = int(t.split(":")[1], 10)
    cfg.logs.mkdir(parents=True, exist_ok=True)
    if _is_windows():   # NET-NEW (no bash oracle): Windows Task Scheduler
        entry = cfg.state / "bin" / "cairn.py"
        if not entry.is_file():
            die(f"run 'cairn install' first (no dispatcher at {entry})")
        if not _has("schtasks"):
            warn(f"schtasks not found — schedule '{entry} maintain' yourself")
            return
        subprocess.run(["schtasks", "/Create", "/TN", SCHED_WIN_TASK, "/TR",
                        f'python "{entry}" maintain', "/SC", "DAILY", "/ST", t, "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok(f"nightly maintenance scheduled at {t} (schtasks: {SCHED_WIN_TASK})")
        info("runs: cairn maintain = improve (model calls) + curate --apply-lifecycle (gentle). Disable: cairn schedule --off")
        return
    binp = cfg.state / "bin" / "cairn"
    if not (binp.is_file() and os.access(binp, os.X_OK)):
        die(f"run 'cairn install' first (no dispatcher at {binp})")
    if platform.system() == "Darwin":
        plist = sched_plist()
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(_PLIST.format(label=SCHED_LABEL, python=sys.executable, bin=binp, h=h, m=m, logs=cfg.logs), encoding="utf-8")
        if _has("launchctl"):
            uid = os.getuid()
            subprocess.run(["launchctl", "bootout", f"gui/{uid}/{SCHED_LABEL}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode != 0:
                subprocess.run(["launchctl", "load", "-w", str(plist)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok(f"nightly maintenance scheduled at {t} (launchd: {plist})")
    else:
        if not _has("crontab"):
            warn(f"crontab not found — schedule '{binp} maintain' yourself")
            return
        cur = subprocess.run(["crontab", "-l"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             encoding="utf-8", errors="replace").stdout
        kept = [l for l in cur.split("\n") if SCHED_CRON_MARK not in l]
        # drop a trailing empty element from the split so we don't add a blank line
        while kept and kept[-1] == "":
            kept.pop()
        new_line = f'{m} {h} * * * "{binp}" maintain >> "{cfg.logs}/maintain.log" 2>&1 {SCHED_CRON_MARK}'
        payload = "\n".join(kept + [new_line]) + "\n"
        subprocess.run(["crontab", "-"], input=payload, encoding="utf-8",
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok(f"nightly maintenance scheduled at {t} (cron)")
    info("runs: cairn maintain = improve (model calls) + curate --apply-lifecycle (gentle). Disable: cairn schedule --off")


def sched_disable(cfg: Config) -> None:
    removed = False
    if _is_windows():   # NET-NEW: Windows Task Scheduler
        if _has("schtasks") and _win_task_exists():
            subprocess.run(["schtasks", "/Delete", "/TN", SCHED_WIN_TASK, "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            removed = True
        ok("nightly maintenance schedule removed" if removed else "no maintenance schedule was set")
        return
    plist = sched_plist()
    if platform.system() == "Darwin" and plist.is_file():
        if _has("launchctl"):
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{SCHED_LABEL}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            plist.unlink()
        except OSError:
            pass
        removed = True
    if _has("crontab"):
        cur = subprocess.run(["crontab", "-l"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             encoding="utf-8", errors="replace").stdout
        if any(SCHED_CRON_MARK in line for line in cur.split("\n")):
            kept = "\n".join(l for l in cur.split("\n") if SCHED_CRON_MARK not in l)
            subprocess.run(["crontab", "-"], input=kept, encoding="utf-8",
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            removed = True
    ok("nightly maintenance schedule removed" if removed else "no maintenance schedule was set")
