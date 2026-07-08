#!/usr/bin/env bash
# Flip the active dispatcher from bash to the (proven-equivalent) Python port.
# Reversible. Run when you're ready to retire bash as the ACTIVE cairn; bash stays
# in the repo as bin/cairn.bash — the frozen CI equivalence oracle.
#
# After this:  bin/cairn = Python. `cairn install` deploys the Python package to
# ~/.claude/cairn, points hooks at it, and everything (maintain/schedule/test) uses
# Python. Re-run `cairn install --enable-hooks` to upgrade an existing bash install
# in place (enable_hooks UPSERTS — the old bash hook commands are replaced, not
# duplicated; skills/.meta/memory/foreign-hooks are preserved).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f bin/cairn ] && head -1 bin/cairn | grep -q bash && {
  git mv bin/cairn bin/cairn.bash
  git mv bin/cairn.py bin/cairn
  chmod +x bin/cairn
  echo "Flipped: bin/cairn is now Python; bash preserved as bin/cairn.bash (CI oracle)."
  echo "Next: run  ./bin/cairn install --enable-hooks   to deploy Python + repoint hooks."
  echo "Update the harness oracle to bin/cairn.bash:  diff-cairn.py --oracle bin/cairn.bash --candidate bin/cairn"
} || echo "bin/cairn is not the bash script (already flipped?). Nothing to do."
# To revert:  git mv bin/cairn bin/cairn.py && git mv bin/cairn.bash bin/cairn
