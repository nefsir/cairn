"""cairn mine / distill / refine — Layer A backfill (past transcripts -> proposals).
Ports bash cmd_mine/distill/refine: resumable per-unit stamps (.done/.failed), the
run_claude 3-way contract (HALT leaves unstamped), the append-only candidate filter,
and the inline-python cluster/split/rebuild steps (lifted verbatim). All model prompts
are byte-identical (see prompts.py).
"""
from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path

from ..claude import run_claude
from ..clock import stamp_hm, ts
from ..context import Context
from ..helpers import need_claude, need_python
from ..out import die, info, ok, say
from ..prompts import AGG_PROMPT, EXTRACT_PROMPT, REFINE_PROMPT, SYN_PROMPT


def _opt(args, i, default):
    return args[i + 1] if i + 1 < len(args) else default


def cmd_mine(ctx: Context, args: list[str]) -> int:
    need_python()
    need_claude()
    cfg = ctx.cfg
    projects = cfg.claude_dir / "projects"
    root = ""
    ALL = SINCE = 0
    MAX = 20
    model = cfg.model_default
    maxchars = 60000
    mr = 3
    retry_failed = reset = dryr = 0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--all":
            ALL = 1
        elif a == "--since":
            SINCE = int(_opt(args, i, "0")); i += 1
        elif a == "--max-sessions":
            MAX = int(_opt(args, i, "20")); i += 1
        elif a == "--model":
            model = _opt(args, i, cfg.model_default); i += 1
        elif a == "--max-chars":
            maxchars = int(_opt(args, i, "60000")); i += 1
        elif a == "--max-retries":
            mr = int(_opt(args, i, "3")); i += 1
        elif a == "--retry-failed":
            retry_failed = 1
        elif a == "--dry-run":
            dryr = 1
        elif a == "--reset":
            reset = 1
        elif a.startswith("--"):
            die(f"mine: unknown option {a}")
        else:
            root = a
        i += 1
    if not root:
        root = os.getcwd()
    if not projects.is_dir():
        die(f"no transcripts dir at {projects}")
    stamps = cfg.harvest / ".mined"
    cand = cfg.harvest / "candidates.jsonl"
    prop = cfg.harvest / "PROPOSALS.md"
    lf = cfg.logs / "mine.log"
    stamps.mkdir(parents=True, exist_ok=True)
    cfg.logs.mkdir(parents=True, exist_ok=True)
    if reset == 1:
        for f in stamps.glob("*"):
            f.unlink()
        cand.write_text("", encoding="utf-8")
    if not cand.exists():
        cand.write_text("", encoding="utf-8")

    disc = ctx.lib.run("transcript", "discover", str(projects), root, str(ALL), str(SINCE)).out
    recs = disc.split("\n")
    if disc.endswith("\n"):
        recs = recs[:-1]
    rows = recs[:MAX]
    total = sum(1 for r in rows if r != "")
    scope = "ALL projects" if ALL == 1 else f"cwd under {root}"
    say(lf, f"scope: {scope} | since: {SINCE}d | matched (cap {MAX}): {total} session(s)")
    if total == 0:
        print("No matching transcripts. Try --all or a higher --since.")
        return 0

    if dryr == 1:
        print("%-6s %-7s %s" % ("MSGS", "AGE(d)", "SESSION (cwd)"))
        s = 0
        for r in rows:
            if not r:
                continue
            p = r.split("\t")
            print("%-6s %-7s %s" % (p[1], p[2], p[3] if len(p) > 3 else ""))
            c = int(p[1]) * 400
            if c > maxchars:
                c = maxchars
            s += c
        print()
        print(f"Rough input estimate: ~{s // 4} tokens across {total} session(s). Dry run — nothing sent.")
        return 0

    halted = failed = 0
    for r in rows:
        if not r:
            continue
        p = r.split("\t")
        f, n = p[0], p[1]
        base = os.path.basename(f)
        done_s = stamps / f"{base}.done"
        fail_s = stamps / f"{base}.failed"
        if reset != 1:
            if done_s.is_file():
                say(lf, f"skip (mined): {base}")
                continue
            if fail_s.is_file() and retry_failed != 1:
                say(lf, f"skip (failed; --retry-failed): {base}")
                continue
        if retry_failed == 1:
            fail_s.unlink(missing_ok=True)
        flat = ctx.lib.run("transcript", "flatten-file", f, str(maxchars)).out.rstrip("\n")
        if flat == "":
            say(lf, f"skip (empty): {base}")
            done_s.touch()
            continue
        say(lf, f"extracting: {base} ({n} msgs)")
        pid = os.getpid()
        inf = cfg.harvest / f".in.{pid}"
        outf = cfg.harvest / f".out.{pid}"
        errf = cfg.harvest / f".err.{pid}"
        inf.write_text(flat, encoding="utf-8")
        rc = run_claude(EXTRACT_PROMPT, model, str(inf), str(outf), str(errf), mr, base, str(lf))
        if rc == 1:
            say(lf, f"HALT: persistent transient error on {base} — NOT marked done")
            for t in (inf, outf, errf):
                t.unlink(missing_ok=True)
            halted = 1
            break
        if rc == 2:
            failed += 1
            say(lf, f"FAILED (quarantined): {base}")
            fail_s.touch()
            for t in (inf, outf, errf):
                t.unlink(missing_ok=True)
            continue
        keep = [ln for ln in outf.read_text(encoding="utf-8", errors="replace").split("\n")
                if re.match(r'^\s*\{.*\}\s*$', ln)]
        if keep:
            with open(cand, "a", encoding="utf-8") as c:
                c.write("".join(ln + "\n" for ln in keep))
        for t in (inf, outf, errf):
            t.unlink(missing_ok=True)
        done_s.touch()
    if failed > 0:
        say(lf, f"quarantined {failed} session(s) (retry: --retry-failed)")
    if halted == 1:
        print("Stopped early without losing progress — re-run to resume.")
        return 1

    cn = sum(1 for ln in cand.read_text(encoding="utf-8", errors="replace").split("\n") if ln != "")
    say(lf, f"candidates so far: {cn}")
    if cn == 0:
        print("No candidates emitted.")
        return 0
    say(lf, f"aggregating {cn} candidate(s)")
    pid = os.getpid()
    af = cfg.harvest / f".agg.{pid}"
    ef = cfg.harvest / f".aggerr.{pid}"
    rc = run_claude(AGG_PROMPT, model, str(cand), str(af), str(ef), mr, "aggregate", str(lf))
    if rc != 0:
        af.unlink(missing_ok=True)
        ef.unlink(missing_ok=True)
        print("Aggregation failed — candidates are safe; re-run to retry.")
        return 1
    prop.write_text(
        f"# Skill proposals (mined {stamp_hm()})\n\nScope: {scope} · candidates: {cn}\n"
        f"Review, then scaffold with /skill-new. Nothing was written to skills/.\n\n"
        + af.read_text(encoding="utf-8", errors="replace"),
        encoding="utf-8")
    af.unlink(missing_ok=True)
    ef.unlink(missing_ok=True)
    ok(f"proposals: {prop}")
    info("next: 'cairn distill' (cluster) then 'cairn refine' (score), or scaffold directly with /skill-new")
    return 0


def cmd_distill(ctx: Context, args: list[str]) -> int:
    need_python()
    need_claude()
    cfg = ctx.cfg
    IN = str(cfg.harvest / "candidates.jsonl")
    thresh = "0.50"
    mincl = 2
    maxcl = 60
    maxmem = 30
    model = cfg.model_default
    mr = 3
    reset = dryr = 0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--threshold":
            thresh = _opt(args, i, "0.50"); i += 1
        elif a == "--min-cluster":
            mincl = int(_opt(args, i, "2")); i += 1
        elif a == "--max-clusters":
            maxcl = int(_opt(args, i, "60")); i += 1
        elif a == "--max-members":
            maxmem = int(_opt(args, i, "30")); i += 1
        elif a == "--model":
            model = _opt(args, i, cfg.model_default); i += 1
        elif a == "--max-retries":
            mr = int(_opt(args, i, "3")); i += 1
        elif a == "--reset":
            reset = 1
        elif a == "--dry-run":
            dryr = 1
        elif a.startswith("--"):
            die(f"distill: unknown option {a}")
        else:
            IN = a
        i += 1
    if not os.path.isfile(IN):
        die(f"no candidates at {IN} (run 'cairn mine' first)")
    work = cfg.harvest / "distill"
    cl = work / "clusters"
    pd = work / "proposals"
    st = work / ".done"
    lf = cfg.logs / "distill.log"
    for d in (cl, pd, st, cfg.logs):
        d.mkdir(parents=True, exist_ok=True)
    if reset == 1:
        for d in (st, pd, cl):
            for f in d.glob("*"):
                f.unlink()

    summary = ctx.lib.run("cluster", "candidates", IN, thresh, str(cl)).out.rstrip("\n")
    say(lf, summary)
    eligible = []
    for cf in sorted(cl.glob("cluster_*.json")):
        if len(json.load(open(cf))) >= mincl:
            eligible.append(cf)
    eln = len(eligible)
    if dryr == 1:
        print(f"Eligible clusters (>= {mincl}): {eln} | would synthesize up to {maxcl}. Dry run — no model calls.")
        return 0

    done_n = halted = 0
    i = 0
    for cf in eligible:
        i += 1
        if i > maxcl:
            say(lf, f"reached --max-clusters {maxcl}; {eln - maxcl} left")
            break
        cid = cf.stem
        if (st / f"{cid}.done").is_file() and reset != 1:
            say(lf, f"skip (done): {cid}")
            continue
        full = json.load(open(cf))
        cnt = len(full)
        d = full[:maxmem]
        feed = "\n".join([f"Total in group: {len(full)} (showing {len(d)})"]
                         + [json.dumps(x, ensure_ascii=False) for x in d])
        say(lf, f"synthesizing {cid} ({cnt} candidate(s))")
        pid = os.getpid()
        inf = work / f".in.{pid}"
        outf = work / f".out.{pid}"
        errf = work / f".err.{pid}"
        inf.write_text(feed, encoding="utf-8")
        rc = run_claude(SYN_PROMPT, model, str(inf), str(outf), str(errf), mr, cid, str(lf))
        if rc == 1:
            say(lf, f"HALT on {cid}")
            for t in (inf, outf, errf):
                t.unlink(missing_ok=True)
            halted = 1
            break
        if rc == 2:
            say(lf, f"FAILED (quarantined): {cid}")
            (st / f"{cid}.failed").touch()
            for t in (inf, outf, errf):
                t.unlink(missing_ok=True)
            continue
        (pd / f"{cid}.md").write_text(
            f"<!-- cluster {cid}, {cnt} candidates -->\n"
            + outf.read_text(encoding="utf-8", errors="replace") + "\n",
            encoding="utf-8")
        for t in (inf, outf, errf):
            t.unlink(missing_ok=True)
        (st / f"{cid}.done").touch()
        done_n += 1
    if halted == 1:
        print("Stopped early — re-run to resume.")
        return 1

    prop = cfg.harvest / "PROPOSALS.md"
    parts = [f"# Curated skill proposals (distilled {stamp_hm()})\n\n",
             f"From {IN} · {summary}\n",
             "Ordered by supporting evidence. Scaffold with /skill-new.\n\n"]
    for pf in sorted(pd.glob("*.md")):
        parts.append(pf.read_text(encoding="utf-8", errors="replace"))
        parts.append("\n")
    prop.write_text("".join(parts), encoding="utf-8")
    ok(f"proposals: {prop} (synthesized {done_n} this run)")
    info("next: 'cairn refine' to generalize + reusability-score them")
    return 0


def cmd_refine(ctx: Context, args: list[str]) -> int:
    need_python()
    need_claude()
    cfg = ctx.cfg
    src = str(cfg.harvest / "distill" / "proposals")
    batch = 8
    minscore = 3
    model = cfg.model_default
    mr = 3
    reset = dryr = 0
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--batch":
            batch = int(_opt(args, i, "8")); i += 1
        elif a == "--min-score":
            minscore = int(_opt(args, i, "3")); i += 1
        elif a == "--model":
            model = _opt(args, i, cfg.model_default); i += 1
        elif a == "--max-retries":
            mr = int(_opt(args, i, "3")); i += 1
        elif a == "--reset":
            reset = 1
        elif a == "--dry-run":
            dryr = 1
        elif a.startswith("--"):
            die(f"refine: unknown option {a}")
        else:
            src = a
        i += 1
    if not os.path.isdir(src):
        die(f"no proposals dir at {src} (run 'cairn distill' first)")
    work = cfg.harvest / "refine"
    items = work / "items"
    outd = work / "out"
    st = work / ".done"
    prop = cfg.harvest / "PROPOSALS.md"
    for d in (items, outd, st, work / "batches", cfg.logs):
        d.mkdir(parents=True, exist_ok=True)
    lf = cfg.logs / "refine.log"
    if reset == 1:
        for d in (st, outd, items, work / "batches"):
            for f in d.glob("*"):
                f.unlink()

    # split proposals into item files (lifted verbatim)
    for f in glob.glob(os.path.join(str(items), 'item_*.md')):
        os.remove(f)
    idx = 0
    for pf in sorted(glob.glob(os.path.join(src, '*.md'))):
        for p in re.split(r'(?m)^(?=### )', open(pf, errors='replace').read()):
            if '### ' in p and p.strip():
                open(os.path.join(str(items), 'item_%04d.md' % idx), 'w').write(p.strip() + '\n')
                idx += 1
    print(idx)   # bash's split heredoc prints the item count to stdout
    nitems = len(glob.glob(os.path.join(str(items), "item_*.md")))
    nb = (nitems + batch - 1) // batch
    say(lf, f"split into {nitems} proposal item(s) -> {nb} batch(es) of {batch}")
    if nitems == 0:
        print("No proposals to refine.")
        return 0
    if dryr == 1:
        print(f"Would make {nb} AI call(s). Dry run.")
        return 0

    # group items into batches (lifted verbatim)
    it_list = sorted(glob.glob(os.path.join(str(items), 'item_*.md')))
    bd = str(work / 'batches')
    for f in glob.glob(os.path.join(bd, 'batch_*.md')):
        os.remove(f)
    b = 0
    for k in range(0, len(it_list), batch):
        with open(os.path.join(bd, 'batch_%04d.md' % b), 'w') as out:
            for it in it_list[k:k + batch]:
                out.write(open(it, errors='replace').read().rstrip() + "\n\n")
        b += 1

    done_n = halted = 0
    for bf in sorted((work / "batches").glob("batch_*.md")):
        bid = bf.stem
        if (st / f"{bid}.done").is_file() and reset != 1:
            say(lf, f"skip (done): {bid}")
            continue
        say(lf, f"refining {bid}")
        pid = os.getpid()
        outf = work / f".out.{pid}"
        errf = work / f".err.{pid}"
        rc = run_claude(REFINE_PROMPT, model, str(bf), str(outf), str(errf), mr, bid, str(lf))
        if rc == 1:
            say(lf, f"HALT on {bid}")
            outf.unlink(missing_ok=True)
            errf.unlink(missing_ok=True)
            halted = 1
            break
        if rc == 2:
            say(lf, f"FAILED (quarantined): {bid}")
            (st / f"{bid}.failed").touch()
            outf.unlink(missing_ok=True)
            errf.unlink(missing_ok=True)
            continue
        os.replace(outf, outd / f"{bid}.md")
        errf.unlink(missing_ok=True)
        (st / f"{bid}.done").touch()
        done_n += 1
    if halted == 1:
        print("Stopped early — re-run to resume.")
        return 1

    if prop.is_file():
        import shutil
        shutil.copyfile(prop, prop.with_name(prop.name + f".bak-{ts()}"))
    _rebuild_refined(str(outd), minscore, str(prop), src)
    ok(f"refined proposals: {prop} (refined {done_n} batch(es); highly-reusable at top)")
    return 0


def _rebuild_refined(OUTD, MINSCORE, OUT, SRC):
    """Final refined-proposals rebuild — lifted verbatim from bash's inline python."""
    props = []
    for of in sorted(glob.glob(os.path.join(OUTD, '*.md'))):
        for chunk in re.split(r'(?m)^---\s*$', open(of, errors='replace').read()):
            chunk = chunk.strip()
            if not chunk.startswith('### '):
                continue
            m = re.search(r'Reusability:\s*([1-5])', chunk)
            props.append((int(m.group(1)) if m else 3, chunk))
    props = [c for _, (s, c) in sorted(enumerate(props), key=lambda x: (-x[1][0], x[0]))]

    def sc(c):
        return int(re.search(r'Reusability:\s*([1-5])', c).group(1))

    def emit(g):
        return "\n\n".join(g) if g else "_None._"
    hi = [c for c in props if sc(c) >= 4]
    mid = [c for c in props if sc(c) == 3]
    lo = [c for c in props if sc(c) <= 2]
    o = ["# Refined skill proposals (%s)" % stamp_hm(), "",
         "%d proposal(s), generalized and reusability-scored. Source: %s. Scaffold with /skill-new." % (len(props), SRC), "",
         "## Highly reusable (4-5) — start here", "", emit(hi), "",
         "## Reusable with parameterization (3)", "", emit(mid), "",
         "## Specific — probably skip (1-2)", "These look tied to one service/incident/config.", "", emit(lo), ""]
    open(OUT, 'w').write("\n".join(o) + "\n")
    print("high=%d mid=%d low=%d" % (len(hi), len(mid), len(lo)))
