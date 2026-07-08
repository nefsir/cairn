#!/usr/bin/env bash
# =============================================================================
# cairn — a self-improving skill & memory system for Claude Code.
#
# One dispatcher. Everything it manages is a plain file in git: skills, their
# .meta, bounded memory, the managed CLAUDE.md block. Nothing hides in a
# database. See `cairn --help` for the subcommand map.
#
#   Layer A (backfill, one-time):  mine | distill | refine
#   Layer B (the ongoing loop):    review | curate | improve
#   Store & memory:                memory | pin | unpin | provenance | status
#   Lifecycle:                     install | migrate | uninstall | test
#
# Conventions: bash-3.2 compatible (macOS default bash), idempotent, never
# deletes (archives only), all skill writes git-tracked. python3 powers the
# data steps; `claude -p` powers the model steps (the only thing that leaves
# the machine).
# =============================================================================

# --- shell guard: re-exec under bash when started from zsh/sh/dash -----------
if [ -z "${BASH_VERSION:-}" ] && [ -f "$0" ]; then exec bash "$0" "$@"; fi
set -uo pipefail   # NOT -e: subcommands manage their own error flow

CAIRN_VERSION="2.0.0-dev"

# --- self-location: find CAIRN_HOME so we can reach lib/ and assets/ ---------
# Portable symlink resolution (no readlink -f on macOS).
_cairn_resolve_self() {
  local src="${BASH_SOURCE[0]:-$0}" dir
  while [ -h "$src" ]; do
    dir="$(cd -P "$(dirname "$src")" && pwd)"
    src="$(readlink "$src")"
    case "$src" in /*) ;; *) src="$dir/$src" ;; esac
  done
  cd -P "$(dirname "$src")" && pwd
}
SELF_DIR="$(_cairn_resolve_self)"                 # .../bin
CAIRN_HOME="$(cd "$SELF_DIR/.." && pwd)"          # repo root or ~/.claude/cairn
LIB="$CAIRN_HOME/lib"
ASSETS="$CAIRN_HOME/assets"
LOGO="$CAIRN_HOME/cairn-logo.txt"

# --- paths it operates on ----------------------------------------------------
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SKILLS="$CLAUDE_DIR/skills"
MEMORIES="$CLAUDE_DIR/memories"
COMMANDS="$CLAUDE_DIR/commands"
TEMPLATES="$CLAUDE_DIR/templates"
STATE="$CLAUDE_DIR/cairn"                          # cairn's own working state
HARVEST="$STATE/harvest"                           # mine/distill/refine output
ARCHIVE="$STATE/skill-archive"                     # lifecycle archive (never delete)
LOGS="$STATE/logs"
USER_MD="$MEMORIES/USER.md"
MEMORY_MD="$MEMORIES/MEMORY.md"

# --- bounded-memory char caps (tunable via env) ------------------------------
USER_CAP="${CAIRN_USER_CAP:-1375}"
MEMORY_CAP="${CAIRN_MEMORY_CAP:-2200}"

# --- defaults for model/data steps ------------------------------------------
MODEL_DEFAULT="${CAIRN_MODEL:-sonnet}"

# --- managed CLAUDE.md block markers (must match assets/claude-block.md) -----
BEGIN_MARK='<!-- BEGIN cairn (managed by cairn) -->'
END_MARK='<!-- END cairn -->'

# --- transient-error pattern shared by every resilient claude -p caller ------
TRANSIENT_RE='rate.?limit|quota|overloaded|too many requests|429|503|529|timeout|timed out|temporarily|try again|connection|network|ECONNRESET|ETIMEDOUT'

# =============================================================================
# Output helpers
# =============================================================================
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_DIM=$'\033[2m'; C_B=$'\033[1m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_0=$'\033[0m'
else
  C_DIM=""; C_B=""; C_G=""; C_Y=""; C_R=""; C_0=""
fi
ok()   { printf '  %s\342\234\223%s %s\n' "$C_G" "$C_0" "$1"; }      # ✓
warn() { printf '  %s!%s %s\n'  "$C_Y" "$C_0" "$1"; }
info() { printf '  %s\n' "$1"; }
die()  { printf '%sERROR:%s %s\n' "$C_R" "$C_0" "$1" >&2; exit 1; }
hdr()  { printf '%s== %s ==%s\n' "$C_B" "$1" "$C_0"; }
today(){ date +%Y-%m-%d; }
ts()   { date +%Y%m%d-%H%M%S; }
say()  { # say <logfile> <msg> : timestamped line to stdout + log
  local lf="$1"; shift
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$lf" || true
}

# =============================================================================
# Dependency checks
# =============================================================================
need_python() { command -v python3 >/dev/null 2>&1 || die "python3 required for this command"; }
need_claude() { command -v claude  >/dev/null 2>&1 || die "claude not on PATH (install Claude Code first)"; }
has_git()     { command -v git >/dev/null 2>&1; }

# py <helper> <args...> : run a lib/ python helper
py() { local h="$1"; shift; python3 "$LIB/$h.py" "$@"; }

# =============================================================================
# Idempotent file install (skip-if-identical / backup-if-changed / create)
#   put <src> <dest> <label>
# DRY=1 makes put/mkd/snapshot describe instead of act (cairn migrate --dry-run).
# =============================================================================
DRY=0
CAIRN_TS=""
mkd() { [ "$DRY" -eq 1 ] && return 0; mkdir -p "$@"; }
put() {
  local src="$1" dest="$2" label="$3"
  [ -n "$CAIRN_TS" ] || CAIRN_TS="$(ts)"
  if [ "$DRY" -eq 1 ]; then
    if [ -f "$dest" ] && cmp -s "$src" "$dest"; then info "would skip $label (unchanged)"
    elif [ -f "$dest" ]; then info "would update $label (backing up existing)"
    else info "would create $label"; fi
    return 0
  fi
  mkdir -p "$(dirname "$dest")"
  if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
    ok "$label (unchanged)"
  elif [ -f "$dest" ]; then
    cp "$dest" "$dest.bak-$CAIRN_TS"; cp "$src" "$dest"
    ok "$label (updated; backup: $(basename "$dest").bak-$CAIRN_TS)"
  else
    cp "$src" "$dest"; ok "$label (created)"
  fi
}

# =============================================================================
# git helpers for the skills repo (git = undo/rollback)
# =============================================================================
skills_git() { git -C "$SKILLS" "$@"; }
skills_is_repo() { has_git && skills_git rev-parse --git-dir >/dev/null 2>&1; }
skills_commit() { # skills_commit <message> : commit all of skills/ (best-effort)
  [ "$DRY" -eq 1 ] && { info "would commit skills/: $1"; return 0; }
  skills_is_repo || return 0
  skills_git add -A >/dev/null 2>&1 || true
  skills_git diff --cached --quiet 2>/dev/null && return 0   # nothing staged
  if [ -n "$(skills_git config user.email 2>/dev/null || true)" ]; then
    skills_git commit -q -m "$1" >/dev/null 2>&1 || true
  else
    skills_git -c user.name="cairn" -c user.email="cairn@localhost" \
      commit -q -m "$1" >/dev/null 2>&1 || true
  fi
}

# =============================================================================
# resilient claude -p runner (shared by mine/distill/refine/review/improve)
#   run_claude <prompt> <model> <infile-or-empty> <outfile> <errfile> <maxretry> <label> <logfile>
#   returns: 0 success | 1 transient-halt (resume later) | 2 deterministic fail
# =============================================================================
run_claude() {
  local prompt="$1" model="$2" infile="$3" outf="$4" errf="$5" maxretry="$6" label="$7" lf="$8"
  local attempt=0 rc=0 transient=0 wait
  while :; do
    attempt=$((attempt + 1))
    if [ -n "$infile" ]; then
      claude -p "$prompt" --model "$model" --max-turns 2 < "$infile" > "$outf" 2>"$errf"
    else
      claude -p "$prompt" --model "$model" --max-turns 2 > "$outf" 2>"$errf"
    fi
    rc=$?
    [ "$rc" -eq 0 ] && return 0
    if grep -qiE "$TRANSIENT_RE" "$errf"; then
      transient=1
      if [ "$attempt" -le "$maxretry" ]; then
        wait=$((attempt * attempt * 5))
        say "$lf" "  transient (attempt $attempt/$maxretry) on $label; retry in ${wait}s"
        sleep "$wait"; continue
      fi
    fi
    break
  done
  cat "$errf" >> "$lf" 2>/dev/null || true
  [ "$transient" -eq 1 ] && return 1
  return 2
}

# =============================================================================
# skill resolution
# =============================================================================
resolve_skill_dir() { # resolve_skill_dir <name> -> prints dir or empty
  local name="$1"
  if [ -d "$SKILLS/$name" ]; then printf '%s\n' "$SKILLS/$name"; return 0; fi
  if [ -d "$PWD/.claude/skills/$name" ]; then printf '%s\n' "$PWD/.claude/skills/$name"; return 0; fi
  return 1
}

# =============================================================================
# banner / version / help
# =============================================================================
banner() {
  if [ -f "$LOGO" ]; then cat "$LOGO"; else printf '\n  cairn — self-improving skills & memory for Claude Code\n'; fi
  printf '\n  %sv%s%s · %s\n\n' "$C_DIM" "$CAIRN_VERSION" "$C_0" "run 'cairn --help' for the subcommand map"
}

show_help() {
  cat <<EOF
${C_B}cairn${C_0} — self-improving skills & memory for Claude Code  (v$CAIRN_VERSION)

${C_B}Backfill (Layer A, one-time)${C_0}
  cairn mine [ROOT] [opts]     mine past transcripts into skill candidates
  cairn distill [opts]         cluster candidates -> synthesized proposals
  cairn refine [opts]          generalize + reusability-score the proposals

${C_B}The loop (Layer B, ongoing)${C_0}
  cairn review [TRANSCRIPT]    post-session review: patch/create skills + memory
  cairn curate                 consolidation + lifecycle report (read-only)
  cairn curate --merge [--yes]        auto-merge overlapping skills into umbrellas
  cairn curate --archive-weak [--assess] [--yes]   archive low-quality/low-use skills
  cairn curate --apply-lifecycle      apply stale/archive transitions
  cairn improve                improvement pass (eval -> fix -> re-eval)
  cairn maintain               run the nightly job now (improve + inactivity-archive)
  cairn schedule [HH:MM]       run maintain nightly (launchd/cron); --off to remove

${C_B}Store & memory${C_0}
  cairn status                 health dashboard
  cairn lint [name]            validate skill frontmatter (name, description ≤1024)
  cairn suggest "<text>"       show the skills matching a prompt (the use-side hook)
  cairn memory [user|agent ...] read / add / replace / remove / trim memory
  cairn pin <name>             freeze a skill from auto-curation
  cairn unpin <name>
  cairn provenance --list      show provenance / pinned / state / quality
  cairn provenance <name> <managed|bundled>

${C_B}Lifecycle${C_0}
  cairn install [--enable-hooks]   fresh install (or migrate if a setup exists)
  cairn migrate [--dry-run] [--no-assess]
  cairn uninstall
  cairn test                   run the test suite (static + unit + integration)
  cairn --version | --help

Everything lives under ${C_DIM}$CLAUDE_DIR${C_0} as plain files in git.
EOF
}

# =============================================================================
# subcommand: memory
# =============================================================================
cmd_memory() {
  need_python
  mkdir -p "$MEMORIES"
  py memory init "$USER_MD"   "$USER_CAP"   "USER model (cairn)"  >/dev/null 2>&1 || true
  py memory init "$MEMORY_MD" "$MEMORY_CAP" "Agent notes (cairn)" >/dev/null 2>&1 || true

  local which="${1:-}"
  if [ -z "$which" ]; then
    hdr "USER.md  ($(py memory chars "$USER_MD")/$USER_CAP chars)"
    py memory read "$USER_MD"
    printf '\n'
    hdr "MEMORY.md  ($(py memory chars "$MEMORY_MD")/$MEMORY_CAP chars)"
    py memory read "$MEMORY_MD"
    return 0
  fi

  local file cap label
  case "$which" in
    user)         file="$USER_MD";   cap="$USER_CAP";   label="USER.md" ;;
    agent|memory) file="$MEMORY_MD"; cap="$MEMORY_CAP"; label="MEMORY.md" ;;
    *) die "memory: first arg must be 'user' or 'agent' (got '$which')" ;;
  esac
  shift
  local action="${1:-read}"; shift 2>/dev/null || true
  case "$action" in
    read)    py memory read "$file" ;;
    add)     [ $# -ge 1 ] || die "memory $which add \"<text>\""
             if py memory add "$file" "$cap" "$*"; then ok "$label: added (now $(py memory chars "$file")/$cap)"; else die "memory add rejected (see reason above) — over cap $cap, or unsafe characters"; fi ;;
    replace) [ $# -ge 2 ] || die "memory $which replace \"<substr>\" \"<text>\""
             local sub="$1"; shift; py memory replace "$file" "$cap" "$sub" "$*" && ok "$label: replaced" || die "replace failed" ;;
    remove)  [ $# -ge 1 ] || die "memory $which remove \"<substr>\""
             py memory remove "$file" "$1" && ok "$label: removed" || die "remove failed" ;;
    trim)    local n; n="$(py memory trim "$file" "$cap")"; ok "$label: trimmed $n oldest entry(ies) (now $(py memory chars "$file")/$cap)" ;;
    *) die "memory: unknown action '$action' (read|add|replace|remove|trim)" ;;
  esac
}

# =============================================================================
# subcommand: pin / unpin
# =============================================================================
_set_pin() {
  local name="$1" val="$2" d
  d="$(resolve_skill_dir "$name")" || die "no skill '$name' in $SKILLS"
  need_python
  py meta init "$d/.meta" created="$(today)" last_used="$(today)"
  py meta set "$d/.meta" pinned "$val"
  skills_commit "cairn: pin=$val $name"
  ok "$name: pinned=$val"
}
cmd_pin()   { [ $# -ge 1 ] || die "usage: cairn pin <name>";   _set_pin "$1" true; }
cmd_unpin() { [ $# -ge 1 ] || die "usage: cairn unpin <name>"; _set_pin "$1" false; }

# =============================================================================
# subcommand: provenance
# =============================================================================
cmd_provenance() {
  need_python
  if [ "${1:-}" = "--list" ] || [ -z "${1:-}" ]; then
    [ -d "$SKILLS" ] || die "no skills dir at $SKILLS"
    local fmt='%-32s %-9s %-6s %-8s %-4s %-4s %s\n'
    printf "$fmt" "SKILL" "PROV" "PINNED" "STATE" "QUAL" "USED" "LAST_USED"
    local d name
    for d in "$SKILLS"/*/; do
      [ -f "$d/SKILL.md" ] || continue
      name="$(basename "$d")"
      [ "$name" = "skill-extraction" ] && continue
      [ -f "$d/.meta" ] || { printf "$fmt" "$name" "(none)" "-" "-" "-" "-" "-"; continue; }
      printf "$fmt" "$name" \
        "$(py meta get "$d/.meta" provenance)" \
        "$(py meta get "$d/.meta" pinned)" \
        "$(py meta get "$d/.meta" state)" \
        "$(py meta get "$d/.meta" quality)" \
        "$(py meta get "$d/.meta" use_count)" \
        "$(py meta get "$d/.meta" last_used)"
    done
    return 0
  fi
  local name="$1" prov="${2:-}"
  [ -n "$prov" ] || die "usage: cairn provenance <name> <managed|bundled>"
  case "$prov" in managed|bundled) ;; *) die "provenance must be 'managed' or 'bundled'";; esac
  local d; d="$(resolve_skill_dir "$name")" || die "no skill '$name'"
  py meta init "$d/.meta" created="$(today)" last_used="$(today)"
  py meta set "$d/.meta" provenance "$prov"
  skills_commit "cairn: provenance=$prov $name"
  ok "$name: provenance=$prov"
}

# =============================================================================
# provisioning: install / migrate / uninstall
# =============================================================================
OLD_BEGIN='<!-- BEGIN skill-system (managed by claude-skill-system installer) -->'
OLD_END='<!-- END skill-system -->'

# strip a marker-delimited block (begin/end on their own lines) from a file
strip_block() { # strip_block <file> <begin> <end> -> stdout
  awk -v b="$2" -v e="$3" '
    index($0, b) == 1 {skip=1; next}
    index($0, e) == 1 {skip=0; next}
    !skip {print}
  ' "$1"
}

# detect a pre-existing skill setup (v1 or cairn)
detect_existing() {
  [ -d "$SKILLS" ] && ls -d "$SKILLS"/*/ >/dev/null 2>&1 && return 0
  [ -f "$CLAUDE_DIR/CLAUDE.md" ] && grep -qF "$OLD_BEGIN" "$CLAUDE_DIR/CLAUDE.md" 2>/dev/null && return 0
  [ -f "$CLAUDE_DIR/CLAUDE.md" ] && grep -qF "$BEGIN_MARK" "$CLAUDE_DIR/CLAUDE.md" 2>/dev/null && return 0
  [ -d "$CLAUDE_DIR/scripts" ] && ls "$CLAUDE_DIR/scripts"/skill-*.sh >/dev/null 2>&1 && return 0
  return 1
}

# copy this cairn tree (bin/lib/assets/logo) into ~/.claude/cairn so future
# `cairn` invocations are self-contained. No-op when already running from there.
self_install() {
  [ "$CAIRN_HOME" = "$STATE" ] && return 0
  if [ "$DRY" -eq 1 ]; then info "would copy bin/ lib/ assets/ into $STATE"; return 0; fi
  # idempotent skip when the dispatcher + a representative helper already match
  if cmp -s "$CAIRN_HOME/bin/cairn" "$STATE/bin/cairn" 2>/dev/null \
     && cmp -s "$CAIRN_HOME/lib/meta.py" "$STATE/lib/meta.py" 2>/dev/null \
     && cmp -s "$CAIRN_HOME/assets/claude-block.md" "$STATE/assets/claude-block.md" 2>/dev/null; then
    ok "cairn in $STATE (unchanged)"; return 0
  fi
  mkd "$STATE"
  cp -R "$CAIRN_HOME/bin"    "$STATE/" 2>/dev/null || true
  cp -R "$CAIRN_HOME/lib"    "$STATE/" 2>/dev/null || true
  cp -R "$CAIRN_HOME/assets" "$STATE/" 2>/dev/null || true
  [ -d "$CAIRN_HOME/tests" ] && cp -R "$CAIRN_HOME/tests" "$STATE/" 2>/dev/null || true
  [ -f "$LOGO" ] && cp "$LOGO" "$STATE/cairn-logo.txt"
  rm -rf "$STATE/lib/__pycache__" "$STATE/bin/README.md"   # build noise
  chmod +x "$STATE/bin/cairn" 2>/dev/null || true
  ok "installed cairn into $STATE"
}

# symlink the dispatcher onto PATH (~/.local/bin), else print guidance
link_cairn() {
  local target="$STATE/bin/cairn" dest="$HOME/.local/bin/cairn"
  [ "$DRY" -eq 1 ] && { info "would link $dest -> $target"; return 0; }
  if [ -d "$HOME/.local/bin" ] || mkdir -p "$HOME/.local/bin" 2>/dev/null; then
    ln -sf "$target" "$dest" && ok "linked $dest -> cairn"
    case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "add ~/.local/bin to PATH to run 'cairn' directly";; esac
  else
    warn "could not link onto PATH — run via $target or add it to PATH yourself"
  fi
}

# swap the managed CLAUDE.md block (remove old v1 + old cairn block, append new)
swap_block() {
  local md="$CLAUDE_DIR/CLAUDE.md" cand="$TMPD/md-candidate"
  [ "$DRY" -eq 1 ] && {
    if [ -f "$md" ] && grep -qF "$BEGIN_MARK" "$md"; then info "would replace existing cairn block in CLAUDE.md"
    elif [ -f "$md" ] && grep -qF "$OLD_BEGIN" "$md"; then info "would replace v1 skill-system block with cairn block"
    else info "would append cairn block to CLAUDE.md"; fi
    return 0
  }
  touch "$md"
  # Refuse to strip a hand-corrupted block (a BEGIN with no matching END would
  # make awk swallow everything to EOF). Warn loudly and leave CLAUDE.md alone.
  local pair
  for pair in "$BEGIN_MARK|$END_MARK" "$OLD_BEGIN|$OLD_END"; do
    local b="${pair%%|*}" e="${pair##*|}"
    if grep -qF "$b" "$md" && ! grep -qF "$e" "$md"; then
      warn "CLAUDE.md has a managed-block BEGIN marker with no END — looks hand-edited."
      warn "Leaving it untouched (no swap). Fix the markers, then re-run. Nothing was changed."
      return 0
    fi
  done
  # remove any old v1 block, then any existing cairn block
  strip_block "$md" "$OLD_BEGIN" "$OLD_END" > "$TMPD/md-1"
  strip_block "$TMPD/md-1" "$BEGIN_MARK" "$END_MARK" > "$TMPD/md-2"
  # trim trailing blank lines so re-runs converge byte-for-byte
  awk '{l[NR]=$0} END{n=NR; while(n>0 && l[n] ~ /^[[:space:]]*$/) n--; for(i=1;i<=n;i++) print l[i]}' \
    "$TMPD/md-2" > "$TMPD/md-trimmed"
  if [ -s "$TMPD/md-trimmed" ]; then
    { cat "$TMPD/md-trimmed"; printf '\n'; cat "$ASSETS/claude-block.md"; } > "$cand"
  else
    cp "$ASSETS/claude-block.md" "$cand"
  fi
  if cmp -s "$cand" "$md"; then
    ok "CLAUDE.md block up to date"
  else
    [ -s "$md" ] && cp "$md" "$md.bak-$CAIRN_TS"
    cp "$cand" "$md"
    [ -f "$md.bak-$CAIRN_TS" ] && ok "CLAUDE.md block swapped (backup: CLAUDE.md.bak-$CAIRN_TS)" || ok "CLAUDE.md block installed"
  fi
}

# stamp .meta on every skill that lacks one (default managed, dated from dir mtime)
stamp_meta() {
  local d name created
  for d in "$SKILLS"/*/; do
    [ -f "$d/SKILL.md" ] || continue
    name="$(basename "$d")"
    [ -f "$d/.meta" ] && continue
    created="$(dir_date "$d")"
    if [ "$DRY" -eq 1 ]; then info "would stamp .meta on $name (created=$created)"; continue; fi
    py meta init "$d/.meta" created="$created" last_used="$created"
    # the bundled meta-skill is infrastructure, protect it from curation
    [ "$name" = "skill-extraction" ] && py meta set "$d/.meta" provenance bundled
  done
}

# best-effort skill-dir date (last_used seed). GNU stat -c FIRST: GNU's `stat -f`
# succeeds with a wrong value, so trying BSD -f first would silently misread on
# Linux. GNU -c errors on macOS and falls through to BSD -f. Then epoch->date,
# again GNU (-d @epoch) with a BSD (-r epoch) fallback; else today.
dir_date() {
  local m
  m="$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null || echo "")"
  case "$m" in
    ''|*[!0-9]*) today ;;
    *) date -d "@$m" +%Y-%m-%d 2>/dev/null || date -r "$m" +%Y-%m-%d 2>/dev/null || today ;;
  esac
}

# seed empty learnings.md / usage.md / evals where missing (never touch existing)
seed_feedback() {
  local d name
  for d in "$SKILLS"/*/; do
    [ -f "$d/SKILL.md" ] || continue
    name="$(basename "$d")"
    [ "$name" = "skill-extraction" ] && continue
    [ "$DRY" -eq 1 ] && continue
    [ -f "$d/learnings.md" ] || printf '# Learnings — %s\n<!-- YYYY-MM-DD — what happened → what to do differently -->\n' "$name" > "$d/learnings.md"
    [ -f "$d/usage.md" ]     || printf '# Usage ratings — %s\n<!-- YYYY-MM-DD | N/5 | task context | helped or hindered -->\n' "$name" > "$d/usage.md"
  done
}

# one-time move of v1 working state into cairn/
relocate_state() {
  [ "$DRY" -eq 1 ] && { [ -d "$CLAUDE_DIR/skill-harvest" ] && info "would move skill-harvest -> cairn/harvest"; [ -d "$CLAUDE_DIR/skill-archive" ] && info "would move skill-archive -> cairn/skill-archive"; return 0; }
  if [ -d "$CLAUDE_DIR/skill-harvest" ] && [ ! -e "$HARVEST" ]; then
    mkd "$STATE"; mv "$CLAUDE_DIR/skill-harvest" "$HARVEST" && ok "moved skill-harvest -> cairn/harvest"
  fi
  if [ -d "$CLAUDE_DIR/skill-archive" ] && [ ! -e "$ARCHIVE" ]; then
    mkd "$STATE"; mv "$CLAUDE_DIR/skill-archive" "$ARCHIVE" && ok "moved skill-archive -> cairn/skill-archive"
  fi
}

# the shared, idempotent install/migrate core
provision() {
  local enable_hooks="$1" assess="$2"
  CAIRN_TS="$(ts)"
  TMPD="$(mktemp -d)"; trap 'rm -rf "$TMPD"' RETURN

  hdr "Detect"
  if detect_existing; then ok "existing setup found — migrating in place"; else ok "fresh install"; fi

  hdr "Snapshot"
  if has_git; then
    if skills_is_repo; then
      skills_commit "cairn: pre-migration snapshot"; ok "snapshotted skills/ (git)"
    else
      if [ "$DRY" -eq 1 ]; then info "would git init $SKILLS"; else
        mkd "$SKILLS"
        ( cd "$SKILLS" && { git init -q -b main 2>/dev/null || git init -q; } && printf '.DS_Store\n' > .gitignore )
        skills_commit "cairn: initial snapshot"; ok "git-initialised skills/"
      fi
    fi
  else warn "git not found — skill repo not initialised (everything else proceeds)"; fi

  # relocate v1 state BEFORE creating cairn/ dirs, so the "target absent" guard fires
  hdr "Relocate state"
  relocate_state

  hdr "Directories"
  mkd "$SKILLS" "$MEMORIES" "$COMMANDS" "$TEMPLATES/skill-template/evals" \
      "$HARVEST" "$ARCHIVE" "$LOGS"
  ok "$CLAUDE_DIR/{skills,memories,commands,templates,cairn/{harvest,skill-archive,logs}}"

  hdr "Dispatcher"
  self_install
  link_cairn

  hdr "Commands"
  local f
  for f in "$ASSETS"/commands/*.md; do
    put "$f" "$COMMANDS/$(basename "$f")" "commands/$(basename "$f")"
  done

  hdr "Template + meta-skill"
  ( cd "$ASSETS/templates/skill-template" && find . -type f -print | LC_ALL=C sort ) | while read -r rel; do
    rel="${rel#./}"
    put "$ASSETS/templates/skill-template/$rel" "$TEMPLATES/skill-template/$rel" "templates/skill-template/$rel"
  done
  put "$ASSETS/skills/skill-extraction/SKILL.md" "$SKILLS/skill-extraction/SKILL.md" "skills/skill-extraction/SKILL.md"

  # Memory BEFORE the CLAUDE.md block, which @-imports these files at session start
  hdr "Memory"
  if [ "$DRY" -eq 1 ]; then info "would init memories/USER.md ($USER_CAP) + MEMORY.md ($MEMORY_CAP) if absent"; else
    mkd "$MEMORIES"
    py memory init "$USER_MD"   "$USER_CAP"   "USER model (cairn)"  && ok "memories/USER.md"
    py memory init "$MEMORY_MD" "$MEMORY_CAP" "Agent notes (cairn)" && ok "memories/MEMORY.md"
  fi

  hdr "CLAUDE.md"
  swap_block

  hdr "Skill metadata"
  stamp_meta
  seed_feedback
  [ "$DRY" -eq 1 ] || ok "every skill stamped with .meta"

  if [ "$assess" -eq 1 ] && [ "$DRY" -ne 1 ]; then
    hdr "Assess (quality scoring)"
    if command -v claude >/dev/null 2>&1; then assess_skills; else warn "claude not on PATH — skipping assessment (re-run: cairn migrate)"; fi
  elif [ "$assess" -eq 1 ]; then
    info "would assess each skill's quality (1-5) into .meta"
  fi

  if [ "$enable_hooks" -eq 1 ]; then hdr "Hooks"; enable_hooks; fi

  hdr "Commit"
  skills_commit "cairn: migrated to 2.0"
  [ "$DRY" -eq 1 ] || { skills_is_repo && ok "committed skills/ ($(skills_git rev-parse --short HEAD 2>/dev/null))"; }

  hdr "Done"
  [ "$DRY" -eq 1 ] && { info "dry run — nothing changed"; return 0; }
  ok "cairn $CAIRN_VERSION ready"
  info "next: start a NEW Claude Code session, then try  cairn status  ·  /skill-new demo"
  local lowq; lowq="$(low_quality_list)"
  [ -n "$lowq" ] && { warn "low-quality skills flagged (improve / pin / merge):"; printf '%s\n' "$lowq" | sed 's/^/      /'; }
  if [ "$assess" -eq 0 ] && unscored_managed_exists; then
    info "tip: 'cairn migrate' also scores your existing skills' quality (model calls)"
  fi
}

# true if any managed, non-bundled skill has no quality score yet
unscored_managed_exists() {
  local d
  for d in "$SKILLS"/*/; do
    [ -f "$d/.meta" ] || continue
    [ "$(basename "$d")" = "skill-extraction" ] && continue
    [ "$(py meta get "$d/.meta" provenance)" = "bundled" ] && continue
    [ -z "$(py meta get "$d/.meta" quality)" ] && return 0
  done
  return 1
}

# score one skill's reusability/quality 1-5 into .meta quality=
SCORE_PROMPT='You are assessing ONE Claude Code skill for REUSABILITY/QUALITY. On stdin is
its SKILL.md. Reply with ONLY a single digit 1-5, nothing else:
  5 = broad, well-formed, class-level skill that transfers across projects
  4 = reusable within a tech stack or domain, clear triggers + procedure
  3 = reusable within one setup, parameterizable
  2 = mostly specific; only a small transferable core
  1 = hyper-specific one-off / runbook / malformed — not really a skill.'
score_one_skill() { # score_one_skill <skill-dir> -> prints 1-5 or empty
  # own a temp dir — do NOT depend on a provision-scoped $TMPD (curate has none).
  local d="$1" td rcs; td="$(mktemp -d)"
  run_claude "$SCORE_PROMPT" "$MODEL_DEFAULT" "$d/SKILL.md" "$td/score.out" "$td/score.err" 2 "$(basename "$d")" "$LOGS/assess.log"
  rcs=$?
  [ "$rcs" -eq 0 ] && tr -dc '12345' < "$td/score.out" | cut -c1
  rm -rf "$td"
  [ "$rcs" -eq 0 ] || return 1
}
assess_skills() {
  local d name q n=0
  for d in "$SKILLS"/*/; do
    [ -f "$d/SKILL.md" ] || continue
    name="$(basename "$d")"
    [ "$name" = "skill-extraction" ] && continue
    [ "$(py meta get "$d/.meta" provenance)" = "bundled" ] && continue
    [ -n "$(py meta get "$d/.meta" quality)" ] && continue   # already scored
    q="$(score_one_skill "$d")"
    if [ -n "$q" ]; then py meta set "$d/.meta" quality "$q"; n=$((n+1)); ok "$name → quality $q"; fi
  done
  ok "assessed $n skill(s)"
}
low_quality_list() {
  local d name q
  for d in "$SKILLS"/*/; do
    [ -f "$d/.meta" ] || continue
    name="$(basename "$d")"
    q="$(py meta get "$d/.meta" quality)"
    case "$q" in 1|2) printf '%s (quality %s)\n' "$name" "$q";; esac
  done
}

# SessionEnd hook: review automatically. Safe, backed-up, reversible JSON merge.
# Only backs up + rewrites settings.json when the content actually changes.
enable_hooks() {
  local settings="$CLAUDE_DIR/settings.json"
  if [ "$DRY" -eq 1 ]; then info "would add SessionEnd review + UserPromptSubmit suggest + PostToolUse track hooks to settings.json (backed up)"; return 0; fi
  need_python
  local tmp status sf
  tmp="$settings.cairn-tmp.$$"; sf="$settings.cairn-st.$$"
  # NOTE: the heredoc is redirected to a file, NOT nested inside $() — bash 3.2's
  # parser desyncs on a here-document inside a command substitution.
  python3 - "$settings" "$tmp" "$STATE/bin/cairn" "$LOGS/review-hook.log" > "$sf" 2>/dev/null <<'PYEOF'
import sys, json, os
settings, tmp, cairn_bin, logf = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
data = {}
if os.path.isfile(settings):
    try: data = json.load(open(settings))
    except Exception: data = {}
if not isinstance(data, dict): data = {}
before = json.dumps(data, sort_keys=True)
hooks = data.setdefault("hooks", {})

def upsert(event, needle, command, matcher=None):
    arr = hooks.setdefault(event, [])
    for group in arr:
        for h in (group.get("hooks", []) if isinstance(group, dict) else []):
            if isinstance(h, dict) and "cairn" in str(h.get("command", "")) and needle in str(h.get("command", "")):
                h["command"] = command
                return
    grp = {"hooks": [{"type": "command", "command": command}]}
    if matcher:
        grp["matcher"] = matcher
    arr.append(grp)

# SessionEnd -> post-session review (CAPTURE). Recursion guard: the hook's own
# `claude -p` would re-fire SessionEnd; CAIRN_REVIEW_HOOK (set by `cairn review`)
# makes nested runs no-op. ${VAR:-} keeps it safe under a nounset hook shell.
upsert("SessionEnd", "review",
       '[ -n "${CAIRN_REVIEW_HOOK:-}" ] && exit 0; "%s" review --hook >> "%s" 2>&1' % (cairn_bin, logf))
# UserPromptSubmit -> surface matching skills at task start (USE). Local, no model
# call; `|| true` keeps a matcher hiccup from ever blocking the prompt.
upsert("UserPromptSubmit", "suggest", '"%s" suggest --hook 2>/dev/null || true' % cairn_bin)
# PostToolUse on the Skill tool -> record REAL activation telemetry (use_count,
# last_used) for the invoked skill. Reliable: it only writes a file (no mid-turn
# context injection), so unlike the re-surface below, this one belongs on.
upsert("PostToolUse", "track", '"%s" track --hook 2>/dev/null || true' % cairn_bin, matcher="Skill")
# NOTE: a PostToolUse mid-task re-surface (`cairn suggest --tick`) is deliberately
# NOT wired here — verified that PostToolUse additionalContext is only an advisory
# system-reminder, not fed into the model's reasoning stream, so it adds per-call
# overhead for no reliable gain. It stays an off-by-default, opt-in experiment.

# NOTE: cairn deliberately does NOT touch `skillListingBudgetFraction`. An earlier
# version set it to 0 to "silence" Claude Code's native skill listing, but 0 is an
# undocumented value that Claude Code's validator rejects (and strips) — and the
# native listing at its default is benign (it collapses the long tail to bare names,
# which is fine). The suggest hook complements that listing; it does not replace it.

if json.dumps(data, sort_keys=True) == before:
    print("unchanged")
else:
    json.dump(data, open(tmp, "w"), indent=2)
    print("changed")
PYEOF
  status="$(cat "$sf" 2>/dev/null)"; rm -f "$sf"
  if [ "$status" = "changed" ]; then
    [ -f "$settings" ] && cp "$settings" "$settings.bak-$CAIRN_TS"
    mv "$tmp" "$settings"
    ok "hooks installed: SessionEnd review (capture) + UserPromptSubmit suggest (surface at task start) + PostToolUse track (real use_count). Disable: cairn uninstall."
  else
    rm -f "$tmp" 2>/dev/null || true
    ok "cairn hooks already present (no change)"
  fi
}

cmd_install() {
  local hooks=0
  while [ $# -gt 0 ]; do case "$1" in --enable-hooks) hooks=1;; *) die "install: unknown option $1";; esac; shift; done
  need_python
  command -v claude >/dev/null 2>&1 || warn "claude not on PATH — file install proceeds; model steps (mine/review/assess) need it"
  provision "$hooks" 0
}

cmd_migrate() {
  local assess=1 hooks=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run)    DRY=1 ;;
      --no-assess)  assess=0 ;;
      --enable-hooks) hooks=1 ;;
      *) die "migrate: unknown option $1" ;;
    esac; shift
  done
  need_python
  provision "$hooks" "$assess"
}

cmd_uninstall() {
  CAIRN_TS="$(ts)"
  hdr "Uninstall"
  local f
  for f in "$ASSETS"/commands/*.md; do rm -f "$COMMANDS/$(basename "$f")"; done
  rm -rf "$TEMPLATES/skill-template"
  # remove the cairn-created meta-skill incl. its .meta so the dir actually empties
  rm -f "$SKILLS/skill-extraction/SKILL.md" "$SKILLS/skill-extraction/.meta"
  rmdir "$SKILLS/skill-extraction" 2>/dev/null || true
  ok "removed commands, template, meta-skill"
  # CLAUDE.md block
  local md="$CLAUDE_DIR/CLAUDE.md"
  if [ -f "$md" ] && grep -qF "$BEGIN_MARK" "$md"; then
    cp "$md" "$md.bak-$CAIRN_TS"
    strip_block "$md" "$BEGIN_MARK" "$END_MARK" > "$md.tmp" && mv "$md.tmp" "$md"
    ok "managed block removed from CLAUDE.md (backup: CLAUDE.md.bak-$CAIRN_TS)"
  fi
  # remove cairn's hooks (SessionEnd review + UserPromptSubmit suggest) — only
  # touch settings.json if a cairn hook is actually present
  if [ -f "$CLAUDE_DIR/settings.json" ] && command -v python3 >/dev/null 2>&1 \
     && grep -q 'cairn' "$CLAUDE_DIR/settings.json" 2>/dev/null; then
    cp "$CLAUDE_DIR/settings.json" "$CLAUDE_DIR/settings.json.bak-$CAIRN_TS"
    python3 - "$CLAUDE_DIR/settings.json" <<'PYEOF'
import sys, json
p = sys.argv[1]
try: data = json.load(open(p))
except Exception: sys.exit(0)
def is_cairn(h):
    c = str(h.get("command", "")) if isinstance(h, dict) else ""
    return "cairn" in c and ("review" in c or "suggest" in c or "track" in c)
for event in ("SessionEnd", "UserPromptSubmit", "PostToolUse"):
    arr = data.get("hooks", {}).get(event, [])
    keep = []
    for group in arr:
        hs = [h for h in (group.get("hooks", []) if isinstance(group, dict) else []) if not is_cairn(h)]
        if hs: keep.append({"hooks": hs})
    if "hooks" in data and event in data["hooks"]:
        if keep: data["hooks"][event] = keep
        else: del data["hooks"][event]
    if "hooks" in data and not data["hooks"]: del data["hooks"]
json.dump(data, open(p, "w"), indent=2)
PYEOF
    # if removing our hook left an empty {} (cairn likely created it via
    # --enable-hooks), drop it — the .bak preserves the prior state.
    [ "$(tr -d ' \n\t' < "$CLAUDE_DIR/settings.json" 2>/dev/null)" = "{}" ] && rm -f "$CLAUDE_DIR/settings.json"
    ok "cairn hooks removed from settings.json"
  fi
  sched_disable
  # remove the PATH symlink only if it actually points at cairn's own dispatcher
  if [ -L "$HOME/.local/bin/cairn" ]; then
    case "$(readlink "$HOME/.local/bin/cairn" 2>/dev/null)" in
      */cairn/bin/cairn) rm -f "$HOME/.local/bin/cairn" ;;
    esac
  fi
  info "Left untouched: your skills, their .meta, memory, the git repo, $STATE."
  info "Remove the rest yourself if you want: rm -rf $STATE  (it holds the dispatcher + archive)."
}

# =============================================================================
# subcommand: review  (Layer B — the loop's heart, G5)
# =============================================================================
REVIEW_PROMPT='You are running Cairn'\''s post-session review. A flattened, redacted
transcript of the session just ended is on stdin. Decide what (if anything) to
save, and APPLY it directly — you act on files, you do not chat. Be ACTIVE:
most sessions produce at least one update.

Tools: use Read/Glob/Grep to inspect and Edit/Write to change files under
__SKILLS__ and __TEMPLATES__ (use ONLY these absolute paths — never any other
skills dir). Use Bash ONLY for `cairn memory ...`
(the harness commits for you — you do not need git, ls, cat, or any other shell
command; use Glob/Grep/Read to explore, never Bash). Do nothing destructive. Ask
no questions (no user is present); make conservative choices.

SKILLS — apply the update decision tree, stopping at the FIRST that fits:
  1. patch a skill loaded/consulted this session (fix a step, add a pitfall,
     broaden a description trigger),
  2. else patch an existing umbrella skill in __SKILLS__,
  3. else add a support file under the nearest umbrella —
     references/<topic>.md (detail/quirks), templates/<name> (starters), or
     scripts/<name> (re-runnable actions) — and add a one-line SKILL.md pointer,
  4. else create a new CLASS-LEVEL umbrella from __TEMPLATES__/skill-template/
     (class-level name only — never a ticket/error string/"fix-X-today").
  Re-read a file before editing; keep frontmatter valid (name + description
  <=1024 chars). NEVER edit a skill whose .meta says provenance=bundled or
  pinned=true (e.g. skill-extraction) — those are protected. Just edit files;
  the harness commits.

DO NOT capture: environment-dependent failures (save the FIX, not "X is broken"),
negative claims about tools, transient errors that resolved on retry, or one-off
task narratives. Route style/workflow corrections ("too verbose", "stop doing X")
into the governing skill'\''s BODY.

MEMORY — only durable facts, respecting char caps (a rejection means trim/replace):
  - new lasting user preference/style/habit -> `cairn memory user add "..."`
  - new durable environment fact/convention/quirk -> `cairn memory agent add "..."`
  Memory is who-the-user-is + state-of-things; skills are how-to-do-a-class-of-task.
  Never store task procedures in memory, or this prompt'\''s own text.

FEEDBACK — for each skill actually used this session, append one honest line to
its usage.md (YYYY-MM-DD | N/5 | context | helped/hindered); append dated
learnings.md lines for any corrections.

End by printing a 1-3 line summary of exactly what you changed (or "no changes").'

cmd_review() {
  local transcript="" hook=0 model="$MODEL_DEFAULT" dry=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --hook)   hook=1 ;;
      --model)  model="${2:-$MODEL_DEFAULT}"; shift ;;
      --dry-run) dry=1 ;;
      --*)      die "review: unknown option $1" ;;
      *)        transcript="$1" ;;
    esac; shift
  done
  need_python
  mkdir -p "$LOGS"
  local lf="$LOGS/review.log"

  # recursion guard: the hook exports CAIRN_REVIEW_HOOK; never review our own run
  if [ -n "${CAIRN_REVIEW_HOOK:-}" ] && [ "$hook" -eq 0 ]; then
    return 0
  fi

  # locate the transcript
  if [ "$hook" -eq 1 ] && [ -z "$transcript" ]; then
    transcript="$(python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("transcript_path",""))
except Exception: print("")' 2>/dev/null)"
  fi
  if [ -z "$transcript" ]; then
    # newest session whose cwd is under the current directory
    transcript="$(py transcript discover "$CLAUDE_DIR/projects" "$PWD" 0 0 2>/dev/null | head -1 | cut -f1)"
  fi
  [ -n "$transcript" ] && [ -f "$transcript" ] || { say "$lf" "review: no transcript found"; [ "$hook" -eq 1 ] && return 0; die "no transcript to review (pass a path)"; }

  local flat; flat="$(py transcript flatten-file "$transcript" 60000)"
  if [ -z "$flat" ]; then say "$lf" "review: empty transcript ($transcript)"; return 0; fi

  if [ "$dry" -eq 1 ]; then
    hdr "review (dry run)"
    info "transcript: $transcript"
    info "flattened: $(printf '%s' "$flat" | wc -c | tr -d ' ') chars"
    info "model: $model — would run one scoped claude -p with the review prompt"
    return 0
  fi

  need_claude
  say "$lf" "review: $transcript (model $model)"
  # bind the prompt to the ACTUAL configured paths (correct under a relocated
  # config dir, and keeps the review scoped to the right skills dir)
  local prompt="${REVIEW_PROMPT//__SKILLS__/$SKILLS}"
  prompt="${prompt//__TEMPLATES__/$TEMPLATES}"
  # CAIRN_REVIEW_HOOK on the claude env guards the nested SessionEnd it would fire.
  # Scope the cairn subcommands the review may call to the non-destructive ones
  # (memory/provenance/pin/unpin) — never uninstall/curate/migrate/install.
  printf '%s' "$flat" | CAIRN_REVIEW_HOOK=1 claude -p "$prompt" \
    --model "$model" \
    --max-turns 30 \
    --permission-mode acceptEdits \
    --allowedTools "Read,Edit,Write,Glob,Grep,Bash(cairn memory:*),Bash(cairn provenance:*),Bash(cairn pin:*),Bash(cairn unpin:*)" \
    >> "$lf" 2>&1
  local rc=$?
  # telemetry: skills the review touched count as used this session. Claude Code
  # has no per-activation hook, so "the review engaged this skill" is the signal.
  if skills_is_repo; then
    local s
    for s in $(skills_git status --porcelain 2>/dev/null | awk '{print $NF}' | cut -d/ -f1 | sort -u); do
      { [ -n "$s" ] && [ "$s" != "skill-extraction" ] && [ -f "$SKILLS/$s/SKILL.md" ]; } || continue
      py meta init "$SKILLS/$s/.meta" created="$(today)" last_used="$(today)" 2>/dev/null || true
      py meta set  "$SKILLS/$s/.meta" last_used "$(today)" 2>/dev/null || true
      py meta bump "$SKILLS/$s/.meta" use_count 2>/dev/null || true
    done
  fi
  skills_commit "cairn: review of $(basename "$transcript")"
  if [ "$rc" -eq 0 ]; then say "$lf" "review: done"; ok "review complete (log: $lf)"
  else say "$lf" "review: claude exited $rc"; [ "$hook" -eq 1 ] || warn "review ended with code $rc (see $lf)"; fi
  return 0
}

# =============================================================================
# subcommand: curate  (Layer B — consolidation + lifecycle, G8/G9/G10)
# =============================================================================
CURATE_THRESHOLD="${CAIRN_CURATE_THRESHOLD:-0.40}"
FOLD_AT="${CAIRN_FOLD_AT:-15}"
STALE_DAYS="${CAIRN_STALE_DAYS:-30}"
ARCHIVE_DAYS="${CAIRN_ARCHIVE_DAYS:-90}"
USE_MIN="${CAIRN_USE_MIN:-3}"
USE_AVG="${CAIRN_USE_AVG:-2.5}"

# is a skill protected from auto-curation? (bundled / pinned / the meta-skill)
is_protected() {
  local n="$1"
  [ "$n" = "skill-extraction" ] && return 0
  [ "$(py meta get "$SKILLS/$n/.meta" provenance 2>/dev/null)" = "bundled" ] && return 0
  [ "$(py meta get "$SKILLS/$n/.meta" pinned 2>/dev/null)" = "true" ] && return 0
  return 1
}

# archive a skill: MOVE to the archive (never delete), stamp the moved copy.
# echoes the destination path on success; returns non-zero on failure.
archive_skill() {
  local n="$1" d="$SKILLS/$1" dest
  [ -d "$d" ] || return 1
  mkd "$ARCHIVE"
  dest="$ARCHIVE/$n-$(ts)"
  [ -e "$dest" ] && dest="$dest-$$"
  if mv "$d" "$dest" 2>/dev/null; then
    py meta set "$dest/.meta" state archived 2>/dev/null || true
    printf '%s\n' "$dest"
    return 0
  fi
  return 1
}

MERGE_PROMPT='You are merging several overlapping Claude Code skills into ONE class-level
umbrella skill. Each source skill'\''s SKILL.md is on stdin, separated by lines like
"===== <name> =====". Produce ONE merged SKILL.md and NOTHING else:
- YAML frontmatter delimited by --- with `name:` (the clearest existing name or a
  better kebab-case umbrella name) and `description:` (the UNION of the distinct
  triggers, deduplicated, concrete "Use when ..." phrasing, <=1024 chars),
- a body that merges the procedures into clearly labelled subsections, removes
  duplicate steps, reconciles overlaps, and preserves every distinct piece of
  guidance and success criterion from the sources.
Output ONLY the file content, starting with "---". No prose, no code fences.'

cmd_curate() {
  need_python
  [ -d "$SKILLS" ] || die "no skills dir at $SKILLS"
  local apply=0 do_merge=0 do_weak=0 do_assess=0 yes=0
  while [ $# -gt 0 ]; do case "$1" in
    --apply-lifecycle) apply=1 ;;
    --merge)           do_merge=1 ;;
    --archive-weak)    do_weak=1 ;;
    --assess)          do_assess=1 ;;
    --yes|-y)          yes=1 ;;
    --threshold)       CURATE_THRESHOLD="${2:-0.40}"; shift ;;
    *) die "curate: unknown option $1" ;;
  esac; shift; done
  mkdir -p "$HARVEST" "$LOGS"
  local TMPD_C out body
  TMPD_C="$(mktemp -d)"
  out="$HARVEST/CURATE.md"
  body="$TMPD_C/body.md"

  # ---- consolidation analysis (umbrella-building, fold, low-usefulness) ----
  python3 - "$SKILLS" "$CURATE_THRESHOLD" "$FOLD_AT" "$body" <<'PYEOF'
import sys, os, re, glob, itertools
SKILLS, THRESH, FOLD, OUT = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
USE_MIN = int(os.environ.get('CAIRN_USE_MIN', '3'))
USE_AVG = float(os.environ.get('CAIRN_USE_AVG', '2.5'))
STOP = set("""a an the of to and or for with use used using when this that those these on
in into your you user users claude skill skills it its as be by from at if then else do
does done can will would should task tasks help via run runs new also etc""".split())
def toks(s): return set(t for t in re.split(r'[^a-z0-9]+', s.lower()) if len(t) > 2 and t not in STOP)
def frontmatter(p):
    name=desc=""
    try:
        t=open(p,errors='replace').read(); m=re.search(r'^---\s*\n(.*?)\n---',t,re.S); fm=m.group(1) if m else ""
        nm=re.search(r'^name:[ \t]*(.+)$',fm,re.M); name=nm.group(1).strip() if nm else ""
        dm=re.search(r'^description:[ \t]*(.+)$',fm,re.M); desc=dm.group(1).strip() if dm else ""
    except Exception: pass
    return name,desc
def learn_count(d):
    p=os.path.join(SKILLS,d,'learnings.md');
    if not os.path.isfile(p): return 0
    n=0
    for line in open(p,errors='replace'):
        ls=line.strip()
        if ls.startswith('<!--') or not ls: continue
        if ls.startswith('-') or re.match(r'^\d{4}-\d{2}-\d{2}',ls): n+=1
    return n
def usage_stats(d):
    p=os.path.join(SKILLS,d,'usage.md')
    if not os.path.isfile(p): return (None,0)
    sc=[]
    for line in open(p,errors='replace'):
        m=re.match(r'\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5',line)
        if m: sc.append(int(m.group(1)))
    return ((sum(sc)/len(sc)) if sc else None, len(sc))
def meta_get(d,key):
    p=os.path.join(SKILLS,d,'.meta')
    if os.path.isfile(p):
        for line in open(p,errors='replace'):
            if line.strip().startswith(key+'='): return line.split('=',1)[1].strip()
    return ''
skills=[]
for dpath in sorted(glob.glob(os.path.join(SKILLS,'*'))):
    sp=os.path.join(dpath,'SKILL.md')
    if not os.path.isfile(sp): continue
    dirn=os.path.basename(dpath)
    if dirn=='skill-extraction': continue
    if meta_get(dirn,'provenance')=='bundled' or meta_get(dirn,'pinned')=='true': continue  # protected
    name,desc=frontmatter(sp); uavg,uc=usage_stats(dirn)
    skills.append({'dir':dirn,'name':name or dirn,'desc':desc,'toks':toks((name or dirn)+' '+desc),
                   'learn':learn_count(dirn),'uavg':uavg,'uc':uc,'q':meta_get(dirn,'quality')})
def jac(a,b): return len(a&b)/len(a|b) if a and b else 0.0
pairs=[(i,j,jac(skills[i]['toks'],skills[j]['toks'])) for i,j in itertools.combinations(range(len(skills)),2) if jac(skills[i]['toks'],skills[j]['toks'])>=THRESH]
parent=list(range(len(skills)))
def find(x):
    while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
    return x
for i,j,_ in pairs: parent[find(i)]=find(j)
groups={}
for idx in range(len(skills)): groups.setdefault(find(idx),[]).append(idx)
clusters=[g for g in groups.values() if len(g)>1]
def best(g): return max([jac(skills[a]['toks'],skills[b]['toks']) for a,b in itertools.combinations(g,2)] or [0])
clusters.sort(key=best,reverse=True)
folds=sorted([s for s in skills if s['learn']>=FOLD],key=lambda s:s['learn'],reverse=True)
lowuse=sorted([s for s in skills if s['uc']>=USE_MIN and s['uavg'] is not None and s['uavg']<=USE_AVG],key=lambda s:s['uavg'])
lowq=sorted([s for s in skills if s['q'] in ('1','2')],key=lambda s:s['q'])
L=[]
if clusters:
    L.append("## Merge into umbrellas (%d cluster(s))"%len(clusters)); L.append("")
    L.append("For each cluster ask: would a maintainer write these as N skills, or "
             "ONE umbrella with N labelled subsections? Merge when the latter "
             "(demote narrow siblings to references/templates/scripts).")
    L.append("")
    for g in clusters:
        ms=[skills[i] for i in g]
        L.append("### %s  (overlap %.2f)"%(' + '.join(m['dir'] for m in ms),best(g)))
        for m in ms:
            d=(m['desc'][:140]+'…') if len(m['desc'])>140 else m['desc']
            L.append("- **%s** — %s%s"%(m['dir'], d or '(no description)', ("  · %d learning(s)"%m['learn']) if m['learn'] else ""))
        L.append(""); L.append("    /skill-merge %s"%(' '.join(m['dir'] for m in ms))); L.append("")
if folds:
    L.append("## Fold candidates (%d)"%len(folds)); L.append("")
    L.append("learnings.md has grown enough to fold stable entries into SKILL.md."); L.append("")
    for s in folds: L.append("- **%s** — %d learning entries"%(s['dir'],s['learn'])); L.append("      /skill-fold %s"%s['dir'])
    L.append("")
if lowuse:
    L.append("## Low-usefulness (%d)"%len(lowuse)); L.append("")
    L.append("Scored poorly across real uses — improve, or merge into something better."); L.append("")
    for s in lowuse: L.append("- **%s** — avg %.1f/5 over %d use(s)"%(s['dir'],s['uavg'],s['uc'])); L.append("      /skill-improve %s"%s['dir'])
    L.append("")
if lowq:
    L.append("## Low-quality — assessed 1-2/5 (%d)"%len(lowq)); L.append("")
    L.append("These scored low on the quality assessment (`cairn migrate`). Improve them, "
             "merge them into a stronger umbrella, or archive in one pass with "
             "`cairn curate --archive-weak`."); L.append("")
    for s in lowq:
        d=(s['desc'][:120]+'…') if len(s['desc'])>120 else s['desc']
        L.append("- **%s** — quality %s/5 — %s"%(s['dir'],s['q'],d or '(no description)'))
        L.append("      /skill-improve %s   ·   or  cairn curate --archive-weak"%s['dir'])
    L.append("")
open(OUT,'w').write('\n'.join(L)+('\n' if L else ''))
print("clusters=%d folds=%d lowuse=%d lowq=%d scanned=%d"%(len(clusters),len(folds),len(lowuse),len(lowq),len(skills)))
PYEOF

  # ---- lifecycle proposals (G9) ----
  local life="$TMPD_C/life.tsv"
  py lifecycle propose "$SKILLS" "$(today)" "$STALE_DAYS" "$ARCHIVE_DAYS" > "$life" 2>/dev/null || : > "$life"

  # ---- assemble report ----
  {
    echo "# Cairn curate report ($(date '+%Y-%m-%d %H:%M'))"
    echo
    echo "Scanned \`$SKILLS\` — overlap≥$CURATE_THRESHOLD, fold-at $FOLD_AT, stale@${STALE_DAYS}d, archive@${ARCHIVE_DAYS}d."
    echo "Read-only by default. Merges are manual (/skill-merge); lifecycle applies with --apply-lifecycle."
    echo
    if [ -s "$body" ]; then cat "$body"; else echo "_No merge / fold / low-usefulness candidates. Library looks tidy._"; echo; fi
    echo "## Lifecycle transitions (by inactivity)"
    echo
    if [ -s "$life" ]; then
      echo "| skill | from | to | idle (days) |"
      echo "|---|---|---|---|"
      while IFS="$(printf '\t')" read -r name from to idle; do
        [ -n "$name" ] && echo "| $name | $from | $to | $idle |"
      done < "$life"
      echo
      echo "(pinned and bundled skills are never auto-transitioned.)"
    else
      echo "_No skills are stale or archivable. Nothing ages out._"
    fi
  } > "$out"

  ok "curate report: $out"
  sed -n '1,40p' "$out"

  # ---- apply lifecycle if asked (never deletes; skips pinned/bundled) ----
  if [ "$apply" -eq 1 ] && [ -s "$life" ]; then
    hdr "Applying lifecycle"
    local name from to idle moved=0 staled=0
    while IFS="$(printf '\t')" read -r name from to idle; do
      [ -n "$name" ] || continue
      local d="$SKILLS/$name"
      [ -d "$d" ] || continue
      case "$to" in
        stale)
          py meta set "$d/.meta" state stale; staled=$((staled+1)); ok "$name → stale" ;;
        archived)
          local dest
          if dest="$(archive_skill "$name")"; then moved=$((moved+1)); ok "$name → archived ($dest)"
          else warn "$name: archive move failed — left in place, state unchanged"; fi ;;
      esac
    done < "$life"
    skills_commit "cairn: lifecycle ($staled stale, $moved archived)"
    ok "lifecycle applied: $staled stale, $moved archived (recoverable in $ARCHIVE + git)"
  fi

  # ---- MERGE mode: auto-consolidate overlapping clusters into umbrellas ----
  # preview unless --yes. originals are archived (recoverable), never deleted.
  if [ "$do_merge" -eq 1 ]; then
    hdr "Merge overlapping skills into umbrellas"
    [ "$yes" -eq 1 ] || info "PREVIEW — add --yes to execute. Originals are archived, never deleted."
    local cl; cl="$(py cluster skills "$SKILLS" "$CURATE_THRESHOLD" 2>/dev/null)"
    if [ -z "$cl" ]; then ok "no overlapping clusters at threshold $CURATE_THRESHOLD"; else
      [ "$yes" -eq 1 ] && need_claude
      local merged_n=0 line m members target rc dest
      while IFS= read -r line; do
        [ -n "$line" ] || continue
        members=""
        for m in $line; do is_protected "$m" || members="$members $m"; done
        set -- $members
        [ $# -ge 2 ] || { info "  skip (fewer than 2 unprotected): ${line//	/ }"; continue; }
        if [ "$yes" -ne 1 ]; then info "  would merge: $* → one umbrella"; continue; fi
        # feed every member's SKILL.md to the model
        local feed="$TMPD_C/merge.in" o2="$TMPD_C/merge.out" e2="$TMPD_C/merge.err"
        : > "$feed"
        for m in "$@"; do printf '===== %s =====\n' "$m" >> "$feed"; cat "$SKILLS/$m/SKILL.md" >> "$feed"; printf '\n' >> "$feed"; done
        say "$LOGS/curate.log" "merging: $*"
        run_claude "$MERGE_PROMPT" "$MODEL_DEFAULT" "$feed" "$o2" "$e2" 3 "merge" "$LOGS/curate.log"
        rc=$?
        [ "$rc" -ne 0 ] && { warn "merge failed for: $* (originals intact)"; continue; }
        # empty/malformed model output -> never touch a live skill
        [ -s "$o2" ] || { warn "merge produced no output for: $* (originals intact)"; continue; }
        # derive + SANITIZE the target name (model output is untrusted): reject
        # path traversal / dots / non-slug, falling back to the first member.
        target="$(grep -m1 '^name:' "$o2" | sed 's/^name:[[:space:]]*//' | tr -d "[:space:]\"'")"
        case "$target" in ''|*/*|*.*|.*) target="$1" ;; esac
        case "$target" in [a-z0-9]*) : ;; *) target="$1" ;; esac
        # refuse to write over an existing skill that is NOT part of this cluster,
        # and never over a protected skill.
        local is_member=0
        for m in "$@"; do [ "$m" = "$target" ] && is_member=1; done
        if [ -d "$SKILLS/$target" ] && [ "$is_member" -eq 0 ]; then
          warn "merge target '$target' collides with an existing non-member skill — skipped (originals intact)"; continue
        fi
        if is_protected "$target"; then warn "merge target '$target' is protected — skipped"; continue; fi
        # STAGE the merged SKILL.md in a temp dir and validate it THERE. Only write
        # into the live tree after it passes — a live skill is never overwritten by
        # unvalidated model output.
        local stage="$TMPD_C/stage"; rm -rf "$stage"; mkdir -p "$stage"; cp "$o2" "$stage/SKILL.md"
        if [ -n "$(py validate skill "$stage")" ]; then
          warn "merged '$target' failed frontmatter validation — skipped (originals intact)"; continue
        fi
        # order-preserving merged feedback from ALL members (read before archiving)
        { printf '# Learnings — %s\n' "$target"; for m in "$@"; do grep -hvE '^(#|<!--|[[:space:]]*$)' "$SKILLS/$m/learnings.md" 2>/dev/null; done | awk '!seen[$0]++'; } > "$TMPD_C/m.learn"
        { printf '# Usage ratings — %s\n' "$target"; for m in "$@"; do grep -hvE '^(#|<!--|[[:space:]]*$)' "$SKILLS/$m/usage.md" 2>/dev/null; done | awk '!seen[$0]++'; } > "$TMPD_C/m.usage"
        mkd "$SKILLS/$target"
        cp "$stage/SKILL.md" "$SKILLS/$target/SKILL.md"
        cp "$TMPD_C/m.learn" "$SKILLS/$target/learnings.md"; cp "$TMPD_C/m.usage" "$SKILLS/$target/usage.md"
        py meta init "$SKILLS/$target/.meta" created="$(today)" last_used="$(today)"
        py meta set "$SKILLS/$target/.meta" last_patched "$(today)"
        for m in "$@"; do [ "$m" = "$target" ] && continue; dest="$(archive_skill "$m")" && ok "  archived $m → merged into $target"; done
        merged_n=$((merged_n+1)); ok "merged [$*] → $target"
      done <<MERGE_EOF
$cl
MERGE_EOF
      if [ "$yes" -eq 1 ]; then skills_commit "cairn: auto-merged $merged_n cluster(s)"; ok "merged $merged_n cluster(s) (originals in $ARCHIVE + git)"; fi
    fi
  fi

  # ---- ARCHIVE-WEAK mode: archive low-quality / low-usefulness skills ----
  # preview unless --yes. with --assess, score unscored skills first (model calls).
  if [ "$do_weak" -eq 1 ]; then
    hdr "Archive weak skills"
    [ "$yes" -eq 1 ] || info "PREVIEW — add --yes to execute. Archived (recoverable), never deleted."
    if [ "$do_assess" -eq 1 ] && [ "$yes" -eq 1 ]; then need_claude; hdr "Assessing unscored skills first"; assess_skills; fi
    local weak wf="$TMPD_C/weak.tsv"   # heredoc to a file, not inside $() (bash 3.2)
    python3 - "$SKILLS" "$USE_AVG" "$USE_MIN" > "$wf" 2>/dev/null <<'PYEOF'
import sys, os, re, glob
SKILLS, UAVG, UMIN = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
def mg(d, k):
    p = os.path.join(SKILLS, d, '.meta')
    if os.path.isfile(p):
        for l in open(p, errors='replace'):
            if l.strip().startswith(k + '='): return l.split('=', 1)[1].strip()
    return ''
def uavg(d):
    p = os.path.join(SKILLS, d, 'usage.md'); sc = []
    if os.path.isfile(p):
        for l in open(p, errors='replace'):
            m = re.match(r'\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5', l)
            if m: sc.append(int(m.group(1)))
    return (sum(sc)/len(sc) if sc else None, len(sc))
for dp in sorted(glob.glob(os.path.join(SKILLS, '*'))):
    d = os.path.basename(dp)
    if not os.path.isfile(os.path.join(dp, 'SKILL.md')) or d == 'skill-extraction': continue
    if mg(d, 'provenance') == 'bundled' or mg(d, 'pinned') == 'true' or mg(d, 'state') == 'archived': continue
    q = mg(d, 'quality'); a, n = uavg(d); reason = None
    if q in ('1', '2'): reason = 'quality ' + q
    elif a is not None and n >= UMIN and a <= UAVG: reason = 'usefulness %.1f/5 over %d' % (a, n)
    if reason: print('%s\t%s' % (d, reason))
PYEOF
    weak="$(cat "$wf" 2>/dev/null)"
    if [ -z "$weak" ]; then ok "no weak skills (quality 1-2, or low usefulness). Assess first with --assess."; else
      local wn=0 wname wreason wdest
      while IFS="$(printf '\t')" read -r wname wreason; do
        [ -n "$wname" ] || continue
        if [ "$yes" -ne 1 ]; then info "  would archive: $wname ($wreason)"; continue; fi
        if wdest="$(archive_skill "$wname")"; then wn=$((wn+1)); ok "archived $wname ($wreason)"; fi
      done <<WEAK_EOF
$weak
WEAK_EOF
      if [ "$yes" -eq 1 ]; then skills_commit "cairn: archived $wn weak skill(s)"; ok "archived $wn weak skill(s) (recoverable in $ARCHIVE + git)"; fi
    fi
  fi

  rm -rf "$TMPD_C"
}

# =============================================================================
# subcommand: mine  (Layer A — past transcripts -> skill candidates)
# =============================================================================
EXTRACT_PROMPT='You are mining a single Claude Code session transcript (on stdin) for
REUSABLE skills. A skill is worth proposing only if the session shows a
non-trivial procedure, debugging pattern, or hard-won convention that would
plausibly recur. Ignore one-off trivia and project-specific details that will
not generalize.

Output ONLY JSON Lines: zero or more objects, one per line, no prose, no fences.
Each object:
{"name":"kebab-case-name","description":"what it does + concrete Use-when triggers (<=1024 chars)","evidence":"1-2 sentences why it is reusable","procedure":"terse step outline"}
If nothing is worth a skill, output nothing.'

AGG_PROMPT='You are given candidate skills as JSON Lines on stdin, mined from many
Claude Code sessions. Produce a Markdown review report that clusters near-
duplicates into one proposed skill each, ranks by how often the pattern recurred,
and for each gives a kebab-case name, a tight description with concrete Use-when
triggers, supporting session count, and a one-line procedure. Prefer a few
class-level umbrellas over many narrow siblings. End each with: /skill-new <name>
"<purpose>". Drop weak one-offs. Output Markdown only.'

cmd_mine() {
  need_python; need_claude
  local PROJECTS="$CLAUDE_DIR/projects"
  local ROOT="" ALL=0 SINCE=0 MAX=20 MODEL="$MODEL_DEFAULT" MAXCHARS=60000 MR=3
  local RETRY_FAILED=0 RESET=0 DRYR=0
  while [ $# -gt 0 ]; do case "$1" in
    --all) ALL=1 ;; --since) SINCE="${2:-0}"; shift ;;
    --max-sessions) MAX="${2:-20}"; shift ;; --model) MODEL="${2:-$MODEL_DEFAULT}"; shift ;;
    --max-chars) MAXCHARS="${2:-60000}"; shift ;; --max-retries) MR="${2:-3}"; shift ;;
    --retry-failed) RETRY_FAILED=1 ;; --dry-run) DRYR=1 ;; --reset) RESET=1 ;;
    --*) die "mine: unknown option $1" ;; *) ROOT="$1" ;;
  esac; shift; done
  [ -n "$ROOT" ] || ROOT="$PWD"
  [ -d "$PROJECTS" ] || die "no transcripts dir at $PROJECTS"
  local STAMPS="$HARVEST/.mined" CAND="$HARVEST/candidates.jsonl" PROP="$HARVEST/PROPOSALS.md" lf="$LOGS/mine.log"
  mkdir -p "$STAMPS" "$LOGS"
  [ "$RESET" -eq 1 ] && { rm -f "$STAMPS"/* 2>/dev/null || true; : > "$CAND"; }
  [ -f "$CAND" ] || : > "$CAND"

  local ROWS TOTAL SCOPE
  ROWS="$(py transcript discover "$PROJECTS" "$ROOT" "$ALL" "$SINCE" | head -n "$MAX")"
  TOTAL="$(printf '%s' "$ROWS" | grep -c . || true)"
  [ "$ALL" -eq 1 ] && SCOPE="ALL projects" || SCOPE="cwd under $ROOT"
  say "$lf" "scope: $SCOPE | since: ${SINCE}d | matched (cap $MAX): $TOTAL session(s)"
  [ "$TOTAL" -eq 0 ] && { echo "No matching transcripts. Try --all or a higher --since."; return 0; }

  if [ "$DRYR" -eq 1 ]; then
    printf '%-6s %-7s %s\n' "MSGS" "AGE(d)" "SESSION (cwd)"
    printf '%s\n' "$ROWS" | while IFS="$(printf '\t')" read -r f n age cwd; do printf '%-6s %-7s %s\n' "$n" "$age" "$cwd"; done
    local approx; approx="$(printf '%s\n' "$ROWS" | awk -F'\t' -v mc="$MAXCHARS" '{c=$2*400; if(c>mc)c=mc; s+=c} END{printf "%d", s/4}')"
    echo; echo "Rough input estimate: ~${approx} tokens across $TOTAL session(s). Dry run — nothing sent."
    return 0
  fi

  local TAB; TAB="$(printf '\t')"; local ROWFILE="$HARVEST/.rows.$$"
  printf '%s\n' "$ROWS" > "$ROWFILE"
  local HALTED=0 FAILED=0
  while IFS="$TAB" read -r f n age cwd; do
    [ -n "$f" ] || continue
    local base; base="$(basename "$f")"
    local done_s="$STAMPS/$base.done" fail_s="$STAMPS/$base.failed"
    if [ "$RESET" -ne 1 ]; then
      [ -f "$done_s" ] && { say "$lf" "skip (mined): $base"; continue; }
      [ -f "$fail_s" ] && [ "$RETRY_FAILED" -ne 1 ] && { say "$lf" "skip (failed; --retry-failed): $base"; continue; }
    fi
    [ "$RETRY_FAILED" -eq 1 ] && rm -f "$fail_s"
    local flat; flat="$(py transcript flatten-file "$f" "$MAXCHARS")"
    [ -z "$flat" ] && { say "$lf" "skip (empty): $base"; touch "$done_s"; continue; }
    say "$lf" "extracting: $base ($n msgs)"
    local inf="$HARVEST/.in.$$" outf="$HARVEST/.out.$$" errf="$HARVEST/.err.$$"
    printf '%s' "$flat" > "$inf"
    run_claude "$EXTRACT_PROMPT" "$MODEL" "$inf" "$outf" "$errf" "$MR" "$base" "$lf"
    local rc=$?
    if [ "$rc" -eq 1 ]; then say "$lf" "HALT: persistent transient error on $base — NOT marked done"; rm -f "$inf" "$outf" "$errf"; HALTED=1; break; fi
    if [ "$rc" -eq 2 ]; then FAILED=$((FAILED+1)); say "$lf" "FAILED (quarantined): $base"; touch "$fail_s"; rm -f "$inf" "$outf" "$errf"; continue; fi
    grep -E '^[[:space:]]*\{.*\}[[:space:]]*$' "$outf" >> "$CAND" || true
    rm -f "$inf" "$outf" "$errf"; touch "$done_s"
  done < "$ROWFILE"
  rm -f "$ROWFILE"
  [ "$FAILED" -gt 0 ] && say "$lf" "quarantined $FAILED session(s) (retry: --retry-failed)"
  [ "$HALTED" -eq 1 ] && { echo "Stopped early without losing progress — re-run to resume."; return 1; }

  local CN; CN="$(grep -c . "$CAND" 2>/dev/null)"; CN="${CN:-0}"   # grep -c already prints 0
  say "$lf" "candidates so far: $CN"
  [ "$CN" -eq 0 ] && { echo "No candidates emitted."; return 0; }
  say "$lf" "aggregating $CN candidate(s)"
  local af="$HARVEST/.agg.$$" ef="$HARVEST/.aggerr.$$"
  run_claude "$AGG_PROMPT" "$MODEL" "$CAND" "$af" "$ef" "$MR" "aggregate" "$lf"
  [ $? -ne 0 ] && { rm -f "$af" "$ef"; echo "Aggregation failed — candidates are safe; re-run to retry."; return 1; }
  { echo "# Skill proposals (mined $(date '+%Y-%m-%d %H:%M'))"; echo; echo "Scope: $SCOPE · candidates: $CN"; echo "Review, then scaffold with /skill-new. Nothing was written to skills/."; echo; cat "$af"; } > "$PROP"
  rm -f "$af" "$ef"
  ok "proposals: $PROP"
  info "next: 'cairn distill' (cluster) then 'cairn refine' (score), or scaffold directly with /skill-new"
}

# =============================================================================
# subcommand: distill  (Layer A — cluster candidates -> synthesized proposals)
# =============================================================================
SYN_PROMPT='These candidate skills (JSON on stdin) were mined from many sessions and
mechanically grouped because their triggers overlap. Synthesize ONE proposed
skill: a kebab-case name; a tight description (<=1024 chars) that is the UNION of
the distinct triggers, deduplicated, with concrete "Use when ..." phrasing (not a
concatenation); a short numbered procedure; and a final line "Supported by: N
candidate(s)". Begin with "### <name>". If the group is clearly NOT one coherent
skill, emit the best 1-2 distinct proposals. Output Markdown only, no fences.'

cmd_distill() {
  need_python; need_claude
  local IN="$HARVEST/candidates.jsonl"
  local THRESH=0.50 MINCL=2 MAXCL=60 MAXMEM=30 MODEL="$MODEL_DEFAULT" MR=3 RESET=0 DRYR=0
  while [ $# -gt 0 ]; do case "$1" in
    --threshold) THRESH="${2:-0.50}"; shift ;; --min-cluster) MINCL="${2:-2}"; shift ;;
    --max-clusters) MAXCL="${2:-60}"; shift ;; --max-members) MAXMEM="${2:-30}"; shift ;;
    --model) MODEL="${2:-$MODEL_DEFAULT}"; shift ;; --max-retries) MR="${2:-3}"; shift ;;
    --reset) RESET=1 ;; --dry-run) DRYR=1 ;;
    --*) die "distill: unknown option $1" ;; *) IN="$1" ;;
  esac; shift; done
  [ -f "$IN" ] || die "no candidates at $IN (run 'cairn mine' first)"
  local WORK="$HARVEST/distill" CL="$HARVEST/distill/clusters" PD="$HARVEST/distill/proposals" ST="$HARVEST/distill/.done" lf="$LOGS/distill.log"
  mkdir -p "$CL" "$PD" "$ST" "$LOGS"
  [ "$RESET" -eq 1 ] && rm -f "$ST"/* "$PD"/* "$CL"/* 2>/dev/null || true

  local SUMMARY; SUMMARY="$(py cluster candidates "$IN" "$THRESH" "$CL")"
  say "$lf" "$SUMMARY"
  local cf cnt; local eligible=()   # array, not a word-split string (paths may contain spaces)
  for cf in "$CL"/cluster_*.json; do
    [ -f "$cf" ] || continue
    cnt="$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$cf")"
    [ "$cnt" -ge "$MINCL" ] && eligible+=("$cf")
  done
  set -- ${eligible[@]+"${eligible[@]}"}; local ELN=$#
  if [ "$DRYR" -eq 1 ]; then
    echo "Eligible clusters (>= $MINCL): $ELN | would synthesize up to $MAXCL. Dry run — no model calls."
    return 0
  fi

  local done_n=0 fail_n=0 halted=0 i=0
  for cf in "$@"; do
    i=$((i+1)); [ "$i" -gt "$MAXCL" ] && { say "$lf" "reached --max-clusters $MAXCL; $((ELN-MAXCL)) left"; break; }
    local cid; cid="$(basename "$cf" .json)"
    [ -f "$ST/$cid.done" ] && [ "$RESET" -ne 1 ] && { say "$lf" "skip (done): $cid"; continue; }
    cnt="$(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))))" "$cf")"
    local feed; feed="$(python3 -c "import json,sys;d=json.load(open(sys.argv[1]));d=d[:int(sys.argv[2])];print('Total in group: %d (showing %d)'%(len(json.load(open(sys.argv[1]))),len(d)));[print(json.dumps(x,ensure_ascii=False)) for x in d]" "$cf" "$MAXMEM")"
    say "$lf" "synthesizing $cid ($cnt candidate(s))"
    local inf="$WORK/.in.$$" outf="$WORK/.out.$$" errf="$WORK/.err.$$"
    printf '%s' "$feed" > "$inf"
    run_claude "$SYN_PROMPT" "$MODEL" "$inf" "$outf" "$errf" "$MR" "$cid" "$lf"
    local rc=$?
    if [ "$rc" -eq 1 ]; then say "$lf" "HALT on $cid"; rm -f "$inf" "$outf" "$errf"; halted=1; break; fi
    if [ "$rc" -eq 2 ]; then fail_n=$((fail_n+1)); say "$lf" "FAILED (quarantined): $cid"; touch "$ST/$cid.failed"; rm -f "$inf" "$outf" "$errf"; continue; fi
    { printf '<!-- cluster %s, %s candidates -->\n' "$cid" "$cnt"; cat "$outf"; echo; } > "$PD/$cid.md"
    rm -f "$inf" "$outf" "$errf"; touch "$ST/$cid.done"; done_n=$((done_n+1))
  done
  [ "$halted" -eq 1 ] && { echo "Stopped early — re-run to resume."; return 1; }

  local PROP="$HARVEST/PROPOSALS.md"
  { echo "# Curated skill proposals (distilled $(date '+%Y-%m-%d %H:%M'))"; echo; echo "From $IN · $SUMMARY"; echo "Ordered by supporting evidence. Scaffold with /skill-new."; echo;
    local pf; for pf in $(ls "$PD"/*.md 2>/dev/null | sort); do cat "$pf"; echo; done; } > "$PROP"
  ok "proposals: $PROP (synthesized $done_n this run)"
  info "next: 'cairn refine' to generalize + reusability-score them"
}

# =============================================================================
# subcommand: refine  (Layer A — generalize + reusability-score proposals; G13)
# =============================================================================
REFINE_PROMPT='You are given several proposed Claude Code skills (Markdown, each starts
with "### name"). For EACH, judge how REUSABLE the underlying pattern is and
rewrite toward general, project-agnostic form WHERE HONEST.
Reusability: 5=broad cross-project; 4=within a stack/domain; 3=one setup but
parameterizable; 2=mostly specific; 1=hyper-specific one-off (not a skill).
Strip service names/hosts/incident IDs into general language; do NOT invent
generality — a genuine one-off stays specific and scores low.
Output for EACH, exactly:
### <kebab-name>
**Reusability: N/5** — <one-line rationale>
<generalized one-line description with concrete "Use when ..." triggers>
<short numbered procedure>
Separate proposals with a line containing only ---. Markdown only, no fences.'

cmd_refine() {
  need_python; need_claude
  local SRC="$HARVEST/distill/proposals"
  local BATCH=8 MINSCORE=3 MODEL="$MODEL_DEFAULT" MR=3 RESET=0 DRYR=0
  while [ $# -gt 0 ]; do case "$1" in
    --batch) BATCH="${2:-8}"; shift ;; --min-score) MINSCORE="${2:-3}"; shift ;;
    --model) MODEL="${2:-$MODEL_DEFAULT}"; shift ;; --max-retries) MR="${2:-3}"; shift ;;
    --reset) RESET=1 ;; --dry-run) DRYR=1 ;;
    --*) die "refine: unknown option $1" ;; *) SRC="$1" ;;
  esac; shift; done
  [ -d "$SRC" ] || die "no proposals dir at $SRC (run 'cairn distill' first)"
  local WORK="$HARVEST/refine" ITEMS="$HARVEST/refine/items" OUTD="$HARVEST/refine/out" ST="$HARVEST/refine/.done" lf="$LOGS/refine.log"
  local PROP="$HARVEST/PROPOSALS.md"
  mkdir -p "$ITEMS" "$OUTD" "$ST" "$WORK/batches" "$LOGS"
  [ "$RESET" -eq 1 ] && rm -f "$ST"/* "$OUTD"/* "$ITEMS"/* "$WORK/batches"/* 2>/dev/null || true

  python3 - "$SRC" "$ITEMS" <<'PYEOF'
import sys,os,re,glob
SRC,ITEMS=sys.argv[1],sys.argv[2]
for f in glob.glob(os.path.join(ITEMS,'item_*.md')): os.remove(f)
idx=0
for pf in sorted(glob.glob(os.path.join(SRC,'*.md'))):
    for p in re.split(r'(?m)^(?=### )', open(pf,errors='replace').read()):
        if '### ' in p and p.strip():
            open(os.path.join(ITEMS,'item_%04d.md'%idx),'w').write(p.strip()+'\n'); idx+=1
print(idx)
PYEOF
  local NITEMS; NITEMS="$(ls "$ITEMS"/item_*.md 2>/dev/null | wc -l | tr -d ' ')"
  local NB=$(( (NITEMS + BATCH - 1) / BATCH ))
  say "$lf" "split into $NITEMS proposal item(s) -> $NB batch(es) of $BATCH"
  [ "$NITEMS" -eq 0 ] && { echo "No proposals to refine."; return 0; }
  [ "$DRYR" -eq 1 ] && { echo "Would make $NB AI call(s). Dry run."; return 0; }

  python3 - "$ITEMS" "$WORK" "$BATCH" <<'PYEOF'
import sys,os,glob
ITEMS,WORK,BATCH=sys.argv[1],sys.argv[2],int(sys.argv[3])
items=sorted(glob.glob(os.path.join(ITEMS,'item_*.md')))
bd=os.path.join(WORK,'batches')
for f in glob.glob(os.path.join(bd,'batch_*.md')): os.remove(f)
b=0
for i in range(0,len(items),BATCH):
    with open(os.path.join(bd,'batch_%04d.md'%b),'w') as out:
        for it in items[i:i+BATCH]: out.write(open(it,errors='replace').read().rstrip()+"\n\n")
    b+=1
PYEOF

  local done_n=0 halted=0 bf bid
  for bf in "$WORK"/batches/batch_*.md; do
    [ -f "$bf" ] || continue
    bid="$(basename "$bf" .md)"
    [ -f "$ST/$bid.done" ] && [ "$RESET" -ne 1 ] && { say "$lf" "skip (done): $bid"; continue; }
    say "$lf" "refining $bid"
    local outf="$WORK/.out.$$" errf="$WORK/.err.$$"
    run_claude "$REFINE_PROMPT" "$MODEL" "$bf" "$outf" "$errf" "$MR" "$bid" "$lf"
    local rc=$?
    if [ "$rc" -eq 1 ]; then say "$lf" "HALT on $bid"; rm -f "$outf" "$errf"; halted=1; break; fi
    if [ "$rc" -eq 2 ]; then say "$lf" "FAILED (quarantined): $bid"; touch "$ST/$bid.failed"; rm -f "$outf" "$errf"; continue; fi
    mv "$outf" "$OUTD/$bid.md"; rm -f "$errf"; touch "$ST/$bid.done"; done_n=$((done_n+1))
  done
  [ "$halted" -eq 1 ] && { echo "Stopped early — re-run to resume."; return 1; }

  [ -f "$PROP" ] && cp "$PROP" "$PROP.bak-$(ts)"
  python3 - "$OUTD" "$MINSCORE" "$PROP" "$SRC" <<'PYEOF'
import sys,os,re,glob,datetime
OUTD,MINSCORE,OUT,SRC=sys.argv[1],int(sys.argv[2]),sys.argv[3],sys.argv[4]
props=[]
for of in sorted(glob.glob(os.path.join(OUTD,'*.md'))):
    for chunk in re.split(r'(?m)^---\s*$', open(of,errors='replace').read()):
        chunk=chunk.strip()
        if not chunk.startswith('### '): continue
        m=re.search(r'Reusability:\s*([1-5])',chunk); props.append((int(m.group(1)) if m else 3, chunk))
props=[c for _,(s,c) in sorted(enumerate(props),key=lambda x:(-x[1][0],x[0]))]
def sc(c): return int(re.search(r'Reusability:\s*([1-5])',c).group(1))
def emit(g): return "\n\n".join(g) if g else "_None._"
hi=[c for c in props if sc(c)>=4]; mid=[c for c in props if sc(c)==3]; lo=[c for c in props if sc(c)<=2]
o=["# Refined skill proposals (%s)"%datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),"",
   "%d proposal(s), generalized and reusability-scored. Source: %s. Scaffold with /skill-new."%(len(props),SRC),"",
   "## Highly reusable (4-5) — start here","",emit(hi),"",
   "## Reusable with parameterization (3)","",emit(mid),"",
   "## Specific — probably skip (1-2)","These look tied to one service/incident/config.","",emit(lo),""]
open(OUT,'w').write("\n".join(o)+"\n")
print("high=%d mid=%d low=%d"%(len(hi),len(mid),len(lo)))
PYEOF
  ok "refined proposals: $PROP (refined $done_n batch(es); highly-reusable at top)"
}

# =============================================================================
# subcommand: improve  (Layer B — eval -> fix -> re-eval picker + loop)
# =============================================================================
IMPROVE_PROMPT='You are running ONE autonomous iteration of a skill-improvement loop in the
current directory (a skill: SKILL.md, learnings.md, usage.md, evals/cases.md,
evals/runs.md). No user is present — ask nothing, make conservative choices.
1. Read evals/runs.md first; do not repeat edits a prior iteration rolled back.
2. Execute every case in evals/cases.md by following SKILL.md literally.
3. Grade each against its pass criteria; compute the pass rate.
4. Analyze failures: triggering (description), procedure gap (body), or missing
   knowledge (learnings/references).
5. Apply MINIMAL targeted edits to SKILL.md (and learnings.md if apt). Never
   rewrite wholesale; re-read before editing; keep frontmatter valid; preserve
   the learnings-loop sections.
6. Re-run the previously failing cases; compute the new pass rate.
7. Append to evals/runs.md: date, pass rate before -> after, edits (one line
   each), open issues. If the case set is too weak to grade, improve
   evals/cases.md instead and say so in runs.md.'

improve_one() { # improve_one <skill-dir> <iterations> <model>
  local d="$1" iters="$2" model="$3" name; name="$(basename "$d")"
  case "$iters" in ''|*[!0-9]*) iters=1 ;; esac; [ "$iters" -ge 1 ] || iters=1  # never count down (BSD seq)
  local i rc
  for i in $(seq 1 "$iters"); do
    say "$LOGS/improve.log" "improving $name iteration $i/$iters (model $model)"
    ( cd "$d" && CAIRN_REVIEW_HOOK=1 claude -p "$IMPROVE_PROMPT" --model "$model" \
        --max-turns 50 --permission-mode acceptEdits \
        --allowedTools "Read,Edit,Write,Glob,Grep" ) >> "$LOGS/improve.log" 2>&1
    rc=$?
    [ "$rc" -ne 0 ] && { say "$LOGS/improve.log" "iteration $i failed (rc=$rc) on $name"; return 1; }
  done
  py meta set "$d/.meta" last_patched "$(today)" 2>/dev/null || true
  touch "$d/evals/.last-improve"
  return 0
}

cmd_improve() {
  need_python
  local MAX="${CAIRN_IMPROVE_MAX:-2}" ITER="${CAIRN_IMPROVE_ITERATIONS:-1}" MODEL="$MODEL_DEFAULT"
  local ONE="" DRYR=0 BATT_SKIP=0
  while [ $# -gt 0 ]; do case "$1" in
    --max) MAX="${2:-2}"; shift ;; --iterations) ITER="${2:-1}"; shift ;;
    --model) MODEL="${2:-$MODEL_DEFAULT}"; shift ;; --dry-run) DRYR=1 ;;
    --battery-skip) BATT_SKIP=1 ;;
    --*) die "improve: unknown option $1" ;; *) ONE="$1" ;;
  esac; shift; done
  [ -d "$SKILLS" ] || die "no skills dir at $SKILLS"
  mkdir -p "$LOGS"

  if [ "$BATT_SKIP" -eq 1 ] && command -v pmset >/dev/null 2>&1; then
    pmset -g batt 2>/dev/null | grep -q "Battery Power" && { ok "on battery — skipping (--battery-skip)"; return 0; }
  fi

  # explicit single skill
  if [ -n "$ONE" ]; then
    local d; d="$(resolve_skill_dir "$ONE")" || die "no skill '$ONE'"
    local nc; nc="$(grep -c '^## Case' "$d/evals/cases.md" 2>/dev/null)"; [ "${nc:-0}" -ge 5 ] || die "$ONE has <5 eval cases — write more first (/skill-improve helps)"
    [ "$DRYR" -eq 1 ] && { ok "would improve $ONE ($ITER iteration(s), model $MODEL)"; return 0; }
    need_claude; improve_one "$d" "$ITER" "$MODEL" && { skills_commit "cairn: improve $ONE"; ok "improved $ONE"; } || warn "improve $ONE ended with errors (see $LOGS/improve.log)"
    return 0
  fi

  # pick READY skills: >=5 cases AND fresh signal since last improve; worst first
  local CAND cf2; cf2="$(mktemp)"   # heredoc to a file, not inside $() (bash 3.2)
  python3 - "$SKILLS" "$MAX" > "$cf2" 2>/dev/null <<'PYEOF'
import sys,os,re,glob
SKILLS,MAX=sys.argv[1],int(sys.argv[2])
def mt(p):
    try: return os.path.getmtime(p)
    except OSError: return 0.0
def usage_avg(p):
    if not os.path.isfile(p): return None
    sc=[]
    for line in open(p,errors='replace'):
        m=re.match(r'\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5',line)
        if m: sc.append(int(m.group(1)))
    return (sum(sc)/len(sc)) if sc else None
def meta_get(d,k):
    p=os.path.join(d,'.meta')
    if os.path.isfile(p):
        for line in open(p,errors='replace'):
            if line.strip().startswith(k+'='): return line.split('=',1)[1].strip()
    return ''
rows=[]
for d in sorted(glob.glob(os.path.join(SKILLS,'*'))):
    name=os.path.basename(d)
    if name=='skill-extraction' or not os.path.isdir(d): continue
    sk,lr,cs=(os.path.join(d,f) for f in ('SKILL.md','learnings.md','evals/cases.md'))
    if not (os.path.isfile(sk) and os.path.isfile(cs)): continue
    try: cases=sum(1 for l in open(cs,errors='replace') if l.startswith('## Case'))
    except OSError: cases=0
    if cases<5: continue
    if meta_get(d,'state')=='archived': continue
    stamp=os.path.join(d,'evals/.last-improve'); st=mt(stamp)
    newest=max(mt(lr), mt(os.path.join(d,'usage.md')))
    if st and newest<=st: continue   # already improved since latest signal
    q=meta_get(d,'quality')
    qk=int(q) if q.isdigit() else 9
    avg=usage_avg(os.path.join(d,'usage.md'))
    ak=avg if avg is not None else 9.9
    rows.append((qk, ak, -newest, name))
rows.sort()
for r in rows[:MAX]: print(r[3])
PYEOF
  CAND="$(cat "$cf2")"; rm -f "$cf2"
  [ -z "$CAND" ] && { ok "nothing to improve (no skill with >=5 cases + fresh signal)"; return 0; }
  if [ "$DRYR" -eq 1 ]; then ok "would improve: $(echo "$CAND" | tr '\n' ' ')"; return 0; fi
  need_claude
  local name n=0
  for name in $CAND; do
    if improve_one "$SKILLS/$name" "$ITER" "$MODEL"; then n=$((n+1)); ok "improved $name"; else warn "FAILED $name (continuing)"; fi
  done
  skills_commit "cairn: improve ($n skill(s))"
  ok "improve run complete ($n skill(s))"
}

# =============================================================================
# subcommand: status  (health dashboard)
# =============================================================================
cmd_status() {
  need_python
  hdr "cairn status — $(date '+%Y-%m-%d %H:%M')  (v$CAIRN_VERSION)"
  if [ -d "$SKILLS" ]; then
    python3 - "$SKILLS" "$(today)" "$STALE_DAYS" "$ARCHIVE_DAYS" <<'PYEOF'
import sys,os,re,glob,datetime
SKILLS,today,STALE,ARCH=sys.argv[1],sys.argv[2],int(sys.argv[3]),int(sys.argv[4])
def meta_get(d,k):
    p=os.path.join(d,'.meta')
    if os.path.isfile(p):
        for line in open(p,errors='replace'):
            if line.strip().startswith(k+'='): return line.split('=',1)[1].strip()
    return ''
def usage(d):
    p=os.path.join(d,'usage.md'); sc=[]
    if os.path.isfile(p):
        for l in open(p,errors='replace'):
            m=re.match(r'\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5',l)
            if m: sc.append(int(m.group(1)))
    return sc
def cases(d):
    p=os.path.join(d,'evals/cases.md')
    return sum(1 for l in open(p,errors='replace') if l.startswith('## Case')) if os.path.isfile(p) else 0
def learns(d):
    p=os.path.join(d,'learnings.md'); n=0
    if os.path.isfile(p):
        for l in open(p,errors='replace'):
            s=l.strip()
            if s and not s.startswith('<!--') and (s.startswith('-') or re.match(r'^\d{4}-\d{2}-\d{2}',s)): n+=1
    return n
dirs=[d for d in sorted(glob.glob(os.path.join(SKILLS,'*'))) if os.path.isfile(os.path.join(d,'SKILL.md')) and os.path.basename(d)!='skill-extraction']
total=len(dirs)
prov={}; state={}; quals=[]
improvable=0; rated=[]; never=0; biglearn=[]
for d in dirs:
    prov[meta_get(d,'provenance') or '(none)']=prov.get(meta_get(d,'provenance') or '(none)',0)+1
    state[meta_get(d,'state') or '(none)']=state.get(meta_get(d,'state') or '(none)',0)+1
    q=meta_get(d,'quality')
    if q.isdigit(): quals.append(int(q))
    if cases(d)>=5: improvable+=1
    sc=usage(d)
    if sc: rated.append((os.path.basename(d), sum(sc)/len(sc), len(sc)))
    else: never+=1
    if learns(d)>=15: biglearn.append(os.path.basename(d))
print("Skills:            %d"%total)
print("  by provenance:   "+", ".join("%s=%d"%(k,v) for k,v in sorted(prov.items())))
print("  by state:        "+", ".join("%s=%d"%(k,v) for k,v in sorted(state.items())))
if quals: print("  quality scored:  %d (avg %.1f/5, %d unscored)"%(len(quals),sum(quals)/len(quals),total-len(quals)))
print("  improvable (>=5 eval cases): %d"%improvable)
print("  never rated:     %d"%never)
if rated:
    overall=sum(a for _,a,_ in rated)/len(rated); print("  avg usefulness:  %.1f/5 (%d rated)"%(overall,len(rated)))
    low=sorted([(n,a,c) for n,a,c in rated if c>=3 and a<=2.5],key=lambda x:x[1])
    if low:
        print("  LOW usefulness (<=2.5, >=3 uses): %d  -> cairn improve / /skill-improve"%len(low))
        for n,a,c in low[:5]: print("      %s: %.1f/5 over %d"%(n,a,c))
if biglearn: print("  fold candidates (>=15 learnings): %d  -> /skill-fold"%len(biglearn))
PYEOF
    # lifecycle proposals
    local life; life="$(py lifecycle propose "$SKILLS" "$(today)" "$STALE_DAYS" "$ARCHIVE_DAYS" 2>/dev/null)"
    if [ -n "$life" ]; then
      local nstale narch
      nstale="$(printf '%s\n' "$life" | awk -F'\t' '$3=="stale"' | grep -c . || true)"
      narch="$(printf '%s\n' "$life" | awk -F'\t' '$3=="archived"' | grep -c . || true)"
      info "  lifecycle ready: $nstale -> stale, $narch -> archived  (cairn curate --apply-lifecycle)"
    fi
    local inv; inv="$(py validate all "$SKILLS" 2>/dev/null | wc -l | tr -d ' ')"
    [ "${inv:-0}" != "0" ] && info "  frontmatter issues: $inv  -> cairn lint"
  else
    info "Skills:            (none — $SKILLS missing; run cairn install)"
  fi
  printf '%s\n' "------------------------------------------------"
  # memory
  if [ -f "$USER_MD" ] || [ -f "$MEMORY_MD" ]; then
    info "Memory: USER.md $([ -f "$USER_MD" ] && py memory chars "$USER_MD" || echo 0)/$USER_CAP · MEMORY.md $([ -f "$MEMORY_MD" ] && py memory chars "$MEMORY_MD" || echo 0)/$MEMORY_CAP"
  fi
  # harvest
  local cand="$HARVEST/candidates.jsonl" prop="$HARVEST/PROPOSALS.md"
  [ -f "$cand" ] && info "Mined candidates:  $(grep -c . "$cand" 2>/dev/null)" || info "Mined candidates:  none (cairn mine)"
  [ -f "$prop" ] && info "Proposals:         $prop ($(grep -c '^### ' "$prop" 2>/dev/null) headers)" || info "Proposals:         none (cairn distill / refine)"
  [ -f "$HARVEST/CURATE.md" ] && info "Curate report:     $HARVEST/CURATE.md"
  # hook
  if [ -f "$CLAUDE_DIR/settings.json" ] && grep -q 'cairn.*review' "$CLAUDE_DIR/settings.json" 2>/dev/null; then
    info "SessionEnd hook:   on"
  else
    info "SessionEnd hook:   off (enable: cairn install --enable-hooks)"
  fi
  printf '%s\n' "================================================"
  info "tip: 'cairn curate' for merge/fold/lifecycle detail; 'cairn provenance --list' for the catalog."
}

# =============================================================================
# subcommand: maintain  (the nightly job — gentle, recoverable, no auto-merge)
# =============================================================================
cmd_maintain() {
  mkd "$LOGS"
  local lf="$LOGS/maintain.log" bin="$SELF_DIR/cairn"
  # launchd/cron start with a minimal PATH — make claude findable
  PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
  MAINTAIN_LOCK="$STATE/.maintain.lock"   # global so the EXIT trap can see it
  mkd "$STATE"
  if ! mkdir "$MAINTAIN_LOCK" 2>/dev/null; then
    # reclaim a stale lock left by a killed/OOM/power-lost run (>6h old), so an
    # unattended nightly job can never wedge itself permanently.
    local lmt now lage
    lmt="$(stat -c %Y "$MAINTAIN_LOCK" 2>/dev/null || stat -f %m "$MAINTAIN_LOCK" 2>/dev/null || echo 0)"
    now="$(date +%s)"; lage=$(( now - ${lmt:-0} ))
    if [ "${lmt:-0}" -gt 0 ] && [ "$lage" -gt 21600 ]; then
      say "$lf" "reclaiming stale lock (${lage}s old)"
      rmdir "$MAINTAIN_LOCK" 2>/dev/null || true
      mkdir "$MAINTAIN_LOCK" 2>/dev/null || { say "$lf" "SKIP: could not reclaim lock"; return 0; }
    else
      say "$lf" "SKIP: another maintain run holds $MAINTAIN_LOCK"; return 0
    fi
  fi
  trap 'rmdir "${MAINTAIN_LOCK:-}" 2>/dev/null || true' EXIT
  say "$lf" "maintain: start"
  # 1. improve skills with fresh signal (model calls; non-fatal). Runs regardless
  #    of power state — pass --battery-skip here to restore battery-aware skipping.
  #    improve_one already exports CAIRN_REVIEW_HOOK so its claude -p never
  #    re-triggers the SessionEnd review hook.
  if command -v claude >/dev/null 2>&1; then
    "$bin" improve >> "$lf" 2>&1 || say "$lf" "improve ended with errors (continuing)"
  else
    say "$lf" "improve skipped (claude not on PATH)"
  fi
  # 2. inactivity lifecycle — gentle, no model calls, recoverable. NEVER auto-
  #    merge or quality-archive here; those stay manual (cairn curate --merge / --archive-weak).
  "$bin" curate --apply-lifecycle >> "$lf" 2>&1 || say "$lf" "curate ended with errors"
  say "$lf" "maintain: done"
  ok "maintenance complete (log: $lf)"
}

# =============================================================================
# subcommand: schedule  (wire `cairn maintain` to run nightly; reversible)
# =============================================================================
SCHED_LABEL="com.cairn.maintain"
SCHED_PLIST="$HOME/Library/LaunchAgents/$SCHED_LABEL.plist"
SCHED_CRON_MARK="# cairn maintain"

sched_status() {
  if [ "$(uname)" = "Darwin" ] && [ -f "$SCHED_PLIST" ]; then echo "on (launchd)"; return; fi
  if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -qF "$SCHED_CRON_MARK"; then echo "on (cron)"; return; fi
  echo "off"
}

sched_enable() {
  local t="$1" h m bin="$STATE/bin/cairn"
  [ -x "$bin" ] || die "run 'cairn install' first (no dispatcher at $bin)"
  h=$((10#${t%%:*})); m=$((10#${t##*:}))
  mkd "$LOGS"
  if [ "$(uname)" = "Darwin" ]; then
    mkd "$HOME/Library/LaunchAgents"
    cat > "$SCHED_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$SCHED_LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$bin</string><string>maintain</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$h</integer><key>Minute</key><integer>$m</integer></dict>
  <key>StandardOutPath</key><string>$LOGS/maintain.launchd.log</string>
  <key>StandardErrorPath</key><string>$LOGS/maintain.launchd.log</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
PLIST
    if command -v launchctl >/dev/null 2>&1; then
      launchctl bootout "gui/$(id -u)/$SCHED_LABEL" >/dev/null 2>&1 || true
      launchctl bootstrap "gui/$(id -u)" "$SCHED_PLIST" >/dev/null 2>&1 \
        || launchctl load -w "$SCHED_PLIST" >/dev/null 2>&1 || true
    fi
    ok "nightly maintenance scheduled at $t (launchd: $SCHED_PLIST)"
  else
    if ! command -v crontab >/dev/null 2>&1; then warn "crontab not found — schedule '$bin maintain' yourself"; return 0; fi
    ( crontab -l 2>/dev/null | grep -vF "$SCHED_CRON_MARK" || true; \
      echo "$m $h * * * \"$bin\" maintain >> \"$LOGS/maintain.log\" 2>&1 $SCHED_CRON_MARK" ) | crontab -
    ok "nightly maintenance scheduled at $t (cron)"
  fi
  info "runs: cairn maintain = improve (model calls) + curate --apply-lifecycle (gentle). Disable: cairn schedule --off"
}

sched_disable() {
  local removed=0
  if [ "$(uname)" = "Darwin" ] && [ -f "$SCHED_PLIST" ]; then
    command -v launchctl >/dev/null 2>&1 && launchctl bootout "gui/$(id -u)/$SCHED_LABEL" >/dev/null 2>&1 || true
    rm -f "$SCHED_PLIST"; removed=1
  fi
  if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -qF "$SCHED_CRON_MARK"; then
    ( crontab -l 2>/dev/null | grep -vF "$SCHED_CRON_MARK" || true ) | crontab -; removed=1
  fi
  [ "$removed" -eq 1 ] && ok "nightly maintenance schedule removed" || ok "no maintenance schedule was set"
}

cmd_schedule() {
  case "${1:-}" in
    ""|--status|status)
      info "nightly maintenance: $(sched_status)"
      [ "$(sched_status)" != "off" ] && info "  runs cairn maintain (improve + curate --apply-lifecycle); disable: cairn schedule --off"
      return 0 ;;
    --off|off|--disable) sched_disable ;;
    [01][0-9]:[0-5][0-9]|2[0-3]:[0-5][0-9]|[0-9]:[0-5][0-9]) sched_enable "$1" ;;
    *) die "usage: cairn schedule HH:MM  |  --off  |  --status   (pass a time to enable, e.g. 03:30)" ;;
  esac
}

# =============================================================================
# subcommand: test  (G12 — static + unit + integration, all offline)
# =============================================================================
cmd_test() {
  local runner="$CAIRN_HOME/tests/run-tests.sh"
  [ -f "$runner" ] || runner="$STATE/tests/run-tests.sh"
  [ -f "$runner" ] || die "test runner not found (run from the repo, or reinstall)"
  CAIRN_BIN="$SELF_DIR/cairn" CAIRN_REPO="$CAIRN_HOME" bash "$runner" "$@"
}

# =============================================================================
# subcommand: lint  (programmatic frontmatter + description-cap validation)
# =============================================================================
cmd_lint() {
  need_python
  [ -d "$SKILLS" ] || die "no skills dir at $SKILLS"
  local out
  if [ -n "${1:-}" ]; then
    local d; d="$(resolve_skill_dir "$1")" || die "no skill '$1'"
    out="$(py validate skill "$d")"
    [ -z "$out" ] && { ok "$1: frontmatter valid"; return 0; }
    warn "$1: invalid frontmatter:"; printf '%s\n' "$out" | sed 's/^/      /'; return 1
  fi
  out="$(py validate all "$SKILLS")"
  [ -z "$out" ] && { ok "all skills: frontmatter valid (name, description ≤1024, body)"; return 0; }
  warn "frontmatter issues (name / description ≤1024 / body):"; printf '%s\n' "$out" | sed 's/^/      /'; return 1
}

# =============================================================================
# subcommand: suggest  (use-side surfacing — match a prompt to relevant skills)
# =============================================================================
cmd_suggest() {
  need_python
  [ -d "$SKILLS" ] || return 0
  local mode="manual" prompt=""
  case "${1:-}" in
    --hook) mode=hook ;;     # UserPromptSubmit: surface at task start
    --tick) mode=tick ;;     # PostToolUse: re-surface every Nth tool call mid-task
    "")     return 0 ;;
    *)      prompt="$*" ;;
  esac

  if [ "$mode" = "hook" ]; then
    prompt="$(python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("prompt",""))
except Exception: print("")' 2>/dev/null)"
  elif [ "$mode" = "tick" ]; then
    local N="${CAIRN_SUGGEST_TICK:-8}"
    case "$N" in ''|*[!0-9]*) return 0 ;; esac
    [ "$N" -gt 0 ] || return 0
    local meta sid tp; meta="$(python3 -c 'import json,sys
try:
  d=json.load(sys.stdin); print((d.get("session_id","") or "s")+"\t"+(d.get("transcript_path","") or ""))
except Exception: print("s\t")' 2>/dev/null)"
    sid="$(printf '%s' "$meta" | cut -f1 | tr -dc 'A-Za-z0-9_-')"; sid="${sid:-s}"
    tp="$(printf '%s' "$meta" | cut -f2-)"
    [ -n "$tp" ] && [ -f "$tp" ] || return 0
    mkd "$STATE"
    local cf="$STATE/.suggest-tick-$sid" cnt
    cnt="$(cat "$cf" 2>/dev/null)"; cnt=$(( ${cnt:-0} + 1 )); printf '%s' "$cnt" > "$cf"
    [ $(( cnt % N )) -eq 0 ] || return 0   # only every Nth tool call
    prompt="$(py transcript last-user "$tp" 2>/dev/null)"
  fi
  [ -n "$prompt" ] || return 0

  local plat; case "$(uname)" in Darwin) plat=macos ;; Linux) plat=linux ;; *) plat="" ;; esac
  local matches; matches="$(printf '%s' "$prompt" | py suggest "$SKILLS" "${CAIRN_SUGGEST_TOPK:-3}" "$plat" 2>/dev/null)"
  [ -n "$matches" ] || return 0   # silent when nothing scores high enough

  # names-only safety net: no strong match, but the prompt was topically warm, so
  # suggest emitted the full skill roster (near-misses first) instead of matches.
  # A softer nudge than a real match — these are guesses, not hits.
  case "$matches" in
    @@ROSTER@@*)
      [ "$mode" = "tick" ] && return 0   # don't dump a roster mid-task
      local rextra rnames
      rextra="$(printf '%s' "$matches" | cut -f2)"
      rnames="$(printf '%s' "$matches" | cut -f3-)"
      printf 'Skill check — no installed skill matched this request strongly, but you may have one for it. If a name below fits, load it via the Skill tool (nearest by keyword first); otherwise proceed normally:\n  %s\n' "$rnames"
      case "$rextra" in ''|*[!0-9]*|0) : ;; *) printf '  (+%s more — refine wording or run: cairn suggest "<keywords>")\n' "$rextra" ;; esac
      return 0
      ;;
  esac

  local block; block="$(printf '%s\n' "$matches" | while IFS="$(printf '\t')" read -r n sc d; do
    [ -n "$n" ] && printf '  - %s — %s\n' "$n" "$d"; done)"

  if [ "$mode" = "tick" ]; then
    # PostToolUse: inject as additionalContext (a still-relevant reminder mid-task)
    python3 - "$block" <<'PYEOF'
import json, sys
ctx = ("Skill check (still relevant mid-task) — if you have not yet, invoke the "
       "fitting skill via the Skill tool, or note why it does not apply:\n" + sys.argv[1])
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}}))
PYEOF
  else
    printf 'Skill check — installed skills matching this request. Invoke the fitting one via the Skill tool BEFORE improvising, or say why it does not apply:\n%s\n' "$block"
  fi
}

# =============================================================================
# subcommand: track  (real activation telemetry — PostToolUse on the Skill tool)
# =============================================================================
cmd_track() {
  need_python
  [ -d "$SKILLS" ] || return 0
  [ "${1:-}" = "--hook" ] || { warn "cairn track is a PostToolUse hook (use --hook)"; return 0; }
  # PostToolUse JSON on stdin; find the tool_input value that names one of OUR
  # skills (defensive about the exact field name + plugin:skill / a/b forms).
  # NOTE: pass the JSON as an argv — the heredoc is python's stdin (the program),
  # so the JSON can't also come via stdin.
  local j tf name; j="$(cat)"; tf="$(mktemp)"
  python3 - "$SKILLS" "$j" > "$tf" 2>/dev/null <<'PYEOF'
import json, sys, os
skills = sys.argv[1]
try:
    d = json.loads(sys.argv[2])
except Exception:
    sys.exit(0)
vals = []
def collect(x):
    if isinstance(x, str): vals.append(x)
    elif isinstance(x, dict):
        for v in x.values(): collect(v)
    elif isinstance(x, list):
        for v in x: collect(v)
collect(d.get("tool_input") or {})
for v in vals:
    for cand in (v, v.split(":")[-1], v.split("/")[-1]):
        if cand and os.path.isfile(os.path.join(skills, cand, "SKILL.md")):
            sys.stdout.write(cand); sys.exit(0)
PYEOF
  name="$(cat "$tf" 2>/dev/null)"; rm -f "$tf"
  [ -n "$name" ] || return 0
  py meta init "$SKILLS/$name/.meta" created="$(today)" last_used="$(today)" 2>/dev/null || true
  py meta set  "$SKILLS/$name/.meta" last_used "$(today)" 2>/dev/null || true
  py meta bump "$SKILLS/$name/.meta" use_count 2>/dev/null || true
}

# =============================================================================
# router
# =============================================================================
main() {
  local sub="${1:-}"
  case "$sub" in
    ""|banner)        banner ;;
    -h|--help|help)   show_help ;;
    -V|--version|version) printf 'cairn %s\n' "$CAIRN_VERSION" ;;
    memory)      shift; cmd_memory "$@" ;;
    pin)         shift; cmd_pin "$@" ;;
    unpin)       shift; cmd_unpin "$@" ;;
    provenance)  shift; cmd_provenance "$@" ;;
    status)      shift; cmd_status "$@" ;;
    lint)        shift; cmd_lint "$@" ;;
    suggest)     shift; cmd_suggest "$@" ;;
    track)       shift; cmd_track "$@" ;;
    install)     shift; cmd_install "$@" ;;
    migrate)     shift; cmd_migrate "$@" ;;
    uninstall)   shift; cmd_uninstall "$@" ;;
    review)      shift; cmd_review "$@" ;;
    curate)      shift; cmd_curate "$@" ;;
    improve)     shift; cmd_improve "$@" ;;
    maintain)    shift; cmd_maintain "$@" ;;
    schedule)    shift; cmd_schedule "$@" ;;
    mine)        shift; cmd_mine "$@" ;;
    distill)     shift; cmd_distill "$@" ;;
    refine)      shift; cmd_refine "$@" ;;
    test)        shift; cmd_test "$@" ;;
    *) die "unknown command: $sub (try 'cairn --help')" ;;
  esac
}

# Subcommands defined in the sourced sections below; if a build is incomplete,
# fail loudly rather than silently.
for _fn in cmd_status cmd_install cmd_migrate cmd_uninstall cmd_review \
           cmd_curate cmd_improve cmd_mine cmd_distill cmd_refine cmd_test; do
  if ! declare -f "$_fn" >/dev/null 2>&1; then
    eval "$_fn() { die \"'${_fn#cmd_}' is not available in this build\"; }"
  fi
done

main "$@"
