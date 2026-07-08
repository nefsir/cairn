NAME = "lint-frontmatter-validation"
# Exercises the `cairn lint` command layer (cmd_lint -> lib/validate.py):
#   - bare state: `lint` with no skills dir            -> die "no skills dir", rc 1
#   - `lint` (all) PASS: only the bundled skill present -> "all skills: valid", rc 0
#   - `lint <name>` (single) PASS                        -> "<name>: frontmatter valid", rc 0
#   - every FAIL issue type from validate.py, seeded with ABSOLUTE content:
#       missing 'name', missing 'description', empty body,
#       name > 64 chars, description > 1024 chars
#   - `lint <name>` (single) FAIL, both missing-description and empty-body
#   - `lint` (all) FAIL: per-skill issues, sorted, rc 1
#   - `lint <name>` on a non-existent skill              -> die "no skill", rc 1
# Asserts stdout/stderr format + exit codes AND the resulting tree (harness diffs
# the whole $CLAUDE_DIR: seeded skills stay untracked since lint never commits).


def run(ctx):
    # 1. bare / uninstalled: no $CLAUDE_DIR/skills yet -> die, rc 1 (stderr)
    ctx.run("lint")

    # 2. install: creates skills/ with the single bundled skill (skill-extraction)
    ctx.run("install")

    # 3. lint (all) PASS: only the valid bundled skill exists -> rc 0
    ctx.run("lint")

    # 4. lint <name> (single) PASS on the bundled skill -> rc 0
    ctx.run("lint", "skill-extraction")

    # 5. seed one broken skill per validate.py issue type (ASCII slug dirs).
    #    Frontmatter content is absolute — no dates/counts depend on run time.

    # missing 'name' (description + body present)
    ctx.seed("skills/bad-noname/SKILL.md",
             "---\n"
             "description: Has a description and a body but no name field at all.\n"
             "---\n"
             "\n"
             "Body text present here.\n")

    # missing 'description' (name + body present)
    ctx.seed("skills/bad-nodesc/SKILL.md",
             "---\n"
             "name: bad-nodesc\n"
             "---\n"
             "\n"
             "This skill has a name and a body, but no description field.\n")

    # empty body (name + description present, nothing after frontmatter)
    ctx.seed("skills/bad-nobody/SKILL.md",
             "---\n"
             "name: bad-nobody\n"
             "description: A valid description, but the body below is empty.\n"
             "---\n")

    # name > 64 chars (70 'a's); description + body valid so only the name fails
    ctx.seed("skills/bad-longname/SKILL.md",
             "---\n"
             "name: " + ("a" * 70) + "\n"
             "description: A perfectly valid one-line description under the cap.\n"
             "---\n"
             "\n"
             "Body text present here.\n")

    # description > 1024 chars (1100 'a's); name + body valid so only desc fails
    ctx.seed("skills/bad-longdesc/SKILL.md",
             "---\n"
             "name: bad-longdesc\n"
             "description: " + ("a" * 1100) + "\n"
             "---\n"
             "\n"
             "Body text present here.\n")

    # 6. lint <name> (single) FAIL: missing description -> warn + indented issue, rc 1
    ctx.run("lint", "bad-nodesc")

    # 7. lint <name> (single) FAIL: empty body -> warn + indented issue, rc 1
    ctx.run("lint", "bad-nobody")

    # 8. lint (all) FAIL: all five broken skills reported (sorted), skill-extraction
    #    stays silent (valid) -> rc 1
    ctx.run("lint")

    # 9. lint on a name that resolves to nothing -> die "no skill '...'", rc 1 (stderr)
    ctx.run("lint", "no-such-skill")
