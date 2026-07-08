#!/usr/bin/env bash
# =============================================================================
# cairn-setup.sh — install or update Cairn from this repo into ~/.claude.
#
#   ./cairn-setup.sh                 fresh install, or migrate an existing setup
#   ./cairn-setup.sh --enable-hooks  also turn on the SessionEnd review hook
#
# This is a thin bootstrap: it hands off to `bin/cairn install`, which copies
# the dispatcher into ~/.claude/cairn, lays down commands/templates/memory, and
# swaps the managed CLAUDE.md block. Idempotent and reversible (cairn uninstall).
# Already have skills? `cairn migrate` additionally scores them (model calls).
# =============================================================================
if [ -z "${BASH_VERSION:-}" ] && [ -f "$0" ]; then exec bash "$0" "$@"; fi
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$DIR/bin/cairn" ] || chmod +x "$DIR/bin/cairn" 2>/dev/null || true
exec "$DIR/bin/cairn" install "$@"
