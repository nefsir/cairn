"""cairn memory [user|agent [action …]] — read / add / replace / remove / trim the two
bounded memory files. Ports bash cmd_memory exactly, incl. the ``$*``-join for add/
replace vs ``$1``-only for remove, the ``${1:-read}`` default action, and the lib's
stderr passthrough (REJECTED reasons) before the collapse-to-die.
"""
from __future__ import annotations

import sys

from ..context import Context
from ..helpers import need_python
from ..out import die, hdr, ok


def cmd_memory(ctx: Context, args: list[str]) -> int:
    need_python()
    cfg = ctx.cfg
    lib = ctx.lib
    cfg.memories.mkdir(parents=True, exist_ok=True)
    u_md, m_md = str(cfg.user_md), str(cfg.memory_md)
    # best-effort init (never clobbers; output suppressed like bash `>/dev/null 2>&1 || true`)
    lib.run("memory", "init", u_md, str(cfg.user_cap), "USER model (cairn)")
    lib.run("memory", "init", m_md, str(cfg.memory_cap), "Agent notes (cairn)")

    which = args[0] if args else ""
    if which == "":
        uc = lib.run("memory", "chars", u_md).value()
        hdr(f"USER.md  ({uc}/{cfg.user_cap} chars)")
        sys.stdout.write(lib.run("memory", "read", u_md).out)
        sys.stdout.write("\n")
        mc = lib.run("memory", "chars", m_md).value()
        hdr(f"MEMORY.md  ({mc}/{cfg.memory_cap} chars)")
        sys.stdout.write(lib.run("memory", "read", m_md).out)
        return 0

    if which == "user":
        file, cap, label = u_md, cfg.user_cap, "USER.md"
    elif which in ("agent", "memory"):
        file, cap, label = m_md, cfg.memory_cap, "MEMORY.md"
    else:
        die(f"memory: first arg must be 'user' or 'agent' (got '{which}')")

    rest = args[1:]
    action = rest[0] if rest else "read"
    aargs = rest[1:]

    if action == "read":
        sys.stdout.write(lib.run("memory", "read", file).out)
        return 0
    if action == "add":
        if len(aargs) < 1:
            die(f'memory {which} add "<text>"')
        res = lib.run("memory", "add", file, str(cap), " ".join(aargs))
        sys.stderr.write(res.err)
        if res.rc == 0:
            ok(f"{label}: added (now {lib.run('memory', 'chars', file).value()}/{cap})")
            return 0
        die(f"memory add rejected (see reason above) — over cap {cap}, or unsafe characters")
    if action == "replace":
        if len(aargs) < 2:
            die(f'memory {which} replace "<substr>" "<text>"')
        res = lib.run("memory", "replace", file, str(cap), aargs[0], " ".join(aargs[1:]))
        sys.stderr.write(res.err)
        if res.rc == 0:
            ok(f"{label}: replaced")
            return 0
        die("replace failed")
    if action == "remove":
        if len(aargs) < 1:
            die(f'memory {which} remove "<substr>"')
        res = lib.run("memory", "remove", file, aargs[0])
        sys.stderr.write(res.err)
        if res.rc == 0:
            ok(f"{label}: removed")
            return 0
        die("remove failed")
    if action == "trim":
        res = lib.run("memory", "trim", file, str(cap))
        sys.stderr.write(res.err)
        n = res.value()
        ok(f"{label}: trimmed {n} oldest entry(ies) (now {lib.run('memory', 'chars', file).value()}/{cap})")
        return 0
    die(f"memory: unknown action '{action}' (read|add|replace|remove|trim)")
