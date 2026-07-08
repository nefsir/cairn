#!/usr/bin/env python3
# =============================================================================
# suggest.py — score a prompt against the skill library; surface the top matches.
#
# This is the USE-side counterpart to the capture loop: at the moment a task
# starts, it pushes the few RELEVANT skills forward instead of relying on a flat
# 192-entry index nobody re-scans. Local and instant — NO model call. Matching is
# IDF-weighted token overlap, so distinctive triggers (mysql, flyway, redis, and
# the bilingual "Use when ..." phrases incl. Polish) outweigh common words; a
# prompt that shares only generic words scores low and surfaces nothing.
#
# Platform-aware: a skill may declare a
# `platforms:` frontmatter key (e.g. `platforms: macos` or `platforms: [macos,
# linux]`) and is skipped where it doesn't apply.
#
# Usage:  suggest.py <skills_dir> <topk> <platform>     # prompt on stdin
#   Strong matches (score >= CAIRN_SUGGEST_THRESHOLD, default 5.0):
#     prints  <name>\t<score>\t<one-line description>  for each, up to <topk>.
#   No strong match but topically warm (best >= CAIRN_ROSTER_FLOOR, default 2.0):
#     prints ONE names-only safety-net line  @@ROSTER@@\t<extra>\t<name, name, ...>
#     — the near-miss skill names (any token overlap), ranked by score — a ranked,
#     prompt-relevant fallback so a token-overlap false negative stays one Skill call
#     away. Zero-overlap skills are NOT listed (unrecoverable noise; use
#     `cairn suggest "<words>"` to re-query). Disable with CAIRN_SUGGEST_ROSTER=0;
#     ceiling for common words is CAIRN_ROSTER_MAX (default 40; 0 = uncapped).
#   Cold (best < floor, incl. no overlap): prints NOTHING (silent on chatter).
# =============================================================================
import sys
import os
import re
import glob
import math

STOP = set("""a an the of to and or for with use used using when this that those
these on in into your you user users claude skill skills it its as be by from at
if then else do does done can will would should task tasks help via run runs new
also etc safely across i we us our my me how what why fix add make get set see
need want like just only per about over under more most less
thanks thank looks look good great nice okay yeah yes sure cool well please
dobra dobrze fajnie spoko super zrob zrób mozemy możemy jak tak nie""".split())


# fold Polish (and common Latin) diacritics to ASCII so a prompt matches a
# description whether or not either side used diacritics, and so inflected tokens
# stay whole (usuń -> usun, not usu).
_FOLD = str.maketrans("ąćęłńóśźżàáâäèéêëìíîïòóôöùúûüç", "acelnoszzaaaaeeeeiiiioooouuuuc")


def toks(s):
    s = s.lower().translate(_FOLD)
    return set(t for t in re.split(r'[^a-z0-9]+', s) if len(t) > 2 and t not in STOP)


def _matched_tokens(ptoks, stoks):
    """Skill tokens hit by a prompt token — exact, or (for longer words) sharing a
    5-char prefix so inflected/cross-form variants align (migration~migracja)."""
    hit = set()
    for st in stoks:
        if st in ptoks:
            hit.add(st)
            continue
        if len(st) >= 6:
            pre = st[:5]
            for pt in ptoks:
                if len(pt) >= 6 and pt[:5] == pre:
                    hit.add(st)
                    break
    return hit


def _list_field(fm, key):
    m = re.search(r'^' + key + r':[ \t]*(.+)$', fm, re.M)
    if not m:
        return []
    raw = m.group(1).strip().strip("[]")
    return [p.strip().strip("'\"").lower() for p in raw.split(",") if p.strip()]


def frontmatter(path):
    name, desc, plats, keywords = "", "", [], ""
    try:
        t = open(path, errors="replace").read()
        m = re.search(r'^---\s*\n(.*?)\n---', t, re.S)
        fm = m.group(1) if m else ""
        nm = re.search(r'^name:[ \t]*(.+)$', fm, re.M)
        name = nm.group(1).strip() if nm else ""
        dm = re.search(r'^description:[ \t]*(.+)$', fm, re.M)
        desc = dm.group(1).strip() if dm else ""
        plats = _list_field(fm, "platforms")
        km = re.search(r'^keywords:[ \t]*(.+)$', fm, re.M)
        keywords = km.group(1).strip() if km else ""
    except (OSError, UnicodeError):
        pass
    return name, desc, plats, keywords


def main(argv):
    if len(argv) < 3:
        sys.stderr.write(__doc__)
        return 2
    skills_dir, topk = argv[1], int(argv[2])
    platform = (argv[3] if len(argv) > 3 else "").lower()
    prompt = sys.stdin.read()
    ptoks = toks(prompt)
    if not ptoks or not os.path.isdir(skills_dir):
        return 0

    kw_boost = float(os.environ.get("CAIRN_SUGGEST_KW_BOOST", "2.0"))
    skills = []
    for d in sorted(glob.glob(os.path.join(skills_dir, "*"))):
        sp = os.path.join(d, "SKILL.md")
        if not os.path.isfile(sp):
            continue
        name, desc, plats, keywords = frontmatter(sp)
        name = name or os.path.basename(d)
        if name == "skill-extraction":          # infrastructure, not a task skill
            continue
        if plats and platform and platform not in plats:  # platform gating
            continue
        # desc tokens (incl. name) + the curated `keywords:` set (weighted higher)
        skills.append((name, desc, toks(name + " " + desc), toks(keywords)))
    if not skills:
        return 0

    # idf over the library: rare tokens are strong signals (keywords counted too)
    df = {}
    for _, _, dt, kt in skills:
        for t in (dt | kt):
            df[t] = df.get(t, 0) + 1
    n = len(skills)

    def idf(t):
        return math.log((n + 1.0) / (df.get(t, 0) + 1.0)) + 1.0

    scored = []
    for name, desc, dt, kt in skills:
        score = 0.0
        for t in _matched_tokens(ptoks, dt | kt):
            score += idf(t) * (kw_boost if t in kt else 1.0)  # boost curated keywords
        if score > 0:
            scored.append((score, name, desc))
    scored.sort(key=lambda x: (-x[0], x[1]))

    thresh = float(os.environ.get("CAIRN_SUGGEST_THRESHOLD", "5.0"))
    strong = [(s, n, d) for s, n, d in scored if s >= thresh][:topk]
    if strong:
        for score, name, desc in strong:
            first = re.split(r'(?<=[.])\s', desc)[0][:110] if desc else ""
            sys.stdout.write("%s\t%.1f\t%s\n" % (name, score, first))
        return 0

    # No strong match -> names-only safety net: a names-only category demotion that
    # keeps names visible when descriptions drop. A ranked, prompt-relevant fallback: a token-overlap near-miss that
    # didn't clear the bar stays one Skill call away. When the prompt is topically warm
    # (best score >= floor: it shares distinctive skill vocab but nothing cleared
    # the bar) we list the NEAR-MISS names — every skill with ANY overlap, ranked
    # by score. We deliberately do NOT dump the whole library: a zero-overlap skill
    # buried in a 180-name tail is not discoverable (that's the needle-in-haystack
    # the native listing was removed for) and costs tokens every warm turn. A true
    # zero-overlap semantic miss is recovered via `cairn suggest "<other words>"`,
    # not by eyeballing an unranked dump. Silent on chatter/off-topic (best <
    # floor) and when disabled via CAIRN_SUGGEST_ROSTER=0.
    if os.environ.get("CAIRN_SUGGEST_ROSTER", "1") == "0":
        return 0
    best = scored[0][0] if scored else 0.0
    floor = float(os.environ.get("CAIRN_ROSTER_FLOOR", "2.0"))
    if best < floor:
        return 0
    names = [n for _, n, _ in scored]          # scored: overlap>0, already ranked
    cap = int(os.environ.get("CAIRN_ROSTER_MAX", "40"))  # ceiling for common words
    shown_names = names[:cap] if cap > 0 else names
    extra = len(names) - len(shown_names)
    sys.stdout.write("@@ROSTER@@\t%d\t%s\n" % (extra, ", ".join(shown_names)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
