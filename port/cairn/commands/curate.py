"""cairn curate [--apply-lifecycle|--merge|--archive-weak|--assess|--yes|--threshold]
— consolidation + lifecycle report (read-only), and the batch modes. Ports bash
cmd_curate: the two inline-python analyses lifted verbatim (byte-identical CURATE.md /
weak.tsv), lifecycle apply, and merge (untrusted-model sanitize + stage-then-validate +
archive-not-delete).
"""
from __future__ import annotations

import glob
import itertools
import os
import re
import tempfile
from pathlib import Path

from ..claude import run_claude
from ..clock import stamp_hm, today
from ..context import Context
from ..gitutil import skills_commit
from ..helpers import need_claude, need_python
from ..out import die, hdr, info, ok, warn
from ..provision import assess_skills
from ..skillsutil import archive_skill, is_protected


def still_weak(quality, get):
    """True when a low `quality` score is still supported by evidence.

    `quality` is written ONCE (the assess pass skips anything already scored) and
    nothing recomputes it, so a 1-2 assigned months ago survives a full rewrite.
    Regular use or a fully passing eval set clears the flag — otherwise
    --archive-weak would archive a heavily used skill on a frozen number.
    """
    if quality not in ("1", "2"):
        return False
    try:
        if int(get("use_count") or 0) >= 3:
            return False
    except (TypeError, ValueError):
        pass
    rate = get("last_eval_rate") or ""
    passed, sep, total = rate.partition("/")
    if sep:
        try:
            if int(total) > 0 and int(passed) == int(total):
                return False
        except ValueError:
            pass
    return True


MERGE_PROMPT = """You are merging several overlapping Claude Code skills into ONE class-level
umbrella skill. Each source skill's SKILL.md is on stdin, separated by lines like
"===== <name> =====". Produce ONE merged SKILL.md and NOTHING else:
- YAML frontmatter delimited by --- with `name:` (the clearest existing name or a
  better kebab-case umbrella name) and `description:` (the UNION of the distinct
  triggers, deduplicated, concrete "Use when ..." phrasing, <=1024 chars),
- a body that merges the procedures into clearly labelled subsections, removes
  duplicate steps, reconciles overlaps, and preserves every distinct piece of
  guidance and success criterion from the sources.
Output ONLY the file content, starting with "---". No prose, no code fences."""


def _analyze(SKILLS, THRESH, FOLD, OUT):
    """Consolidation analysis — lifted verbatim from bash cmd_curate's inline python."""
    USE_MIN = int(os.environ.get('CAIRN_USE_MIN', '3'))
    USE_AVG = float(os.environ.get('CAIRN_USE_AVG', '2.5'))
    STOP = set("""a an the of to and or for with use used using when this that those these on
in into your you user users claude skill skills it its as be by from at if then else do
does done can will would should task tasks help via run runs new also etc""".split())

    def toks(s):
        return set(t for t in re.split(r'[^a-z0-9]+', s.lower()) if len(t) > 2 and t not in STOP)

    def frontmatter(p):
        name = desc = ""
        try:
            t = open(p, errors='replace').read()
            m = re.search(r'^---\s*\n(.*?)\n---', t, re.S)
            fm = m.group(1) if m else ""
            nm = re.search(r'^name:[ \t]*(.+)$', fm, re.M)
            name = nm.group(1).strip() if nm else ""
            dm = re.search(r'^description:[ \t]*(.*)$', fm, re.M)
            desc = dm.group(1).strip() if dm else ""
            if desc in ('>', '>-', '>+', '|', '|-', '|+'):
                # YAML block scalar: the text lives in the indented lines below.
                tail = fm[dm.end():].split('\n')[1:]
                body = []
                for ln in tail:
                    if ln.strip() and not ln[:1].isspace():
                        break
                    body.append(ln.strip())
                desc = ' '.join(x for x in body if x)
        except Exception:
            pass
        return name, desc

    def learn_count(d):
        p = os.path.join(SKILLS, d, 'learnings.md')
        if not os.path.isfile(p):
            return 0
        n = 0
        for line in open(p, errors='replace'):
            ls = line.strip()
            if ls.startswith('<!--') or not ls:
                continue
            if ls.startswith('-') or re.match(r'^\d{4}-\d{2}-\d{2}', ls):
                n += 1
        return n

    def usage_stats(d):
        p = os.path.join(SKILLS, d, 'usage.md')
        if not os.path.isfile(p):
            return (None, 0)
        sc = []
        for line in open(p, errors='replace'):
            m = re.match(r'\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5', line)
            if m:
                sc.append(int(m.group(1)))
        return ((sum(sc) / len(sc)) if sc else None, len(sc))

    def meta_get(d, key):
        p = os.path.join(SKILLS, d, '.meta')
        if os.path.isfile(p):
            for line in open(p, errors='replace'):
                if line.strip().startswith(key + '='):
                    return line.split('=', 1)[1].strip()
        return ''

    skills = []
    for dpath in sorted(glob.glob(os.path.join(SKILLS, '*'))):
        sp = os.path.join(dpath, 'SKILL.md')
        if not os.path.isfile(sp):
            continue
        dirn = os.path.basename(dpath)
        if dirn == 'skill-extraction':
            continue
        if meta_get(dirn, 'provenance') == 'bundled' or meta_get(dirn, 'pinned') == 'true':
            continue
        name, desc = frontmatter(sp)
        uavg, uc = usage_stats(dirn)
        skills.append({'dir': dirn, 'name': name or dirn, 'desc': desc,
                       'toks': toks((name or dirn) + ' ' + desc),
                       'learn': learn_count(dirn), 'uavg': uavg, 'uc': uc, 'q': meta_get(dirn, 'quality')})

    def jac(a, b):
        return len(a & b) / len(a | b) if a and b else 0.0
    pairs = [(i, j, jac(skills[i]['toks'], skills[j]['toks']))
             for i, j in itertools.combinations(range(len(skills)), 2)
             if jac(skills[i]['toks'], skills[j]['toks']) >= THRESH]
    parent = list(range(len(skills)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i, j, _ in pairs:
        parent[find(i)] = find(j)
    groups = {}
    for idx in range(len(skills)):
        groups.setdefault(find(idx), []).append(idx)
    clusters = [g for g in groups.values() if len(g) > 1]

    def best(g):
        return max([jac(skills[a]['toks'], skills[b]['toks']) for a, b in itertools.combinations(g, 2)] or [0])
    clusters.sort(key=best, reverse=True)
    folds = sorted([s for s in skills if s['learn'] >= FOLD], key=lambda s: s['learn'], reverse=True)
    lowuse = sorted([s for s in skills if s['uc'] >= USE_MIN and s['uavg'] is not None and s['uavg'] <= USE_AVG], key=lambda s: s['uavg'])
    lowq = sorted([s for s in skills if still_weak(s['q'], lambda k, d=s['dir']: meta_get(d, k))],
                  key=lambda s: s['q'])
    L = []
    if clusters:
        L.append("## Merge into umbrellas (%d cluster(s))" % len(clusters))
        L.append("")
        L.append("For each cluster ask: would a maintainer write these as N skills, or "
                 "ONE umbrella with N labelled subsections? Merge when the latter "
                 "(demote narrow siblings to references/templates/scripts).")
        L.append("")
        for g in clusters:
            ms = [skills[i] for i in g]
            L.append("### %s  (overlap %.2f)" % (' + '.join(m['dir'] for m in ms), best(g)))
            for m in ms:
                d = (m['desc'][:140] + '…') if len(m['desc']) > 140 else m['desc']
                L.append("- **%s** — %s%s" % (m['dir'], d or '(no description)', ("  · %d learning(s)" % m['learn']) if m['learn'] else ""))
            L.append("")
            L.append("    /skill-merge %s" % (' '.join(m['dir'] for m in ms)))
            L.append("")
    if folds:
        L.append("## Fold candidates (%d)" % len(folds))
        L.append("")
        L.append("learnings.md has grown enough to fold stable entries into SKILL.md.")
        L.append("")
        for s in folds:
            L.append("- **%s** — %d learning entries" % (s['dir'], s['learn']))
            L.append("      /skill-fold %s" % s['dir'])
        L.append("")
    if lowuse:
        L.append("## Low-usefulness (%d)" % len(lowuse))
        L.append("")
        L.append("Scored poorly across real uses — improve, or merge into something better.")
        L.append("")
        for s in lowuse:
            L.append("- **%s** — avg %.1f/5 over %d use(s)" % (s['dir'], s['uavg'], s['uc']))
            L.append("      /skill-improve %s" % s['dir'])
        L.append("")
    if lowq:
        L.append("## Low-quality — assessed 1-2/5 (%d)" % len(lowq))
        L.append("")
        L.append("These scored low on the quality assessment (`cairn migrate`). Improve them, "
                 "merge them into a stronger umbrella, or archive in one pass with "
                 "`cairn curate --archive-weak`.")
        L.append("")
        for s in lowq:
            d = (s['desc'][:120] + '…') if len(s['desc']) > 120 else s['desc']
            L.append("- **%s** — quality %s/5 — %s" % (s['dir'], s['q'], d or '(no description)'))
            L.append("      /skill-improve %s   ·   or  cairn curate --archive-weak" % s['dir'])
        L.append("")
    open(OUT, 'w').write('\n'.join(L) + ('\n' if L else ''))
    print("clusters=%d folds=%d lowuse=%d lowq=%d scanned=%d" % (len(clusters), len(folds), len(lowuse), len(lowq), len(skills)))


def _weak_detect(SKILLS, UAVG, UMIN) -> str:
    """Weak-skill detection — lifted verbatim from bash's inline python; returns the tsv."""
    lines = []

    def mg(d, k):
        p = os.path.join(SKILLS, d, '.meta')
        if os.path.isfile(p):
            for l in open(p, errors='replace'):
                if l.strip().startswith(k + '='):
                    return l.split('=', 1)[1].strip()
        return ''

    def uavg(d):
        p = os.path.join(SKILLS, d, 'usage.md')
        sc = []
        if os.path.isfile(p):
            for l in open(p, errors='replace'):
                m = re.match(r'\s*\d{4}-\d{2}-\d{2}\s*\|\s*([0-5])\s*/\s*5', l)
                if m:
                    sc.append(int(m.group(1)))
        return (sum(sc) / len(sc) if sc else None, len(sc))
    for dp in sorted(glob.glob(os.path.join(SKILLS, '*'))):
        d = os.path.basename(dp)
        if not os.path.isfile(os.path.join(dp, 'SKILL.md')) or d == 'skill-extraction':
            continue
        if mg(d, 'provenance') == 'bundled' or mg(d, 'pinned') == 'true' or mg(d, 'state') == 'archived':
            continue
        q = mg(d, 'quality')
        a, n = uavg(d)
        reason = None
        if still_weak(q, lambda k, _d=d: mg(_d, k)):
            reason = 'quality ' + q
        elif a is not None and n >= UMIN and a <= UAVG:
            reason = 'usefulness %.1f/5 over %d' % (a, n)
        if reason:
            lines.append('%s\t%s' % (d, reason))
    return "".join(l + "\n" for l in lines)


def _dedup_feedback(ctx, members, target, fname, header):
    seen = set()
    out = [header + f" {target}\n"]
    for m in members:
        p = ctx.cfg.skills / m / fname
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8", errors="replace").split("\n"):
            if re.match(r'^(#|<!--|[ \t]*$)', line):
                continue
            if line not in seen:
                seen.add(line)
                out.append(line + "\n")
    return "".join(out)


def cmd_curate(ctx: Context, args: list[str]) -> int:
    need_python()
    cfg = ctx.cfg
    if not cfg.skills.is_dir():
        die(f"no skills dir at {cfg.skills}")
    apply = do_merge = do_weak = do_assess = yes = 0
    thresh_str = os.environ.get("CAIRN_CURATE_THRESHOLD") or "0.40"
    fold = int(os.environ.get("CAIRN_FOLD_AT") or 15)
    stale = int(os.environ.get("CAIRN_STALE_DAYS") or 30)
    arch = int(os.environ.get("CAIRN_ARCHIVE_DAYS") or 90)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--apply-lifecycle":
            apply = 1
        elif a == "--merge":
            do_merge = 1
        elif a == "--archive-weak":
            do_weak = 1
        elif a == "--assess":
            do_assess = 1
        elif a in ("--yes", "-y"):
            yes = 1
        elif a == "--threshold":
            thresh_str = args[i + 1] if i + 1 < len(args) else "0.40"
            i += 1
        else:
            die(f"curate: unknown option {a}")
        i += 1
    cfg.harvest.mkdir(parents=True, exist_ok=True)
    cfg.logs.mkdir(parents=True, exist_ok=True)
    tmpd = Path(tempfile.mkdtemp())
    out = cfg.harvest / "CURATE.md"
    body = tmpd / "body.md"

    _analyze(str(cfg.skills), float(thresh_str), fold, str(body))
    life = ctx.lib.run("lifecycle", "propose", str(cfg.skills), today(), stale, arch).out

    body_text = body.read_text(encoding="utf-8", errors="replace") if body.is_file() else ""
    r = [
        f"# Cairn curate report ({stamp_hm()})\n\n",
        f"Scanned `{cfg.skills}` — overlap≥{thresh_str}, fold-at {fold}, stale@{stale}d, archive@{arch}d.\n",
        "Read-only by default. Merges are manual (/skill-merge); lifecycle applies with --apply-lifecycle.\n\n",
    ]
    if body_text != "":
        r.append(body_text)
    else:
        r.append("_No merge / fold / low-usefulness candidates. Library looks tidy._\n\n")
    r.append("## Lifecycle transitions (by inactivity)\n\n")
    life_rows = [ln for ln in life.split("\n") if ln]
    if life != "" and life.strip("\n") != "":
        r.append("| skill | from | to | idle (days) |\n|---|---|---|---|\n")
        for ln in life_rows:
            f = ln.split("\t")
            name = f[0]
            if name:
                r.append(f"| {name} | {f[1] if len(f) > 1 else ''} | {f[2] if len(f) > 2 else ''} | {chr(9).join(f[3:]) if len(f) > 3 else ''} |\n")
        r.append("\n(pinned and bundled skills are never auto-transitioned.)\n")
    else:
        r.append("_No skills are stale or archivable. Nothing ages out._\n")
    out.write_text("".join(r), encoding="utf-8")

    ok(f"curate report: {out}")
    otext = out.read_text(encoding="utf-8", errors="replace")
    recs = otext.split("\n")
    if otext.endswith("\n"):
        recs = recs[:-1]
    for line in recs[:40]:
        print(line)

    if apply == 1 and life.strip("\n") != "":
        hdr("Applying lifecycle")
        staled = moved = 0
        for ln in life_rows:
            f = ln.split("\t")
            name = f[0]
            if not name:
                continue
            to = f[2] if len(f) > 2 else ""
            d = cfg.skills / name
            if not d.is_dir():
                continue
            if to == "stale":
                ctx.lib.run("meta", "set", str(d / ".meta"), "state", "stale")
                staled += 1
                ok(f"{name} → stale")
            elif to == "archived":
                dest = archive_skill(ctx, name)
                if dest:
                    moved += 1
                    ok(f"{name} → archived ({dest})")
                else:
                    warn(f"{name}: archive move failed — left in place, state unchanged")
        skills_commit(cfg, f"cairn: lifecycle ({staled} stale, {moved} archived)")
        ok(f"lifecycle applied: {staled} stale, {moved} archived (recoverable in {cfg.archive} + git)")

    if do_merge == 1:
        _do_merge(ctx, tmpd, thresh_str, yes)

    if do_weak == 1:
        _do_archive_weak(ctx, yes, do_assess)

    import shutil
    shutil.rmtree(tmpd, ignore_errors=True)
    return 0


def _do_merge(ctx: Context, tmpd: Path, thresh_str: str, yes: int) -> None:
    cfg = ctx.cfg
    hdr("Merge overlapping skills into umbrellas")
    if yes != 1:
        info("PREVIEW — add --yes to execute. Originals are archived, never deleted.")
    cl = ctx.lib.run("cluster", "skills", str(cfg.skills), thresh_str).out
    if cl.strip("\n") == "":
        ok(f"no overlapping clusters at threshold {thresh_str}")
        return
    if yes == 1:
        need_claude()
    merged_n = 0
    for line in cl.split("\n"):
        if not line:
            continue
        members = [m for m in line.split() if not is_protected(ctx, m)]
        if len(members) < 2:
            info("  skip (fewer than 2 unprotected): " + line.replace("\t", " "))
            continue
        if yes != 1:
            info("  would merge: " + " ".join(members) + " → one umbrella")
            continue
        feed = tmpd / "merge.in"
        o2 = tmpd / "merge.out"
        e2 = tmpd / "merge.err"
        parts = []
        for m in members:
            parts.append(f"===== {m} =====\n")
            parts.append((cfg.skills / m / "SKILL.md").read_text(encoding="utf-8", errors="replace"))
            parts.append("\n")
        feed.write_text("".join(parts), encoding="utf-8")
        from ..out import say
        say(cfg.logs / "curate.log", "merging: " + " ".join(members))
        rc = run_claude(MERGE_PROMPT, cfg.model_default, str(feed), str(o2), str(e2), 3, "merge", str(cfg.logs / "curate.log"))
        if rc != 0:
            warn("merge failed for: " + " ".join(members) + " (originals intact)")
            continue
        o2text = o2.read_text(encoding="utf-8", errors="replace") if o2.is_file() else ""
        if o2text == "":
            warn("merge produced no output for: " + " ".join(members) + " (originals intact)")
            continue
        target = ""
        for ln in o2text.split("\n"):
            if ln.startswith("name:"):
                target = re.sub(r'[\s"\']', "", re.sub(r'^name:[ \t]*', "", ln))
                break
        if target == "" or "/" in target or "." in target:
            target = members[0]
        if not re.match(r'^[a-z0-9]', target):
            target = members[0]
        is_member = target in members
        if (cfg.skills / target).is_dir() and not is_member:
            warn(f"merge target '{target}' collides with an existing non-member skill — skipped (originals intact)")
            continue
        if is_protected(ctx, target):
            warn(f"merge target '{target}' is protected — skipped")
            continue
        stage = tmpd / "stage"
        import shutil
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
        (stage / "SKILL.md").write_text(o2text, encoding="utf-8")
        if ctx.lib.run("validate", "skill", str(stage)).out != "":
            warn(f"merged '{target}' failed frontmatter validation — skipped (originals intact)")
            continue
        learn = _dedup_feedback(ctx, members, target, "learnings.md", "# Learnings —")
        usage = _dedup_feedback(ctx, members, target, "usage.md", "# Usage ratings —")
        (cfg.skills / target).mkdir(parents=True, exist_ok=True)
        (cfg.skills / target / "SKILL.md").write_text(o2text, encoding="utf-8")
        (cfg.skills / target / "learnings.md").write_text(learn, encoding="utf-8")
        (cfg.skills / target / "usage.md").write_text(usage, encoding="utf-8")
        day = today()
        ctx.lib.run("meta", "init", str(cfg.skills / target / ".meta"), f"created={day}", f"last_used={day}")
        ctx.lib.run("meta", "set", str(cfg.skills / target / ".meta"), "last_patched", day)
        for m in members:
            if m == target:
                continue
            if archive_skill(ctx, m):
                ok(f"  archived {m} → merged into {target}")
        merged_n += 1
        ok("merged [" + " ".join(members) + f"] → {target}")
    if yes == 1:
        skills_commit(cfg, f"cairn: auto-merged {merged_n} cluster(s)")
        ok(f"merged {merged_n} cluster(s) (originals in {cfg.archive} + git)")


def _do_archive_weak(ctx: Context, yes: int, do_assess: int) -> None:
    cfg = ctx.cfg
    hdr("Archive weak skills")
    if yes != 1:
        info("PREVIEW — add --yes to execute. Archived (recoverable), never deleted.")
    uavg = float(os.environ.get("CAIRN_USE_AVG") or 2.5)
    umin = int(os.environ.get("CAIRN_USE_MIN") or 3)
    if do_assess == 1 and yes == 1:
        need_claude()
        hdr("Assessing unscored skills first")
        assess_skills(ctx)
    weak = _weak_detect(str(cfg.skills), uavg, umin)
    if weak.strip("\n") == "":
        ok("no weak skills (quality 1-2, or low usefulness). Assess first with --assess.")
        return
    wn = 0
    for line in weak.split("\n"):
        if not line:
            continue
        f = line.split("\t")
        wname = f[0]
        wreason = f[1] if len(f) > 1 else ""
        if not wname:
            continue
        if yes != 1:
            info(f"  would archive: {wname} ({wreason})")
            continue
        if archive_skill(ctx, wname):
            wn += 1
            ok(f"archived {wname} ({wreason})")
    if yes == 1:
        skills_commit(cfg, f"cairn: archived {wn} weak skill(s)")
        ok(f"archived {wn} weak skill(s) (recoverable in {cfg.archive} + git)")
