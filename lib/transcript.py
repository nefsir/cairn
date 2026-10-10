#!/usr/bin/env python3
# =============================================================================
# transcript.py — discover and flatten Claude Code session transcripts.
#
# Claude Code stores sessions as JSONL under ~/.claude/projects/**/*.jsonl.
# Cairn reads them in two places: the backfill miner (many sessions) and the
# review loop (one session). This helper does the parsing, and does best-effort
# SECRET REDACTION before any text would be sent to `claude -p`.
#
# Redaction is best-effort (key=value secrets + long opaque tokens). Review the
# mining scope before running over shared repos.
#
# Usage:
#   transcript.py discover <projects_dir> <root> <allflag> <since_days>
#       Print  path<TAB>msgcount<TAB>age_days<TAB>cwd  for matching sessions,
#       newest first. allflag=1 ignores root; since_days=0 means no age filter.
#   transcript.py flatten <projects_dir> <path> <maxchars>
#       Print the flattened, redacted text of one session (USER:/ASSISTANT:).
#   transcript.py flatten-file <path> <maxchars> [from_user]
#       Same, but takes an absolute transcript path directly (review loop).
#       Over maxchars keeps head (1/3) + tail (2/3). from_user=N skips the
#       first N user messages (resumed session) and adds a context header.
#   transcript.py classify <path> <min_user>
#       Print  verdict<TAB>user_msgs ; verdict is review | skip:sdk |
#       skip:short | skip:missing | skip:unreadable.
#   transcript.py count-user <path>
#       Print the number of human-typed user messages.
# =============================================================================
import sys
import os
import re
import json
import glob
import time

# Redaction is layered and order-sensitive: structured/multi-line blocks first,
# then key=value (quote/JSON/YAML/env tolerant), CLI flags, URL credentials,
# known provider token shapes, and finally long opaque blobs. Best-effort by
# design — it over-redacts rather than risk leaking. See header note.
_PEM = re.compile(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*-----', re.S)
# a key whose name CONTAINS a sensitive word, then : or = , then the value —
# tolerant of surrounding quotes (JSON/YAML), env vars (AWS_SECRET_ACCESS_KEY),
# and bare assignments. The value stops at the next quote/comma/brace/space.
_KV = re.compile(
    r'(?i)(["\']?[\w.\-]*(?:api[_-]?key|secret|token|password|passwd|pass'
    r'|auth|bearer|access[_-]?key|client[_-]?secret|credential)[\w.\-]*["\']?'
    r'\s*[:=]\s*["\']?)([^\s"\',;}]+)')
# CLI flag forms: --password foo / --token=foo
_CLI = re.compile(r'(?i)(--(?:password|token|secret|api[_-]?key|access[_-]?key)[ =])(\S+)')
# scheme://user:password@host -> redact only the password segment
_URLCRED = re.compile(r'([a-zA-Z][a-zA-Z0-9+.\-]*://[^/\s:@]+:)([^/\s:@]+)(@)')
# auth scheme keyword followed by a credential (the token survives _KV because
# its value-capture stops at the space after the scheme word)
_SCHEME = re.compile(r'(?i)\b(bearer|token|basic|negotiate)\s+([A-Za-z0-9._\-+/=]{6,})')
# known provider token shapes (redact the whole token wherever it appears)
_PROVIDER = re.compile(
    r'(?:AKIA[0-9A-Z]{16}'                                   # AWS access key id
    r'|gh[pousr]_[A-Za-z0-9]{20,}'                           # GitHub tokens
    r'|xox[baprs]-[A-Za-z0-9-]{10,}'                         # Slack
    r'|sk-(?:proj-)?[A-Za-z0-9_-]{20,}'                      # OpenAI-style
    r'|(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}'             # Stripe secret/restricted
    r'|AIza[0-9A-Za-z_\-]{35}'                               # Google API key
    r'|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)')  # JWT
# 40+ char base64/opaque blobs (e.g. AWS secret keys with / + =) — last-resort
_B64 = re.compile(r'\b[A-Za-z0-9+/]{40,}={0,2}')
_LONG = re.compile(r'\b[A-Za-z0-9_\-]{40,}\b')


def redact(s):
    s = _PEM.sub('<redacted-private-key>', s)
    s = _URLCRED.sub(r'\1<redacted>\3', s)
    s = _SCHEME.sub(r'\1 <redacted-token>', s)
    s = _KV.sub(r'\1<redacted>', s)
    s = _CLI.sub(r'\1<redacted>', s)
    s = _PROVIDER.sub('<redacted-token>', s)
    s = _B64.sub('<redacted-long>', s)
    s = _LONG.sub('<redacted-long>', s)
    return s


def session_cwd_and_count(path):
    cwd, n = None, 0
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                n += 1
                if cwd is None:
                    try:
                        o = json.loads(line)
                        if isinstance(o, dict) and o.get("cwd"):
                            cwd = o["cwd"]
                    except ValueError:
                        pass
    except OSError:
        pass
    return cwd, n


def discover(projects, root, allflag, since_days):
    now = time.time()
    rows = []
    root = os.path.realpath(root) if root else None
    for path in glob.glob(os.path.join(projects, "*", "*.jsonl")):
        cwd, n = session_cwd_and_count(path)
        if n == 0:
            continue
        age = (now - os.path.getmtime(path)) / 86400.0
        if since_days and age > since_days:
            continue
        if not allflag:
            if not cwd:
                continue
            rc = os.path.realpath(cwd)
            if not (rc == root or rc.startswith(root + os.sep)):
                continue
        rows.append((os.path.getmtime(path), path, n, cwd or "?"))
    rows.sort(reverse=True)
    for mt, path, n, cwd in rows:
        age = (now - mt) / 86400.0
        sys.stdout.write("%s\t%d\t%.1f\t%s\n" % (path, n, age, cwd))


def content_text(content):
    out = []
    if isinstance(content, str):
        out.append(content)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                out.append(b.get("text", ""))
            elif t == "tool_use":
                inp = json.dumps(b.get("input", {}), ensure_ascii=False)[:200]
                out.append("[tool:%s %s]" % (b.get("name", "?"), inp))
            elif t == "tool_result":
                c = b.get("content", "")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                out.append("[result: %s]" % str(c)[:200])
            # thinking blocks skipped (size/cost)
    return "\n".join(x for x in out if x)


def is_user_text(o):
    """A message the human typed: type=user, not meta, text content, no tool_result."""
    if o.get("type") != "user" or o.get("isMeta"):
        return False
    c = (o.get("message") or {}).get("content")
    if isinstance(c, str):
        return bool(c.strip())
    if isinstance(c, list):
        kinds = {b.get("type") for b in c if isinstance(b, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def _records(path):
    with open(path, "r", errors="replace") as f:
        for line in f:
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict):
                yield o


def count_user(path):
    try:
        return sum(1 for o in _records(path) if is_user_text(o))
    except OSError:
        return 0


def classify(path, min_user):
    """Deterministic review gate -> (verdict, user_msgs). Only sdk-* entrypoints are
    headless; cli / IDE / desktop / missing entrypoint count as interactive."""
    if not os.path.isfile(path):
        return "skip:missing", 0
    n = parsed = 0
    eps = set()
    try:
        for o in _records(path):
            parsed += 1
            ep = o.get("entrypoint")
            if ep:
                eps.add(str(ep))
            if is_user_text(o):
                n += 1
    except OSError:
        return "skip:unreadable", 0
    if parsed == 0:
        return "skip:unreadable", 0
    if eps and all(e.startswith("sdk") for e in eps):
        return "skip:sdk", n
    if n < min_user:
        return "skip:short", n
    return "review", n


def _clip(text, maxchars):
    """Keep the head (1/3) and the tail (2/3): corrections live at the end."""
    if len(text) <= maxchars:
        return text
    head = maxchars // 3
    tail = maxchars - head
    omitted = len(text) - head - tail
    return text[:head] + "\n\n[... %d chars omitted ...]\n\n" % omitted + text[-tail:]


def flatten(path, maxchars, from_user=0):
    parts = []
    first_user = ""
    seen = 0  # user text messages seen BEFORE the current record
    try:
        for o in _records(path):
            role = o.get("type")
            msg = o.get("message") or {}
            if role == "user":
                txt = content_text(msg.get("content", ""))
                user_text = is_user_text(o)
                if user_text and not first_user:
                    first_user = txt
                if seen >= from_user and txt:
                    parts.append("USER: " + txt)
                if user_text:
                    seen += 1
            elif role == "assistant" and (from_user == 0 or seen > from_user):
                txt = content_text(msg.get("content", ""))
                if txt:
                    parts.append("ASSISTANT: " + txt)
    except OSError:
        pass
    text = "\n\n".join(parts)
    if from_user > 0:
        text = ("CONTEXT: this session was resumed; its first %d user messages were "
                "already reviewed. First user message: %s\n\n" % (from_user, first_user[:1000])) + text
    # redact the WHOLE text before clipping so a secret straddling the cut cannot survive
    return _clip(redact(text), maxchars)


def last_user(path):
    """Text of the most recent real user message in a transcript (the current
    task intent) — used by the mid-task re-surface. Skips tool-result/meta noise."""
    last = ""
    try:
        with open(path, "r", errors="replace") as f:
            for line in f:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if isinstance(o, dict) and o.get("type") == "user":
                    msg = o.get("message") or {}
                    c = msg.get("content", "")
                    # skip turns that are purely tool_result (no human text)
                    if isinstance(c, list) and all(
                            isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                        continue
                    txt = content_text(c)
                    if txt:
                        last = txt
    except OSError:
        pass
    return last


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    action = argv[1]
    if action == "last-user":
        sys.stdout.write(last_user(argv[2]))
        return 0
    if action == "discover":
        discover(argv[2], argv[3], int(argv[4]), int(argv[5]))
        return 0
    if action == "flatten":
        # argv[2]=projects_dir (unused beyond symmetry), argv[3]=path
        sys.stdout.write(flatten(argv[3], int(argv[4])))
        return 0
    if action == "flatten-file":
        frm = int(argv[4]) if len(argv) > 4 else 0
        sys.stdout.write(flatten(argv[2], int(argv[3]), frm))
        return 0
    if action == "classify":
        v, n = classify(argv[2], int(argv[3]))
        sys.stdout.write("%s\t%d\n" % (v, n))
        return 0
    if action == "count-user":
        sys.stdout.write("%d\n" % count_user(argv[2]))
        return 0
    sys.stderr.write("unknown action: %s\n" % action)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
