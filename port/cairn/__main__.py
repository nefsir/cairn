"""``python -m cairn`` entry — resolves CAIRN_HOME by walking up to the dir holding
``cairn-logo.txt`` (so assets resolve regardless of invocation path), then dispatches.
"""
import sys
from pathlib import Path

from .cli import main


def _find_cairn_home() -> Path:
    here = Path(__file__).resolve()
    for d in [here.parent, *here.parents]:
        if (d / "cairn-logo.txt").is_file():
            return d
    return here.parent.parent.parent  # fallback: repo root (port/cairn/.. -> repo)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", newline="\n")
        except (AttributeError, ValueError):
            pass
    sys.exit(main(sys.argv, _find_cairn_home()))
