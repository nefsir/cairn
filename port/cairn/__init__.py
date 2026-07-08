"""cairn — a self-improving skill & memory system for Claude Code.

Cross-platform Python port of the bash ``bin/cairn`` dispatcher. Behavior-preserving:
observable output, files, exit codes and git state match the bash oracle byte-for-byte
on macOS/Linux (proven by ``tests/diff-harness``). See ``port/PLAN.md``.
"""

CAIRN_VERSION = "2.0.0-dev"

__all__ = ["CAIRN_VERSION"]
