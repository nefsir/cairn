"""In-process replacement for bash's ``py <helper> <args…>`` seam
(``python3 "$LIB/<helper>.py" "$@"``).

Hybrid packaging: the lib scripts stay the single source of truth and remain
CLI-invocable (the unit tier calls ``python3 lib/x.py`` unchanged); this seam loads
each one as a module and calls its ``main(argv)`` in-process — same code, no process
spawn — capturing stdout/stderr/exit-code exactly as a subprocess would. Faithfulness
is proven by ``tests/diff-harness/lib_parity.py`` (in-process == subprocess, byte for
byte). The libs read env only inside ``main`` and take paths as args, so a module can
be safely imported once and cached.
"""
from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class LibResult:
    """Outcome of one lib invocation, mirroring a subprocess result."""
    rc: int
    out: str
    err: str

    def value(self) -> str:
        """The stdout with a single trailing newline stripped — what bash's
        ``$(py …)`` command substitution yields."""
        return self.out[:-1] if self.out.endswith("\n") else self.out


class LibRunner:
    """Invokes ``lib/<helper>.py::main`` in-process with captured streams."""

    def __init__(self, lib_dir: Path) -> None:
        self._lib_dir = Path(lib_dir)
        self._cache: dict[str, ModuleType] = {}

    def _module(self, helper: str) -> ModuleType:
        mod = self._cache.get(helper)
        if mod is None:
            path = self._lib_dir / f"{helper}.py"
            spec = importlib.util.spec_from_file_location(f"_cairnlib_{helper}", path)
            if spec is None or spec.loader is None:
                raise FileNotFoundError(str(path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)   # side-effect-free: defs only, __main__ guarded
            self._cache[helper] = mod
        return mod

    def run(self, helper: str, *args: object, stdin: str = "") -> LibResult:
        """Run ``lib/<helper>.py`` with ``args`` (and optional stdin); capture output.

        Reproduces the subprocess contract: ``argv[0]`` is the script path, ``main``
        returns the exit code (``None`` -> 0), and a mid-run ``sys.exit`` is honored.
        """
        mod = self._module(helper)
        argv = [str(self._lib_dir / f"{helper}.py"), *(str(a) for a in args)]
        out, err = io.StringIO(), io.StringIO()
        saved_argv, saved_stdin = sys.argv, sys.stdin
        sys.argv = argv
        sys.stdin = io.StringIO(stdin)
        rc = 0
        try:
            with redirect_stdout(out), redirect_stderr(err):
                ret = mod.main(argv)
            rc = 0 if ret is None else int(ret)
        except SystemExit as exc:
            code = exc.code
            rc = 0 if code is None else (code if isinstance(code, int) else 1)
        except Exception:  # noqa: BLE001 — contain a lib bug to rc 1, like a crashing
            import traceback  # subprocess would (never reached on cairn's own callsites,
            with redirect_stderr(err):  # which always pass valid args)
                traceback.print_exc()
            rc = 1
        finally:
            sys.argv, sys.stdin = saved_argv, saved_stdin
        return LibResult(rc, out.getvalue(), err.getvalue())
