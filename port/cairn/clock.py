"""Time formatting — ``today()`` / ``ts()`` matching bash's ``date`` format strings,
with an optional frozen clock (``CAIRN_NOW``) so the differential harness can pin the
wall-clock identically for both builds. Formats are BSD/GNU-portable (no -d/-r).
"""
from __future__ import annotations

import os
from datetime import datetime


def _now() -> datetime:
    raw = os.environ.get("CAIRN_NOW")
    if raw:
        try:
            return datetime.fromtimestamp(int(raw))
        except (ValueError, OverflowError, OSError):
            pass
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.now()


def today() -> str:
    """``date +%Y-%m-%d``"""
    return _now().strftime("%Y-%m-%d")


def ts() -> str:
    """``date +%Y%m%d-%H%M%S`` — drives every ``.bak-<ts>`` / archive suffix."""
    return _now().strftime("%Y%m%d-%H%M%S")


def stamp() -> str:
    """``date '+%Y-%m-%d %H:%M:%S'`` — the ``say()`` log timestamp."""
    return _now().strftime("%Y-%m-%d %H:%M:%S")


def stamp_hm() -> str:
    """``date '+%Y-%m-%d %H:%M'`` — minute-precision header (status / curate / mine)."""
    return _now().strftime("%Y-%m-%d %H:%M")


def epoch() -> int:
    """Seconds since the epoch, honouring CAIRN_NOW (queue gap/cap/rotation math)."""
    return int(_now().timestamp())
