"""Directory queue for post-session reviews: one JSON file per session, one directory
per state, every transition an atomic rename. Plain files so `ls` shows the state."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

STATES = ("pending", "running", "done", "skipped", "failed")
_SID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def safe_sid(sid: str) -> str | None:
    return sid if isinstance(sid, str) and _SID.match(sid) else None


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


class Queue:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def ensure(self) -> None:
        for st in STATES:
            (self.root / st).mkdir(parents=True, exist_ok=True)

    def find(self, sid: str) -> tuple[str, Path] | None:
        for st in STATES:
            p = self.root / st / f"{sid}.json"
            if p.is_file():
                return st, p
        return None

    def read(self, p: Path) -> dict:
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, p: Path, data: dict) -> None:
        tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)

    def put(self, state: str, sid: str, data: dict) -> Path:
        p = self.root / state / f"{sid}.json"
        self._write(p, data)
        return p

    def move(self, p: Path, state: str, updates: dict) -> Path:
        data = self.read(p)
        data.update(updates)
        self._write(p, data)
        dst = self.root / state / p.name
        os.replace(p, dst)
        return dst

    def next_pending(self) -> Path | None:
        items = [(self.read(p).get("enqueued_at", 0), p.name, p)
                 for p in (self.root / "pending").glob("*.json")]
        return min(items)[2] if items else None

    def _last(self) -> int:
        try:
            return int((self.root / ".last-review").read_text().strip() or 0)
        except (OSError, ValueError):
            return 0

    def _daily(self, now: int) -> Path:
        return self.root / f"daily-{_day(now)}"

    def _today_count(self, now: int) -> int:
        try:
            return int(self._daily(now).read_text().strip() or 0)
        except (OSError, ValueError):
            return 0

    def may_start(self, now: int, mode: str, gap_s: int, cap: int) -> tuple[bool, str]:
        if mode == "manual":
            return True, ""
        if self._today_count(now) >= cap:
            return False, f"daily cap {cap} reached"
        if mode == "after-session" and now - self._last() < gap_s:
            return False, f"gap {gap_s}s not elapsed"
        return True, ""

    def note_start(self, now: int) -> None:
        (self.root / ".last-review").write_text(str(now))
        self._daily(now).write_text(str(self._today_count(now) + 1))

    def recover_orphans(self, now: int, stale_s: int) -> int:
        n = 0
        for p in (self.root / "running").glob("*.json"):
            if now - int(self.read(p).get("started_at", 0)) > stale_s:
                self.move(p, "pending", {"recovered_at": now})
                n += 1
        return n

    def retry_failed(self) -> int:
        n = 0
        for p in (self.root / "failed").glob("*.json"):
            if int(self.read(p).get("attempts", 0)) == 1:
                self.move(p, "pending", {})
                n += 1
        return n

    def rotate(self, now: int, days: int) -> int:
        cutoff = now - days * 86400
        n = 0
        for st in ("done", "skipped"):
            for p in (self.root / st).glob("*.json"):
                if int(self.read(p).get("finished_at", now)) < cutoff:
                    p.unlink(missing_ok=True)
                    n += 1
        keep = _day(cutoff)
        for p in self.root.glob("daily-*"):
            if p.name[len("daily-"):] < keep:
                p.unlink(missing_ok=True)
        return n

    def counts(self, now: int) -> dict[str, int]:
        week = now - 7 * 86400
        c = {"pending": 0, "running": 0, "failed": 0, "done_7d": 0, "skipped_7d": 0, "last_done": 0}
        for st in ("pending", "running", "failed"):
            c[st] = sum(1 for _ in (self.root / st).glob("*.json"))
        for st in ("done", "skipped"):
            for p in (self.root / st).glob("*.json"):
                fin = int(self.read(p).get("finished_at", 0))
                if fin >= week:
                    c[f"{st}_7d"] += 1
                if st == "done":
                    c["last_done"] = max(c["last_done"], fin)
        return c
