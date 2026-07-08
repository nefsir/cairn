import json

NAME = "review-internals"

# Golden master for `cairn review` (Layer B, the loop's heart).
# Exercises: --dry-run (+ --model), unknown-option die, missing-transcript die,
# the LIVE claude path (guard=0) with the deterministic claude shim capturing the
# redacted transcript on stdin, the discover-by-cwd path, the CAIRN_REVIEW_HOOK
# recursion guard (no-op exit 0), the --hook stdin-JSON path, and the claude
# failure path (rc=2). The seeded transcript carries one of every secret shape
# cairn's redactor knows (sk-/ghp_/AKIA/Bearer/PEM); the shim's per-call
# .claude-stdin.N files are snapshotted, so the redaction is pinned as a golden
# master and any regression in the flatten/redact pipeline diverges the port.


def _transcript(home):
    # A realistic session with seeded secrets. cwd == $HOME so the discover-by-cwd
    # path (review with no args) matches this transcript deterministically.
    lines = [
        {"type": "user", "cwd": home, "message": {"role": "user", "content":
            "Deploy creds: openai key sk-1234567890abcdefghijABCDEF and "
            "aws AKIA0123456789ABCDEF please store them"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text":
                "Using github token ghp_0123456789abcdefghijABCDEFGHIJ012345 and "
                "header Authorization: Bearer abcDEF0123456789xyz to push."},
            {"type": "tool_use", "name": "Bash", "input": {"command":
                "curl -H 'Authorization: Bearer abcDEF0123456789xyz' https://api.example"}},
        ]}},
        {"type": "user", "message": {"role": "user", "content":
            "deploy key below:\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n"
            "KUpRKfFLfRYC9AIBQ==\n"
            "-----END RSA PRIVATE KEY-----\ndone"}},
    ]
    return "\n".join(json.dumps(l) for l in lines) + "\n"


def run(ctx):
    rel = "projects/proj-sandbox/session.jsonl"
    ctx.seed(rel, _transcript(str(ctx.home)))
    t = str(ctx.claude_dir / rel)
    missing = str(ctx.claude_dir / "projects/proj-sandbox/does-not-exist.jsonl")

    # 1. install with hooks — wires SessionEnd `review --hook >> review-hook.log`
    #    into settings.json and git-inits skills/ (needed for the commit/telemetry
    #    path the live review exercises).
    ctx.run("install", "--enable-hooks")

    # 2-3. dry-run: no model call, prints transcript path + flattened char count +
    #      model. Second run proves the --model flag flows into the summary.
    ctx.run("review", "--dry-run", t)
    ctx.run("review", "--dry-run", "--model", "opus", t)

    # 4. unknown option -> die (exit 1) during arg parse, before any log write.
    ctx.run("review", "--bogus")

    # 5. explicit but missing transcript -> "no transcript found" + die (exit 1).
    ctx.run("review", missing)

    # 6. LIVE review (guard=0): flatten+redact -> claude shim (guard=1 on its env);
    #    the shim records the redacted stdin (.claude-stdin.1) and cairn commits/
    #    records via skills_commit. Nothing is staged, so no new commit — the
    #    golden master captures the redacted stdin + review.log lines.
    ctx.run("review", t)

    # 7. discover-by-cwd: no transcript arg -> newest session under $PWD (==$HOME).
    #    The seeded cwd matches, so this deterministically resolves to our fixture
    #    and runs the live path again (.claude-stdin.2).
    ctx.run("review")

    # 8. recursion guard: `review` (hook=0) with CAIRN_REVIEW_HOOK preset must
    #    no-op exit 0 — no model call, no output.
    ctx.run("review", env={"CAIRN_REVIEW_HOOK": "1"})

    # 9. --hook path: transcript_path arrives as a JSON hook payload on stdin
    #    (what the SessionEnd hook feeds). Runs the live review (.claude-stdin.3).
    ctx.run("review", "--hook", stdin=json.dumps({"transcript_path": t}))

    # 10. failure path: claude exits 2 ("deterministic boom"); review still records
    #     the stdin (.claude-stdin.4), logs "claude exited 2", warns, returns 0.
    ctx.run("review", t, env={"CAIRN_SHIM_CLAUDE_RC": "2"})
