"""cairn test — run the bash test suite (static + unit + integration). Ports cmd_test:
locate the runner (repo, else installed STATE), and shell out to bash with CAIRN_BIN /
CAIRN_REPO set, propagating the runner's exit code.
"""
from __future__ import annotations

import os
import subprocess

from ..context import Context
from ..out import die


def cmd_test(ctx: Context, args: list[str]) -> int:
    cfg = ctx.cfg
    runner = cfg.cairn_home / "tests" / "run-tests.sh"
    if not runner.is_file():
        runner = cfg.state / "tests" / "run-tests.sh"
    if not runner.is_file():
        die("test runner not found (run from the repo, or reinstall)")
    env = os.environ.copy()
    env["CAIRN_BIN"] = str(cfg.cairn_home / "bin" / "cairn")
    env["CAIRN_REPO"] = str(cfg.cairn_home)
    return subprocess.run(["bash", str(runner), *args], env=env).returncode
