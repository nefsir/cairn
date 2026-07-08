"""Managed-block text surgery — ports bash strip_block (awk) and the swap_block
trailing-blank trim. Column-1 anchored (a marker only matches at the start of a line),
and matches awk's record semantics: a trailing newline is a separator, not an empty
final record, and every kept line is emitted with a trailing newline (awk ORS).
"""
from __future__ import annotations


def _records(text: str) -> list[str]:
    recs = text.split("\n")
    if text.endswith("\n"):
        recs = recs[:-1]        # trailing \n is a separator, not an empty record
    return recs


def strip_block(text: str, begin: str, end: str) -> str:
    """Drop the [begin..end] block (inclusive of the marker lines), column-1 anchored.
    Returns kept lines each terminated by '\\n' (empty string if nothing kept)."""
    kept: list[str] = []
    skip = False
    for line in _records(text):
        if line.startswith(begin):
            skip = True
            continue
        if line.startswith(end):
            skip = False
            continue
        if not skip:
            kept.append(line)
    return "".join(l + "\n" for l in kept)


def trim_trailing_blank(text: str) -> str:
    """Drop trailing all-whitespace lines (bash swap_block's convergence awk). Returns
    kept lines each terminated by '\\n'."""
    recs = _records(text)
    n = len(recs)
    while n > 0 and recs[n - 1].strip() == "":
        n -= 1
    return "".join(recs[i] + "\n" for i in range(n))
