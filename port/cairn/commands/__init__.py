"""Command handlers — one migration unit at a time. Each ``cmd_*(ctx, args) -> int``
returns the process exit code (or raises ``CairnDie``, mapped by the dispatcher).
"""
