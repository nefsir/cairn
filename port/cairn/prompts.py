"""Model prompts for the backfill layer — byte-identical to bash (EXTRACT/AGG/SYN/
REFINE). Passed as the claude -p prompt, logged verbatim by the harness shim."""

EXTRACT_PROMPT = """You are mining a single Claude Code session transcript (on stdin) for
REUSABLE skills. A skill is worth proposing only if the session shows a
non-trivial procedure, debugging pattern, or hard-won convention that would
plausibly recur. Ignore one-off trivia and project-specific details that will
not generalize.

Output ONLY JSON Lines: zero or more objects, one per line, no prose, no fences.
Each object:
{"name":"kebab-case-name","description":"what it does + concrete Use-when triggers (<=1024 chars)","evidence":"1-2 sentences why it is reusable","procedure":"terse step outline"}
If nothing is worth a skill, output nothing."""

AGG_PROMPT = """You are given candidate skills as JSON Lines on stdin, mined from many
Claude Code sessions. Produce a Markdown review report that clusters near-
duplicates into one proposed skill each, ranks by how often the pattern recurred,
and for each gives a kebab-case name, a tight description with concrete Use-when
triggers, supporting session count, and a one-line procedure. Prefer a few
class-level umbrellas over many narrow siblings. End each with: /skill-new <name>
"<purpose>". Drop weak one-offs. Output Markdown only."""

SYN_PROMPT = """These candidate skills (JSON on stdin) were mined from many sessions and
mechanically grouped because their triggers overlap. Synthesize ONE proposed
skill: a kebab-case name; a tight description (<=1024 chars) that is the UNION of
the distinct triggers, deduplicated, with concrete "Use when ..." phrasing (not a
concatenation); a short numbered procedure; and a final line "Supported by: N
candidate(s)". Begin with "### <name>". If the group is clearly NOT one coherent
skill, emit the best 1-2 distinct proposals. Output Markdown only, no fences."""

REFINE_PROMPT = """You are given several proposed Claude Code skills (Markdown, each starts
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
Separate proposals with a line containing only ---. Markdown only, no fences."""
