"""Portable mkdir-EXCL mutex with stale-lock reclaim (shared by maintain and review).
mkdir is atomic on every OS cairn supports, unlike flock (POSIX only)."""
from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


def _acquire(lock: Path, stale_after_s: int, log: Callable[[str], None], busy_msg: str) -> bool:
    try:
        os.mkdir(lock)
        return True
    except FileExistsError:
        pass
    try:
        lmt = int(os.path.getmtime(lock))
    except OSError:
        lmt = 0
    age = int(time.time()) - lmt
    if lmt > 0 and age > stale_after_s:
        log(f"reclaiming stale lock ({age}s old)")
        try:
            os.rmdir(lock)
        except OSError:
            pass
        try:
            os.mkdir(lock)
            return True
        except OSError:
            log("SKIP: could not reclaim lock")
            return False
    log(busy_msg)
    return False


def touch(lock: Path) -> None:
    """Heartbeat: refresh the lock's mtime so a long-running holder is not reclaimed as stale."""
    try:
        os.utime(lock)
    except OSError:
        pass


@contextmanager
def mkdir_lock(lock: Path, stale_after_s: int, log: Callable[[str], None],
               busy_msg: str) -> Iterator[bool]:
    lock.parent.mkdir(parents=True, exist_ok=True)
    held = _acquire(lock, stale_after_s, log, busy_msg)
    try:
        yield held
    finally:
        if held:
            try:
                os.rmdir(lock)
            except OSError:
                pass
