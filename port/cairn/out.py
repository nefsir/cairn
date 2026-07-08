"""Output primitives — byte-for-byte matches bash's ok/warn/info/die/hdr/say.

Color is emitted ONLY when stdout is a TTY and ``NO_COLOR`` is unset (gated on
stdout exactly like bash, even for ``die`` which writes to stderr). ``die`` raises
:class:`CairnDie`, which the dispatcher maps to a stderr ``ERROR:`` line + exit code
— reproducing bash ``die`` (immediate ``exit 1``) as observable behavior while staying
a clean, testable control-flow signal (no ``sys.exit`` buried in helpers).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import NoReturn

from . import clock


class CairnDie(Exception):
    """Raised by :func:`die`; carries the message and process exit code."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _colors() -> dict[str, str]:
    import os
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
        return {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m",
                "y": "\033[33m", "r": "\033[31m", "0": "\033[0m"}
    return {k: "" for k in ("dim", "b", "g", "y", "r", "0")}


def ok(msg: str) -> None:
    c = _colors()
    print(f"  {c['g']}✓{c['0']} {msg}")


def warn(msg: str) -> None:
    c = _colors()
    print(f"  {c['y']}!{c['0']} {msg}")


def info(msg: str) -> None:
    print(f"  {msg}")


def hdr(msg: str) -> None:
    c = _colors()
    print(f"{c['b']}== {msg} =={c['0']}")


def die(msg: str, code: int = 1) -> NoReturn:
    """Signal a fatal error (bash ``die``: stderr ``ERROR: <msg>`` + exit 1)."""
    raise CairnDie(msg, code)


def print_die(msg: str) -> None:
    """Render a :class:`CairnDie` message to stderr with the same gating as bash.

    Color is chosen from stdout's tty state (matching bash's stdout-gated vars) but
    written to stderr.
    """
    c = _colors()
    sys.stderr.write(f"{c['r']}ERROR:{c['0']} {msg}\n")


def say(logfile: Path, msg: str) -> None:
    """Timestamped line to stdout AND appended to ``logfile`` (best-effort)."""
    line = f"{clock.stamp()} {msg}"
    print(line)
    try:
        with open(logfile, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass  # tee -a "$lf" || true — a log-write failure never aborts the caller
