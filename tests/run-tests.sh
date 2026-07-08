#!/usr/bin/env bash
# =============================================================================
# run-tests.sh — Cairn test suite (static + unit + integration), all offline.
#
#   ./tests/run-tests.sh [static|unit|integration]   (default: all)
#   cairn test [tier]
#
# Integration runs entirely in a throwaway $HOME with shimmed claude/crontab/
# pmset — it never touches your real ~/.claude. Asserts idempotency and that the
# installed commands/templates are byte-identical to the repo assets.
# =============================================================================
if [ -z "${BASH_VERSION:-}" ] && [ -f "$0" ]; then exec bash "$0" "$@"; fi
set -uo pipefail

# locate repo + dispatcher
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="${CAIRN_REPO:-$(cd "$HERE/.." && pwd)}"
CAIRN="${CAIRN_BIN:-$REPO/bin/cairn}"
# bash reference for the bash-only static checks (bin/cairn is now the Python entry;
# the proven-equivalent bash implementation ships as bin/cairn.bash). Fall back to
# $CAIRN when there is no .bash (pre-flip repos still run the same checks).
BASH_REF="$REPO/bin/cairn.bash"; [ -f "$BASH_REF" ] || BASH_REF="$CAIRN"
LIB="$REPO/lib"
ASSETS="$REPO/assets"

if [ -t 1 ]; then G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; B=$'\033[1m'; Z=$'\033[0m'; else G=""; R=""; Y=""; B=""; Z=""; fi
PASS=0; FAIL=0; FAILED_NAMES=""
ok()   { PASS=$((PASS+1)); printf '  %s✓%s %s\n' "$G" "$Z" "$1"; }
bad()  { FAIL=$((FAIL+1)); FAILED_NAMES="$FAILED_NAMES\n    - $1"; printf '  %s✗%s %s\n' "$R" "$Z" "$1"; }
skip() { printf '  %s~%s %s (skipped)\n' "$Y" "$Z" "$1"; }
hdr()  { printf '\n%s== %s ==%s\n' "$B" "$1" "$Z"; }

# assert <desc> : pass if last command (run before) exit 0 — use the helpers below
check()    { if [ "$1" -eq 0 ]; then ok "$2"; else bad "$2"; fi; }            # check <rc> <desc>
expect_eq(){ if [ "$1" = "$2" ]; then ok "$3"; else bad "$3 (got [$1] want [$2])"; fi; }
expect_file(){ if [ -e "$1" ]; then ok "$2"; else bad "$2 (missing $1)"; fi; }
expect_nofile(){ if [ ! -e "$1" ]; then ok "$2"; else bad "$2 (present: $1)"; fi; }
expect_grep(){ if grep -qF "$2" "$1" 2>/dev/null; then ok "$3"; else bad "$3 (no '$2' in $1)"; fi; }
expect_nogrep(){ if ! grep -qF "$2" "$1" 2>/dev/null; then ok "$3"; else bad "$3 ('$2' still in $1)"; fi; }

# =============================================================================
tier_static() {
  hdr "static"
  local f
  # The project REQUIRES bash 3.2 (stock macOS). Parse under the REAL system bash
  # when present — NOT just PATH bash, which on a dev box is bash 5 and hides
  # bash-3.2-only breakage (e.g. a here-document nested in a command substitution).
  local B32="/bin/bash"; [ -x "$B32" ] || B32="bash"
  local bver; bver="$("$B32" --version 2>/dev/null | sed -n '1s/.*version \([0-9]*\.[0-9]*\).*/\1/p')"
  for f in "$BASH_REF" "$HERE/run-tests.sh"; do
    [ -f "$f" ] || { bad "exists: $f"; continue; }
    "$B32" -n "$f" 2>/dev/null; check $? "$B32 ($bver) -n $(basename "$f")"
  done
  if [ -f "$REPO/cairn-setup.sh" ]; then
    "$B32" -n "$REPO/cairn-setup.sh" 2>/dev/null; check $? "$B32 -n cairn-setup.sh"
  fi
  case "$bver" in 3.2) ok "syntax verified against the bash-3.2 contract ($B32)";; *) skip "system bash is $bver, not 3.2 — bash-3.2 contract only partly verified";; esac
  for f in "$LIB"/*.py; do
    python3 -m py_compile "$f" 2>/dev/null; check $? "py_compile $(basename "$f")"
  done
  # the Python port itself must compile (entry + package)
  if [ -d "$REPO/port/cairn" ]; then
    python3 -m py_compile "$REPO/bin/cairn" $(find "$REPO/port/cairn" -name '*.py') 2>/dev/null
    check $? "py_compile the Python port (bin/cairn + port/cairn)"
  fi
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck -S error "$BASH_REF" >/dev/null 2>&1; check $? "shellcheck -S error bin/cairn.bash"
  else
    skip "shellcheck not installed"
  fi
  # the review prompt must use interpolated paths, never a hardcoded ~/.claude
  # skills dir (which would edit the real config under a relocated CLAUDE_DIR)
  if grep -q '__SKILLS__' "$BASH_REF" && grep -q 'REVIEW_PROMPT//__SKILLS__' "$BASH_REF"; then
    ok "review prompt binds to interpolated \$SKILLS (not hardcoded ~/.claude)"
  else
    bad "review prompt path interpolation missing"
  fi
}

# =============================================================================
tier_unit() {
  hdr "unit — lib helpers"
  local T; T="$(mktemp -d)"
  # --- meta.py ---
  python3 "$LIB/meta.py" init "$T/.meta" created=2026-01-01 last_used=2026-01-01
  expect_eq "$(python3 "$LIB/meta.py" get "$T/.meta" provenance)" "managed" "meta init defaults provenance=managed"
  python3 "$LIB/meta.py" set "$T/.meta" quality 4
  expect_eq "$(python3 "$LIB/meta.py" get "$T/.meta" quality)" "4" "meta set/get quality"
  python3 "$LIB/meta.py" bump "$T/.meta" use_count; python3 "$LIB/meta.py" bump "$T/.meta" use_count
  expect_eq "$(python3 "$LIB/meta.py" get "$T/.meta" use_count)" "2" "meta bump use_count"
  python3 "$LIB/meta.py" init "$T/.meta" provenance=CLOBBER >/dev/null 2>&1
  expect_eq "$(python3 "$LIB/meta.py" get "$T/.meta" provenance)" "managed" "meta init never clobbers existing"
  expect_eq "$(python3 "$LIB/meta.py" dump "$T/.meta" | head -1)" "provenance=managed" "meta dump canonical order"

  # --- memory.py ---
  python3 "$LIB/memory.py" init "$T/U.md" 1375 "USER"
  expect_nogrep "$T/U.md" "§" "memory header carries no § delimiter"
  python3 "$LIB/memory.py" add "$T/U.md" 1375 "prefers terse answers" >/dev/null
  python3 "$LIB/memory.py" add "$T/U.md" 1375 "uses jvm spring" >/dev/null
  expect_grep "$T/U.md" "prefers terse answers" "memory add appends entry"
  python3 "$LIB/memory.py" add "$T/U.md" 40 "way too long to ever fit in forty characters" >/dev/null 2>&1
  expect_eq "$?" "3" "memory add rejects over-cap (exit 3)"
  python3 "$LIB/memory.py" replace "$T/U.md" 1375 "terse" "prefers VERY terse" >/dev/null
  expect_grep "$T/U.md" "VERY terse" "memory replace by unique substring"
  python3 "$LIB/memory.py" remove "$T/U.md" "jvm" >/dev/null
  expect_nogrep "$T/U.md" "jvm" "memory remove by unique substring"

  # --- lifecycle.py ---
  expect_eq "$(python3 "$LIB/lifecycle.py" days 2026-06-14 2026-05-15)" "30" "lifecycle days-between"
  expect_eq "$(python3 "$LIB/lifecycle.py" state 2026-06-14 2026-06-13 30 90)" "active" "lifecycle active (fresh)"
  expect_eq "$(python3 "$LIB/lifecycle.py" state 2026-06-14 2026-05-01 30 90)" "stale" "lifecycle stale @30d"
  expect_eq "$(python3 "$LIB/lifecycle.py" state 2026-06-14 2026-01-01 30 90)" "archived" "lifecycle archived @90d"
  # propose skips pinned/bundled
  local SK="$T/skills"; mkdir -p "$SK/old" "$SK/pin" "$SK/bun"
  for s in old pin bun; do printf -- '---\nname: %s\ndescription: x\n---\n' "$s" > "$SK/$s/SKILL.md"; python3 "$LIB/meta.py" init "$SK/$s/.meta" created=2026-01-01 last_used=2026-01-01; done
  python3 "$LIB/meta.py" set "$SK/pin/.meta" pinned true
  python3 "$LIB/meta.py" set "$SK/bun/.meta" provenance bundled
  local prop; prop="$(python3 "$LIB/lifecycle.py" propose "$SK" 2026-06-14 30 90)"
  expect_eq "$(printf '%s\n' "$prop" | grep -c .)" "1" "lifecycle propose skips pinned+bundled (only 'old')"
  printf '%s\n' "$prop" | grep -q '^old' && ok "lifecycle propose flags the aged managed skill" || bad "lifecycle propose flags 'old'"

  # --- cluster.py ---
  printf '%s\n' \
    '{"name":"mysql-read","description":"mysql read latency hikari pool slow query explain"}' \
    '{"name":"mysql-write","description":"mysql write latency hikari pool slow query explain"}' \
    '{"name":"figma","description":"figma components design tokens variants"}' > "$T/c.jsonl"
  mkdir -p "$T/cl"
  local sum; sum="$(python3 "$LIB/cluster.py" candidates "$T/c.jsonl" 0.30 "$T/cl")"
  case "$sum" in *candidates=3*) ok "cluster candidates counts inputs";; *) bad "cluster candidates count (got: $sum)";; esac
  case "$sum" in *multi=1*) ok "cluster groups the two mysql candidates (multi=1)";; *) bad "cluster multi=1 (got: $sum)";; esac

  # --- transcript.py redaction ---
  local J="$T/s.jsonl"
  printf '%s\n' '{"type":"user","cwd":"/x","message":{"content":[{"type":"text","text":"api_key=sk-SECRETVALUE12345 hello"}]}}' > "$J"
  # a realistic >=40-char opaque token (the long-token backstop fires at 40+)
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"token here ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD ok"}]}}' >> "$J"
  local flat; flat="$(python3 "$LIB/transcript.py" flatten-file "$J" 60000)"
  case "$flat" in *"sk-SECRETVALUE12345"*) bad "transcript redacts api_key value";; *"<redacted>"*) ok "transcript redacts api_key value";; *) bad "transcript redaction (api_key)";; esac
  case "$flat" in *"ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD"*) bad "transcript redacts long token";; *) ok "transcript redacts long token";; esac
  case "$flat" in *"USER: "*) ok "transcript flattens USER role";; *) bad "transcript USER role";; esac
  # strengthened redaction: JSON, env-var, provider tokens, URL creds, PEM
  red(){ python3 -c 'import sys;sys.path.insert(0,sys.argv[1]);import transcript as t;print(t.redact(sys.argv[2]))' "$LIB" "$1"; }
  case "$(red '{"api_key": "sk-1234567890abcdefABCDEF"}')" in *sk-1234567890*) bad "redact JSON-quoted secret";; *) ok "redact JSON-quoted secret";; esac
  case "$(red 'export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENGbPxRfiCYEX')" in *wJalrXUtnFEMI*) bad "redact env-var secret";; *) ok "redact env-var secret";; esac
  case "$(red 'id AKIAIOSFODNN7EXAMPLE here')" in *AKIAIOSFODNN7EXAMPLE*) bad "redact AWS access key id";; *) ok "redact AWS access key id";; esac
  case "$(red 'postgres://admin:s3cretP4ss@db:5432/x')" in *s3cretP4ss*) bad "redact URL credentials";; *) ok "redact URL credentials";; esac
  case "$(red '-----BEGIN RSA PRIVATE KEY-----
MIIEabcdef
-----END RSA PRIVATE KEY-----')" in *MIIEabcdef*) bad "redact PEM private key";; *) ok "redact PEM private key";; esac

  # lifecycle: a future last_used must read as active, not archived (no abs())
  expect_eq "$(python3 "$LIB/lifecycle.py" state 2026-06-15 2026-12-01 30 90)" "active" "lifecycle clamps future activity to active"
  # memory: a multi-line entry whose continuation starts with the marker stays ONE entry
  python3 "$LIB/memory.py" init "$T/M.md" 2000 "M" 2>/dev/null
  python3 "$LIB/memory.py" add "$T/M.md" 2000 "$(printf 'see policy\n§3 applies')" >/dev/null
  python3 "$LIB/memory.py" add "$T/M.md" 2000 "second entry" >/dev/null
  expect_eq "$(python3 "$LIB/memory.py" remove "$T/M.md" "second"; grep -c '^§' "$T/M.md")" "1" "memory keeps a multi-line entry intact (one § entry remains)"
  # meta: a newline in a value is rejected, not silently corrupting the file
  python3 "$LIB/meta.py" init "$T/n.meta" >/dev/null 2>&1
  python3 "$LIB/meta.py" set "$T/n.meta" quality "$(printf '4\ninjected=evil')" >/dev/null 2>&1
  expect_eq "$?" "2" "meta rejects a newline in a value"
  expect_eq "$(python3 "$LIB/meta.py" get "$T/n.meta" injected)" "" "meta value newline did not inject a key"

  # validate.py: frontmatter contract (name, description <=1024, body)
  mkdir -p "$T/vskill"
  printf -- '---\nname: ok-skill\ndescription: a fine description\n---\nbody here\n' > "$T/vskill/SKILL.md"
  python3 "$LIB/validate.py" skill "$T/vskill" >/dev/null 2>&1; expect_eq "$?" "0" "validate passes a well-formed skill"
  printf -- '---\nname: nodesc\n---\nbody\n' > "$T/vskill/SKILL.md"
  python3 "$LIB/validate.py" skill "$T/vskill" >/dev/null 2>&1; expect_eq "$?" "1" "validate fails a missing description"
  printf -- '---\nname: toolong\ndescription: %s\n---\nbody\n' "$(python3 -c 'print("x"*1100)')" > "$T/vskill/SKILL.md"
  vout="$(python3 "$LIB/validate.py" skill "$T/vskill" 2>/dev/null)"
  case "$vout" in *"description exceeds"*) ok "validate flags a >1024 description";; *) bad "validate description cap (got: $vout)";; esac

  # memory: control/invisible unicode is rejected (exit 4) — injection vector
  python3 "$LIB/memory.py" init "$T/inj.md" 2000 "M" 2>/dev/null
  python3 "$LIB/memory.py" add "$T/inj.md" 2000 "$(printf 'normal\xe2\x80\x8bzero-width')" >/dev/null 2>&1
  expect_eq "$?" "4" "memory rejects invisible/control unicode (exit 4)"
  python3 "$LIB/memory.py" add "$T/inj.md" 2000 "café 日本語 ✅ normal text" >/dev/null 2>&1
  expect_eq "$?" "0" "memory accepts accents / CJK / emoji"

  # redaction: Authorization: Bearer <token> must not leak the token (audit finding)
  case "$(red 'Authorization: Bearer abc123secrettoken')" in *abc123secrettoken*) bad "redact bearer token";; *) ok "redact Authorization Bearer token";; esac
  case "$(red 'google AIzaB1234567890123456789012345678901234 here')" in *AIzaB1234567890123456789012345678901234*) bad "redact google key";; *) ok "redact google AIza key";; esac
  # validate: an empty name/description must NOT bleed into the next line (audit finding)
  printf -- '---\nname:\ndescription: a real description\n---\nbody\n' > "$T/vskill/SKILL.md"
  vb="$(python3 "$LIB/validate.py" skill "$T/vskill" 2>/dev/null)"
  case "$vb" in *"missing 'name'"*) ok "validate rejects empty name (no next-line bleed)";; *) bad "validate empty-name bleed (got: $vb)";; esac

  # suggest.py: surface a matching skill, stay silent on chatter, platform-gate
  local SG="$T/sg"; mkdir -p "$SG/mysql-latency" "$SG/figma-x" "$SG/linonly"
  printf -- '---\nname: mysql-latency\ndescription: triage mysql read latency hikari pool slow query explain p99\n---\nb\n' > "$SG/mysql-latency/SKILL.md"
  printf -- '---\nname: figma-x\ndescription: build figma design tokens components variants\nkeywords: przyciski, glassmorphism\n---\nb\n' > "$SG/figma-x/SKILL.md"
  printf -- '---\nname: linonly\ndescription: tune epoll iouring kernel scheduler knobs\nplatforms: linux\n---\nb\n' > "$SG/linonly/SKILL.md"
  case "$(printf 'mysql slow query p99 latency' | CAIRN_SUGGEST_THRESHOLD=1 python3 "$LIB/suggest.py" "$SG" 3 macos | head -1)" in mysql-latency*) ok "suggest surfaces the relevant skill";; *) bad "suggest relevant match";; esac
  sgc="$(printf 'thanks looks good ok' | python3 "$LIB/suggest.py" "$SG" 3 macos)"; [ -z "$sgc" ] && ok "suggest is silent on acknowledgement chatter" || bad "suggest chatter (got: $sgc)"
  # keyword-only match: 'przyciski' is in figma-x keywords, NOT its description
  case "$(printf 'zaprojektuj przyciski' | CAIRN_SUGGEST_THRESHOLD=1 python3 "$LIB/suggest.py" "$SG" 3 macos | head -1)" in figma-x*) ok "suggest matches a keyword-only (bilingual) trigger";; *) bad "suggest keyword match";; esac
  # diacritic folding: 'przyciskÓW' still matches the 'przyciski' keyword
  case "$(printf 'PRZYCISKÓW layout' | CAIRN_SUGGEST_THRESHOLD=1 python3 "$LIB/suggest.py" "$SG" 3 macos | head -1)" in figma-x*) ok "suggest folds diacritics + prefix-matches inflection";; *) bad "suggest folding/prefix";; esac
  case "$(printf 'tune epoll kernel scheduler' | CAIRN_SUGGEST_THRESHOLD=1 python3 "$LIB/suggest.py" "$SG" 3 linux | head -1)" in linonly*) ok "suggest fires a linux skill on linux";; *) bad "suggest linux match";; esac
  sgm="$(printf 'tune epoll kernel scheduler' | CAIRN_SUGGEST_THRESHOLD=1 python3 "$LIB/suggest.py" "$SG" 3 macos)"; [ -z "$sgm" ] && ok "suggest platform-gates a linux-only skill on macos" || bad "suggest platform gating (got: $sgm)"
  rm -rf "$T"
}

# =============================================================================
tier_integration() {
  hdr "integration — install / migrate / review / curate (throwaway HOME)"
  local WORK; WORK="$(mktemp -d)"
  local OLD_HOME="$HOME" OLD_PATH="$PATH"
  export HOME="$WORK/home"; mkdir -p "$HOME"
  unset CLAUDE_DIR 2>/dev/null || true
  # shims: claude (generic), crontab (no-op), pmset (AC power)
  local SHIM="$WORK/shim"; mkdir -p "$SHIM"
  cat > "$SHIM/claude" <<'EOF'
#!/usr/bin/env bash
echo "claude $* guard=${CAIRN_REVIEW_HOOK:-0}" >> "$HOME/.claude-calls"
cat >/dev/null; echo "review: no changes"
EOF
  printf '#!/usr/bin/env bash\ncat >/dev/null 2>&1 || true; echo "crontab $*" >> "$HOME/.crontab-calls"\n' > "$SHIM/crontab"
  printf '#!/usr/bin/env bash\necho "Now drawing from '\''AC Power'\''"\n' > "$SHIM/pmset"
  printf '#!/usr/bin/env bash\necho "launchctl $*" >> "$HOME/.launchctl-calls"\n' > "$SHIM/launchctl"
  chmod +x "$SHIM"/*
  export PATH="$SHIM:$PATH"
  local CD="$HOME/.claude" C="$HOME/.claude/cairn/bin/cairn"

  # --- install ---
  "$CAIRN" install >/dev/null 2>&1; check $? "install exits 0"
  expect_file "$CD/CLAUDE.md" "CLAUDE.md created"
  expect_grep "$CD/CLAUDE.md" "BEGIN cairn" "managed block installed"
  expect_file "$CD/commands/learn.md" "slash command installed"
  expect_file "$CD/skills/skill-extraction/.meta" "meta-skill .meta stamped"
  expect_eq "$(python3 "$LIB/meta.py" get "$CD/skills/skill-extraction/.meta" provenance)" "bundled" "meta-skill is bundled/protected"
  expect_file "$CD/memories/USER.md" "memory USER.md initialised"
  expect_grep "$CD/CLAUDE.md" "@memories/USER.md" "managed block @-imports memory (auto-load at session start)"
  "$C" lint >/dev/null 2>&1; check $? "cairn lint passes on a fresh install"
  expect_file "$C" "dispatcher self-installed to ~/.claude/cairn"
  ( cd "$CD/skills" && git rev-parse --git-dir >/dev/null 2>&1 ); check $? "skills/ is a git repo"

  # --- embedded == asset (G12 cmp) ---
  local diffs=0 f
  for f in "$ASSETS"/commands/*.md; do cmp -s "$f" "$CD/commands/$(basename "$f")" || diffs=$((diffs+1)); done
  cmp -s "$ASSETS/templates/skill-template/SKILL.md" "$CD/templates/skill-template/SKILL.md" || diffs=$((diffs+1))
  expect_eq "$diffs" "0" "installed commands+template byte-identical to repo assets"

  # --- idempotency: re-run changes no file content ---
  # POSIX cksum (universal); strip the $CD prefix so paths compare stably
  local before after
  before="$(find "$CD" -type f -not -path '*/.git/*' -not -name '*.bak-*' -not -path '*/logs/*' -exec cksum {} \; 2>/dev/null | sed "s#$CD##" | sort | cksum)"
  "$CAIRN" install >/dev/null 2>&1
  after="$(find "$CD" -type f -not -path '*/.git/*' -not -name '*.bak-*' -not -path '*/logs/*' -exec cksum {} \; 2>/dev/null | sed "s#$CD##" | sort | cksum)"
  expect_eq "$after" "$before" "install is idempotent (no file content changes on re-run)"

  # --- migrate over a v1 block preserves user content ---
  rm -rf "$WORK/home2"; export HOME="$WORK/home2"; mkdir -p "$HOME/.claude/skills"
  CD="$HOME/.claude"; C="$HOME/.claude/cairn/bin/cairn"
  cat > "$CD/CLAUDE.md" <<'EOF'
# my notes
KEEP-TOP
<!-- BEGIN skill-system (managed by claude-skill-system installer) -->
old v1 block REMOVE-ME
<!-- END skill-system -->
KEEP-BOTTOM
EOF
  "$CAIRN" migrate --no-assess >/dev/null 2>&1; check $? "migrate exits 0"
  expect_grep "$CD/CLAUDE.md" "KEEP-TOP" "migrate preserves user content above block"
  expect_grep "$CD/CLAUDE.md" "KEEP-BOTTOM" "migrate preserves user content below block"
  expect_nogrep "$CD/CLAUDE.md" "REMOVE-ME" "migrate removes the old v1 block"
  expect_grep "$CD/CLAUDE.md" "BEGIN cairn" "migrate installs the cairn block"

  # --- review: dry-run (no claude) + real (shim, recursion guard) ---
  mkdir -p "$CD/projects/p" "$HOME/wd"
  local TR="$CD/projects/p/s.jsonl"
  printf '{"type":"user","cwd":"%s","message":{"content":[{"type":"text","text":"we fixed it by indexing"}]}}\n' "$HOME/wd" > "$TR"
  printf '{"type":"assistant","message":{"content":[{"type":"text","text":"done"}]}}\n' >> "$TR"
  "$C" review --dry-run "$TR" >/dev/null 2>&1; check $? "review --dry-run exits 0 (no model call)"
  : > "$HOME/.claude-calls"
  "$C" review "$TR" >/dev/null 2>&1; check $? "review (shim) exits 0"
  expect_grep "$HOME/.claude-calls" "guard=1" "review runs claude with recursion guard set"
  CAIRN_REVIEW_HOOK=1 "$C" review "$TR" >/dev/null 2>&1
  expect_eq "$?" "0" "review no-ops when CAIRN_REVIEW_HOOK already set (recursion guard)"

  # review telemetry: a skill the review touches gets use_count bumped + last_used set
  mkdir -p "$CD/skills/tele"; printf -- '---\nname: tele\ndescription: d\n---\nb\n' > "$CD/skills/tele/SKILL.md"
  python3 "$LIB/meta.py" init "$CD/skills/tele/.meta" created=2026-01-01 last_used=2026-01-01
  cat > "$SHIM/claude" <<EOF
#!/usr/bin/env bash
cat >/dev/null; printf 'note\n' >> "$CD/skills/tele/learnings.md"; echo done
EOF
  chmod +x "$SHIM/claude"
  "$C" review "$TR" >/dev/null 2>&1
  expect_eq "$(python3 "$LIB/meta.py" get "$CD/skills/tele/.meta" use_count)" "1" "review bumps use_count for a touched skill"
  expect_eq "$(python3 "$LIB/meta.py" get "$CD/skills/tele/.meta" last_used)" "$(date +%Y-%m-%d)" "review sets last_used on a touched skill"

  # --- curate: read-only then --apply-lifecycle with protections ---
  local S="$CD/skills"
  mkfix(){ mkdir -p "$S/$1"; printf -- '---\nname: %s\ndescription: %s\n---\n' "$1" "$2" > "$S/$1/SKILL.md"; python3 "$LIB/meta.py" init "$S/$1/.meta" created="$3" last_used="$3"; }
  mkfix aged "old unused thing nobody touches" 2026-01-01
  mkfix pinold "pinned old thing" 2026-01-01; python3 "$LIB/meta.py" set "$S/pinold/.meta" pinned true
  mkfix lowq1 "marginal one-off thing" 2026-06-10; python3 "$LIB/meta.py" set "$S/lowq1/.meta" quality 1
  "$C" curate >/dev/null 2>&1; check $? "curate (read-only) exits 0"
  expect_file "$S/aged/SKILL.md" "curate read-only does not move skills"
  expect_grep "$CD/cairn/harvest/CURATE.md" "Low-quality" "curate report surfaces quality 1-2 skills"
  expect_grep "$CD/cairn/harvest/CURATE.md" "lowq1" "curate report names the low-quality skill"
  "$C" curate --apply-lifecycle >/dev/null 2>&1
  expect_nofile "$S/aged" "curate --apply-lifecycle archives the aged skill"
  expect_file "$S/pinold/SKILL.md" "curate --apply-lifecycle never touches pinned skills"
  ls "$CD/cairn/skill-archive/" 2>/dev/null | grep -q '^aged-' && ok "archived skill recoverable under cairn/skill-archive" || bad "archived copy present"

  # curate --merge: auto-consolidate an overlapping cluster into one umbrella
  mkfix mfa "alpha beta gamma overlap shared widget tokens handling" 2026-06-10
  mkfix mfb "alpha beta gamma overlap shared gadget tokens handling" 2026-06-10
  mkfix mfpin "alpha beta gamma overlap shared tokens" 2026-06-10; python3 "$LIB/meta.py" set "$S/mfpin/.meta" pinned true
  cat > "$SHIM/claude" <<'MEOF'
#!/usr/bin/env bash
cat >/dev/null
printf -- '---\nname: merged-umbrella\ndescription: Unified alpha/beta/gamma handling. Use when alpha, beta, or gamma overlap.\n---\n# Merged\n## Procedure\n1. do the thing\n'
MEOF
  chmod +x "$SHIM/claude"
  "$C" curate --merge --yes --threshold 0.30 >/dev/null 2>&1
  expect_file "$S/merged-umbrella/SKILL.md" "curate --merge creates one umbrella"
  expect_nofile "$S/mfa" "curate --merge archives a merged original"
  expect_file "$S/mfpin/SKILL.md" "curate --merge never merges a pinned skill"
  ls "$CD/cairn/skill-archive/" 2>/dev/null | grep -q '^mfa-' && ok "merged original recoverable in archive" || bad "merged original archived"
  # curate --archive-weak: archive a quality-1 skill, keep pinned
  mkfix weakling "marginal one-off" 2026-06-10; python3 "$LIB/meta.py" set "$S/weakling/.meta" quality 1
  "$C" curate --archive-weak >/dev/null 2>&1   # preview must NOT remove it
  expect_file "$S/weakling/SKILL.md" "curate --archive-weak preview leaves skills in place"
  "$C" curate --archive-weak --yes >/dev/null 2>&1
  expect_nofile "$S/weakling" "curate --archive-weak --yes archives a quality-1 skill"
  expect_file "$S/pinold/SKILL.md" "curate --archive-weak never touches pinned skills"

  # merge SAFETY: malformed model output must NOT corrupt or delete any skill
  mkfix mrx "delta epsilon zeta overlap shared widget one" 2026-06-10
  mkfix mry "delta epsilon zeta overlap shared widget two" 2026-06-10
  printf '#!/usr/bin/env bash\ncat>/dev/null; printf "not valid frontmatter at all\\n"\n' > "$SHIM/claude"; chmod +x "$SHIM/claude"
  "$C" curate --merge --yes --threshold 0.30 >/dev/null 2>&1
  expect_file "$S/mrx/SKILL.md" "merge: members survive malformed model output (no corruption)"
  expect_file "$S/mry/SKILL.md" "merge: second member survives malformed output"
  # merge SAFETY: a model-chosen name with path traversal must not escape skills/
  printf '#!/usr/bin/env bash\ncat>/dev/null; printf -- "---\\nname: ../../evil-escape\\ndescription: x triggers things\\n---\\nbody\\n"\n' > "$SHIM/claude"; chmod +x "$SHIM/claude"
  "$C" curate --merge --yes --threshold 0.30 >/dev/null 2>&1
  expect_nofile "$CD/evil-escape" "merge: rejects path-traversal target (no escape from skills/)"
  expect_nofile "$HOME/evil-escape" "merge: traversal target did not escape two levels"
  # --archive-weak --assess must not crash on unbound \$TMPD (audit blocker)
  mkfix assessme "marginal unscored thing" 2026-06-10
  printf '#!/usr/bin/env bash\ncat>/dev/null; echo 1\n' > "$SHIM/claude"; chmod +x "$SHIM/claude"
  "$C" curate --archive-weak --assess --yes >/dev/null 2>&1; check $? "curate --archive-weak --assess runs without \$TMPD crash"
  printf '#!/usr/bin/env bash\ncat>/dev/null;echo ok\n' > "$SHIM/claude"; chmod +x "$SHIM/claude"  # restore generic shim

  # schedule: wire + remove the nightly maintenance job (launchctl/crontab shimmed)
  "$C" schedule 03:30 >/dev/null 2>&1; check $? "schedule sets a nightly job"
  case "$("$C" schedule --status)" in *"on ("*) ok "schedule --status reports on";; *) bad "schedule status on";; esac
  "$C" schedule --off >/dev/null 2>&1
  case "$("$C" schedule --status)" in *off*) ok "schedule --off removes the job";; *) bad "schedule off";; esac
  # maintain: improve + inactivity-archive, exits 0, lock cleaned (no unbound-var error)
  out_m="$("$C" maintain 2>&1)"; check $? "maintain runs (improve + curate) and exits 0"
  case "$out_m" in *"unbound variable"*) bad "maintain lock cleanup (unbound variable)";; *) ok "maintain cleans its lock with no error";; esac
  expect_file "$CD/cairn/logs/maintain.log" "maintain writes its log"

  # --- hooks: enable -> valid JSON + guard; uninstall removes ---
  export HOME="$WORK/home3"; mkdir -p "$HOME"; CD="$HOME/.claude"; C="$HOME/.claude/cairn/bin/cairn"
  "$CAIRN" install --enable-hooks >/dev/null 2>&1
  python3 -c "import json;json.load(open('$CD/settings.json'))" 2>/dev/null; check $? "enable-hooks writes valid settings.json"
  expect_grep "$CD/settings.json" 'CAIRN_REVIEW_HOOK' "SessionEnd hook carries the recursion guard"
  expect_grep "$CD/settings.json" 'UserPromptSubmit' "UserPromptSubmit suggest hook installed"
  expect_grep "$CD/settings.json" 'suggest --hook' "suggest hook wired to cairn suggest"
  # cairn must NOT touch skillListingBudgetFraction (0 is an undocumented value CC rejects)
  expect_nogrep "$CD/settings.json" 'skillListingBudgetFraction' "enable-hooks leaves skillListingBudgetFraction untouched"
  # suggest --hook surfaces a matching skill and stays silent on chatter
  mkdir -p "$CD/skills/redis-timeout-x"; printf -- '---\nname: redis-timeout-x\ndescription: diagnose redis command timeout lettuce pool exhaustion\n---\nb\n' > "$CD/skills/redis-timeout-x/SKILL.md"
  printf '{"prompt":"redis command timeout lettuce pool"}' | CAIRN_SUGGEST_THRESHOLD=1 "$C" suggest --hook 2>/dev/null | grep -q 'redis-timeout-x' && ok "suggest --hook surfaces a matching skill" || bad "suggest --hook match"
  printf '{"prompt":"thanks looks good"}' | "$C" suggest --hook 2>/dev/null | grep -q . && bad "suggest --hook should be silent on chatter" || ok "suggest --hook silent on chatter"
  # names-only safety net: no strong match but a topically-warm prompt -> roster of
  # skill names (near-misses first) so a token-overlap false negative stays visible.
  mkdir -p "$CD/skills/mongo-slow-x"; printf -- '---\nname: mongo-slow-x\ndescription: mongodb compound index slow query audit\n---\nb\n' > "$CD/skills/mongo-slow-x/SKILL.md"
  mkdir -p "$CD/skills/lombok-unrelated-x"; printf -- '---\nname: lombok-unrelated-x\ndescription: java lombok annotation builder immutable value object\n---\nb\n' > "$CD/skills/lombok-unrelated-x/SKILL.md"
  roster_out="$(printf '{"prompt":"my redis feels slow"}' | CAIRN_SUGGEST_THRESHOLD=99 CAIRN_ROSTER_FLOOR=0.1 "$C" suggest --hook 2>/dev/null)"
  case "$roster_out" in *"no installed skill matched"*redis-timeout-x*) ok "suggest --hook roster surfaces names when nothing scores strongly";; *) bad "roster fire (got: $roster_out)";; esac
  case "$roster_out" in *@@ROSTER@@*) bad "roster leaks the raw @@ROSTER@@ sentinel into the note";; *) ok "roster renders as prose, not the raw sentinel";; esac
  # near-misses only: a zero-overlap skill must NOT be dumped into the roster
  case "$roster_out" in *lombok-unrelated-x*) bad "roster listed a zero-overlap skill (should be near-misses only)";; *) ok "roster excludes zero-overlap skills (near-misses only)";; esac
  printf '{"prompt":"my redis feels slow"}' | CAIRN_SUGGEST_THRESHOLD=99 CAIRN_ROSTER_FLOOR=0.1 CAIRN_SUGGEST_ROSTER=0 "$C" suggest --hook 2>/dev/null | grep -q . && bad "CAIRN_SUGGEST_ROSTER=0 should suppress the roster" || ok "CAIRN_SUGGEST_ROSTER=0 suppresses the roster"
  printf '{"prompt":"thanks looks good"}' | CAIRN_SUGGEST_THRESHOLD=99 CAIRN_ROSTER_FLOOR=0.1 "$C" suggest --hook 2>/dev/null | grep -q . && bad "roster should stay silent on chatter (cold band)" || ok "roster silent on chatter (best score below floor)"
  # opt-in mid-task re-surface: --tick counts per session, fires every Nth call
  mkdir -p "$CD/projects/q"; printf '{"type":"user","cwd":"x","message":{"content":[{"type":"text","text":"redis command timeout lettuce pool"}]}}\n' > "$CD/projects/q/s.jsonl"
  tj='{"session_id":"sessX","transcript_path":"'"$CD/projects/q/s.jsonl"'"}'
  to1="$(printf '%s' "$tj" | CAIRN_SUGGEST_TICK=2 CAIRN_SUGGEST_THRESHOLD=1 "$C" suggest --tick 2>/dev/null)"
  to2="$(printf '%s' "$tj" | CAIRN_SUGGEST_TICK=2 CAIRN_SUGGEST_THRESHOLD=1 "$C" suggest --tick 2>/dev/null)"
  [ -z "$to1" ] && ok "suggest --tick stays silent between intervals" || bad "tick interval (call 1 fired: $to1)"
  case "$to2" in *additionalContext*redis-timeout-x*) ok "suggest --tick re-surfaces on the Nth tool call";; *) bad "tick fire (got: $to2)";; esac
  # PostToolUse track: a real Skill-tool invocation bumps use_count + last_used
  expect_grep "$CD/settings.json" 'track --hook' "PostToolUse track hook installed (matcher Skill)"
  mkdir -p "$CD/skills/track-me"; printf -- '---\nname: track-me\ndescription: d\n---\nb\n' > "$CD/skills/track-me/SKILL.md"
  python3 "$LIB/meta.py" init "$CD/skills/track-me/.meta" created=2026-01-01 last_used=2026-01-01
  printf '{"tool_name":"Skill","tool_input":{"skill":"track-me"}}' | "$C" track --hook
  expect_eq "$(python3 "$LIB/meta.py" get "$CD/skills/track-me/.meta" use_count)" "1" "track bumps use_count on a Skill invocation"
  printf '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | "$C" track --hook
  expect_eq "$(python3 "$LIB/meta.py" get "$CD/skills/track-me/.meta" use_count)" "1" "track ignores non-Skill tool calls"
  "$C" uninstall >/dev/null 2>&1
  expect_nogrep "$CD/CLAUDE.md" "BEGIN cairn" "uninstall removes the managed block"
  # uninstall removes BOTH hooks; if that left an empty {} it deletes the file too.
  if [ ! -f "$CD/settings.json" ]; then ok "uninstall removes cairn hooks (empty settings.json dropped)"
  else
    python3 -c "import json,sys;d=json.load(open('$CD/settings.json'));sys.exit(0 if 'hooks' not in d else 1)" 2>/dev/null; check $? "uninstall removes the SessionEnd hook"
    expect_nogrep "$CD/settings.json" 'suggest' "uninstall removes the UserPromptSubmit suggest hook"
    expect_nogrep "$CD/settings.json" 'track' "uninstall removes the PostToolUse track hook"
  fi

  # backfill resilience / run_claude 3-way contract: deterministic fail (rc2) is
  # quarantined and the run continues; persistent transient (rc1) HALTs resumably.
  export HOME="$WORK/bf"; mkdir -p "$HOME"; CD="$HOME/.claude"; C="$HOME/.claude/cairn/bin/cairn"
  "$CAIRN" install >/dev/null 2>&1
  local MINED="$CD/cairn/harvest/.mined"
  mkdir -p "$CD/projects/p" "$HOME/wd"
  printf '{"type":"user","cwd":"%s","message":{"content":[{"type":"text","text":"FAILME deterministic"}]}}\n' "$HOME/wd" > "$CD/projects/p/bad.jsonl"
  printf '{"type":"user","cwd":"%s","message":{"content":[{"type":"text","text":"a normal mineable session"}]}}\n' "$HOME/wd" > "$CD/projects/p/good.jsonl"
  cat > "$SHIM/claude" <<'EOF'
#!/usr/bin/env bash
in="$(cat)"; case "$in" in *FAILME*) echo "deterministic boom" >&2; exit 2;; esac
echo '{"name":"mined-x","description":"a triggers b"}'
EOF
  chmod +x "$SHIM/claude"
  ( cd "$HOME/wd" && "$C" mine --all --max-sessions 10 --max-retries 0 >/dev/null 2>&1 )
  ls "$MINED"/*.failed >/dev/null 2>&1 && ok "backfill quarantines a deterministic failure (rc2 -> .failed)" || bad "backfill quarantine stamp"
  ls "$MINED"/*.done >/dev/null 2>&1 && ok "backfill continues past a failed session (good one mined)" || bad "backfill continues past failure"
  # persistent transient -> HALT, resumable (no .done for it), nonzero exit
  rm -rf "$MINED"/* "$CD/projects/p/"*.jsonl
  printf '{"type":"user","cwd":"%s","message":{"content":[{"type":"text","text":"transient please"}]}}\n' "$HOME/wd" > "$CD/projects/p/t.jsonl"
  printf '#!/usr/bin/env bash\ncat>/dev/null; echo "rate limit exceeded" >&2; exit 1\n' > "$SHIM/claude"; chmod +x "$SHIM/claude"
  ( cd "$HOME/wd" && "$C" mine --all --max-sessions 10 --max-retries 0 >/dev/null 2>&1 ); local rcb=$?
  expect_eq "$rcb" "1" "backfill HALTs (exit 1) on persistent transient error"
  ls "$MINED"/*.done >/dev/null 2>&1 && bad "backfill must NOT mark a halted session done" || ok "backfill leaves the halted session un-stamped (resumable)"

  export HOME="$OLD_HOME"; export PATH="$OLD_PATH"
  rm -rf "$WORK"
}

# =============================================================================
TIER="${1:-all}"
echo "${B}Cairn test suite${Z}  (repo: $REPO)"
case "$TIER" in
  static)      tier_static ;;
  unit)        tier_unit ;;
  integration) tier_integration ;;
  all)         tier_static; tier_unit; tier_integration ;;
  *) echo "usage: run-tests.sh [static|unit|integration]"; exit 2 ;;
esac

printf '\n%s========================================%s\n' "$B" "$Z"
if [ "$FAIL" -eq 0 ]; then
  printf '%sALL GREEN%s — %d passed\n' "$G" "$Z" "$PASS"; exit 0
else
  printf '%s%d passed, %d FAILED%s%b\n' "$R" "$PASS" "$FAIL" "$Z" "$FAILED_NAMES"; exit 1
fi
