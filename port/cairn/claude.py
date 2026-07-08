"""Resilient `claude -p` runner (data steps) — ports bash run_claude's 3-way contract:
return 0 on success, 1 on a transient error that exhausted retries, 2 on a deterministic
failure. Quadratic backoff (attempt²·5s); maxretry=0 means a single attempt. Plus the
quality scorer used by assess.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
from pathlib import Path

from .config import TRANSIENT_RE, Config
from .out import say

SCORE_PROMPT = """You are assessing ONE Claude Code skill for REUSABILITY/QUALITY. On stdin is
its SKILL.md. Reply with ONLY a single digit 1-5, nothing else:
  5 = broad, well-formed, class-level skill that transfers across projects
  4 = reusable within a tech stack or domain, clear triggers + procedure
  3 = reusable within one setup, parameterizable
  2 = mostly specific; only a small transferable core
  1 = hyper-specific one-off / runbook / malformed — not really a skill."""


def run_claude(prompt: str, model: str, infile: str, outf: str, errf: str,
               maxretry: int, label: str, lf: str) -> int:
    attempt = 0
    transient = False
    while True:
        attempt += 1
        with open(outf, "wb") as out, open(errf, "wb") as err:
            argv = ["claude", "-p", prompt, "--model", model, "--max-turns", "2"]
            if infile:
                with open(infile, "rb") as inp:
                    rc = subprocess.run(argv, stdin=inp, stdout=out, stderr=err).returncode
            else:
                rc = subprocess.run(argv, stdout=out, stderr=err).returncode
        if rc == 0:
            return 0
        err_text = Path(errf).read_text(encoding="utf-8", errors="replace")
        if re.search(TRANSIENT_RE, err_text, re.IGNORECASE):
            transient = True
            if attempt <= maxretry:
                wait = attempt * attempt * 5
                say(Path(lf), f"  transient (attempt {attempt}/{maxretry}) on {label}; retry in {wait}s")
                time.sleep(wait)
                continue
        break
    try:
        with open(lf, "a", encoding="utf-8") as log:
            log.write(Path(errf).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        pass
    return 1 if transient else 2


def score_one_skill(cfg: Config, d: str) -> str:
    """Score one skill's dir → '1'..'5' (or '' on non-zero rc). Ports score_one_skill."""
    import os
    import shutil
    td = tempfile.mkdtemp()
    try:
        outf = os.path.join(td, "score.out")
        errf = os.path.join(td, "score.err")
        rc = run_claude(SCORE_PROMPT, cfg.model_default, os.path.join(d, "SKILL.md"),
                        outf, errf, 2, os.path.basename(d), str(cfg.logs / "assess.log"))
        if rc == 0:
            digits = [c for c in Path(outf).read_text(encoding="utf-8", errors="replace") if c in "12345"]
            return digits[0] if digits else ""
        return ""
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)
