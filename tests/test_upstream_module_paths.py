"""No file in this fork may name the upstream engine's module, its source
path, or its agents by their upstream spelling.

This fork's package was renamed from `pegasus` to `darq`, so `pegasus.core`,
`pegasus.cli` and their siblings name modules that do not exist here. A
reference to one is a dead pointer: a reader following it finds nothing, and
so does anyone grepping for the module a docstring claims to explain. The
same fork also renamed its five generic agents, `pegasus-<role>` to
`darq-<role>`, plus one that follows no rule, `king-pegasus` to
`arquitecto-darq` -- a stray upstream agent name is the same dead pointer,
aimed at an agent this fork does not ship.

The rename itself was mechanical and complete. What keeps re-introducing
these is transport: a fix or a file authored upstream and brought over with
`git cherry-pick` carries upstream's own prose, and upstream correctly names
its own modules, its own source path, and its own agents. The cherry-pick
applies cleanly -- git tracks the directory rename -- and the stale spelling
rides in with it, unflagged, because the brand guardians in
`test_architecture.py` scan bundled adapter assets rather than engine source
prose, and, until this module grew agent-name coverage, nothing scanned
Markdown content at all. The first transport after the fork introduced
exactly one dotted-path leftover, in `cli.py`'s `_NUMERIC_VERSION` docstring.

This gate covers four forms of the same defect. `docs/transporte-desde-
pegasus.md` keeps the same table, kept in sync by hand:

1. A dotted module path -- `pegasus.core`, `pegasus.__main__`. Matched by
   `UPSTREAM_MODULE_PATH`, on the dot; see that pattern's own docstring below
   for why enumerating modules was tried first and abandoned.
2. The renamed source path split into separate string literals, the way a
   transport actually carries it one segment at a time --
   `Path(...) / "src" / "pegasus"`, `("src", "pegasus", ...)`,
   `os.path.join(..., "pegasus", ...)`, `.joinpath("pegasus")`, and the same
   shapes wrapped across several lines the way a formatter does it. Matched
   by `SPLIT_UPSTREAM_PATH_SEGMENT`.
3. That same path written as one string, including inside a regex, with or
   without the `src/` prefix -- `"src/pegasus/content/skills/"`,
   `r"src/pegasus/content"`, `"pegasus/content/skills/"`. Matched by
   `UPSTREAM_PATH_STRING`.
4. An upstream agent's own name -- `pegasus-orchestrator` and its three
   siblings, plus `king-pegasus` -- whether it appears in a file's own prose
   (`UPSTREAM_AGENT_NAME`) or as a file's own filename, with a body that
   never repeats it (`_agent_filename_offenders`, scoped to
   `src/darq/content/agents/`, the one place a bare filename carries the
   defect on its own).

An adversarial review of the first version of this gate found real gaps in
all four directions at once, folded in here rather than kept as a separate
history: `docs/` was not scanned at all, even though `docs/transporte-desde-
pegasus.md` itself proves a Markdown file can quote any of these four shapes
verbatim as a worked example (`_scanned_files` below now reads `.py` and
`.md` across `docs/` too, alongside `src/darq`, `tests` and `tools`); form 2
missed `os.path.join`/`.joinpath` calls and a segment split across lines by
a formatter; form 3 missed the same path spelled without its `src/` prefix;
and form 4 missed a bare filename. Each fix is explained where its pattern
or check is defined below, and each closed gap has a probe that failed
against the pre-fix pattern and passes against the current one.

Each pattern stays deliberately narrow to its own form, the same way
`UPSTREAM_MODULE_PATH` stays narrow to the dot: every wire identifier that
must keep saying `pegasus` forever -- the journal and report schemas, the
`pegasus_version`/`pegasus_installed` keys, the `PEGASUS_*` environment
variables, `.pegasus-` files, `pegasus-doctor`, `/pegasus/catalog-build`, and
the rest the runbook's table enumerates -- separates the word with an
underscore, a slash, or a hyphen in a shape none of the four patterns match,
so none of them needs an exemption for it. Prose that merely names the
upstream product does not match either; that remains a separate concern this
gate does not judge.

Two properties keep the gate honest about itself. A versioned wire id
(`pegasus/<word>/v<digits>`) is not a path, however its middle word is spelled
(see `UPSTREAM_PATH_STRING`). And an exemption is a list of occurrences, not a
file: `EXEMPT_OCCURRENCES` pins what each exempt file may still say and fails
when it gains one or loses one (`ExemptionAllowlistTest`).

Two forms of split still escape, on purpose rather than by oversight, and
are measured in `test_a_nested_call_is_not_caught` and
`test_a_wholly_new_upstream_agent_role_is_not_caught`: a `"pegasus"`
argument buried behind a nested call inside `os.path.join(...)`/
`.joinpath(...)` (the non-greedy scan between the call's own parentheses
stops at the first `)`, which may belong to the nested call, not the outer
one), and an upstream agent role with no DARQ counterpart yet, which
derivation has nothing to read a role off of.
"""
from __future__ import annotations

import re
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from darq.core.identity import parse as _parse_identity

ROOT = Path(__file__).resolve().parent.parent

#: A dotted path into the upstream package: `pegasus.` followed by anything
#: that can start a Python identifier.
#:
#: This deliberately does not enumerate the modules. It did at first --
#: `(core|adapters|infra|ports|tui|cli|content)` -- and an adversarial review
#: found the hole immediately: the list left out `__main__`, a real module
#: upstream that upstream's own `test_version_guard.py` imports by name, so a
#: transported reference to it would have ridden in unflagged. An enumeration
#: of what exists is a list somebody has to remember to widen, and the whole
#: reason this gate exists is that nobody remembers.
#:
#: Matching on the dot is what keeps it safe. Every identifier that must keep
#: saying `pegasus` forever separates the word with an underscore, a slash or
#: a hyphen -- `pegasus_version`, `pegasus/cli-report/v1`,
#: `pegasus-harness/journal/v4`, `PEGASUS_SKILL_ROOTS`, `.pegasus-`,
#: `pegasus-doctor` -- and never with a dot followed by a letter, so none of
#: them can match here no matter how the engine grows.
#: Spellings where `pegasus.` IS followed by a letter and must survive anyway,
#: with the reason each one is here. Today there is one: `pegasus.md`, the
#: identity-blind default filename `Layout` carries for the Claude Code system
#: prompt -- a wire spelling this engine keeps deliberately, documented in
#: `adapters/claudecode/layout.py` and in `test_architecture.py`'s own
#: allowlist. It is a filename, not a module path, and the dot in front of a
#: file extension is indistinguishable from the dot in front of a package.
#:
#: Enumerating the exceptions is the opposite bet from enumerating the
#: modules, and it is the right one for a gate. A missing module fails OPEN --
#: the defect ships unseen, which is exactly how `__main__` slipped past the
#: first version of this pattern. A missing exception fails CLOSED -- a benign
#: spelling gets flagged, somebody reads it, and it lands here with its reason
#: written down. A guardian should be wrong in the direction that gets looked at.
PROTECTED_DOTTED_SPELLINGS = ("md",)

UPSTREAM_MODULE_PATH = re.compile(
    r"\bpegasus\.(?!(?:" + "|".join(PROTECTED_DOTTED_SPELLINGS) + r")\b)[A-Za-z_]"
)

#: Form 2: the renamed source path, split into separate string literals the
#: way a transport actually carries it -- one segment per literal, so no
#: single literal ever spells the whole dotted-or-slashed path the first
#: pattern above would catch.
#:
#: Four shapes, all anchored on a `"pegasus"` (or `'pegasus'`) literal whose
#: quoted content is the bare word and nothing else:
#:
#: - Path division: a quote-delimited `pegasus` immediately touching a `/`,
#:   either side (`Path(...) / "src" / "pegasus"` or `"pegasus" / "content"`).
#:   The anchor is the `/`, not the word `"src"` -- a caller may already hold
#:   the source root in a variable (`SRC_DIR / "pegasus"`), and this still has
#:   to catch it.
#: - A literal `"src"` segment immediately followed by a literal `"pegasus"`
#:   segment, comma-separated, the shape a tuple or list builds a path from
#:   (`("src", "pegasus", "content")`). Anchored on `"src"` here, unlike the
#:   division case, because without it this would also flag
#:   `("pegasus", "harness", "balerdis")` in `tests/brand_fragments.py` --
#:   a data list of brand words, not a path. `\s` between the two segments
#:   matches a newline as readily as a space, so a formatter wrapping the
#:   tuple one element per line does not defeat this -- and this pattern is
#:   applied to a file's whole text (`_scanned_files`/`_offenders` below),
#:   never split into lines first, precisely so a match spanning lines is
#:   still seen as one match instead of two half-lines that never meet.
#: - `.joinpath("pegasus")`: an upstream agent review found this escapes the
#:   two shapes above (no `/` touches the literal, no `"src"` precedes it).
#:   Bounded to the call's own parentheses with a non-greedy `[^)]*?` on each
#:   side, so `"pegasus"` is matched at any argument position --
#:   `ROOT.joinpath("pegasus")`, `ROOT.joinpath("a", "pegasus", "b")`.
#: - `os.path.join(..., "pegasus", ...)`: the same shape and the same
#:   bounding, for the one other path-building call this fork's style guide
#:   does not forbid.
#:
#: All four anchors are why a bare `"pegasus"` on its own -- `_package_files
#: ("pegasus")`, `asset = "pegasus"`, `sys.argv = ['pegasus']` -- never
#: matches: none of those touch a `/`, follow a literal `"src"`, or sit
#: inside a `joinpath`/`os.path.join` call, so this pattern leaves them alone
#: exactly as it should. Whether a bare, unanchored `"pegasus"` literal like
#: the `sys.argv` one is itself stale prose is a separate question this gate
#: does not answer, the same way it does not judge prose that merely names
#: the product.
#:
#: What still escapes: a `"pegasus"` argument behind a nested call inside
#: `join`/`joinpath` -- `os.path.join(str(ROOT), "pegasus")` -- because the
#: non-greedy `[^)]*?` stops at the first `)`, which belongs to the nested
#: `str(ROOT)` call, not to `join`'s own closing paren, so the alternative
#: never reaches `"pegasus"` before giving up. Measured, not assumed, in
#: `NoSplitUpstreamPathSegmentTest.test_a_nested_call_is_not_caught`. Closing
#: this would need real paren balancing, which a guard built on `re` does not
#: do; nothing in this fork's current style nests a call inside a path join,
#: so the gap is accepted rather than chased with a heavier tool.
_SPLIT_UPSTREAM_PATH_SEGMENT_RE = re.compile(
    r'(["\'])pegasus\1\s*/'
    r'|/\s*(["\'])pegasus\2'
    r'|(["\'])src\3\s*,\s*(["\'])pegasus\4'
    r'|\.joinpath\([^)]*?(["\'])pegasus\5[^)]*?\)'
    r'|os\.path\.join\([^)]*?(["\'])pegasus\6[^)]*?\)'
)

_JOIN_OPENING = re.compile(r"\.joinpath\(|os\.path\.join\(")
_JOIN_RUN = re.compile(r"(?:\.joinpath\(|os\.path\.join\()[^)]*")
_PEGASUS_LITERAL = re.compile(r'(["\'])pegasus\1')
_DEAD_OPENING = "\x00"


class _LinearSplitSegmentPattern:
    """`_SPLIT_UPSTREAM_PATH_SEGMENT_RE` with the quadratic case removed.

    The `join`/`joinpath` alternatives scan from each opening to the next `)`.
    An opening that never closes, repeated n times, makes every attempt rescan
    the same tail: O(n^2). A regex cannot skip those attempts (the lookbehind
    that would anchor them needs a variable width), but the verdict is shared:
    an opening fails exactly when its run -- the text up to the next `)` --
    lacks a quoted `pegasus` or is not closed by a `)`, and any later opening
    in that run has a suffix of the same run, so it fails too. So a cheap
    pre-pass finds each run once, and in a failing run neutralises every
    opening (`(` -> NUL, same length, so offsets are unchanged); the original
    regex then runs unchanged over the masked text. A masked opening could
    never have matched, and the other alternatives cannot contain one, so the
    matches (text and offsets) are identical to the original's.
    """

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self._pattern = pattern

    @staticmethod
    def _mask(text: str) -> str:
        cuts: list[int] = []
        for run in _JOIN_RUN.finditer(text):
            end = run.end()
            closed = text.startswith(")", end)
            if closed and _PEGASUS_LITERAL.search(text, run.start(), end):
                continue
            cuts.extend(opening.end() - 1 for opening in _JOIN_OPENING.finditer(text, run.start(), end))
        if not cuts:
            return text
        chars = list(text)
        for index in cuts:
            chars[index] = _DEAD_OPENING
        return "".join(chars)

    def search(self, text: str) -> re.Match[str] | None:
        return self._pattern.search(self._mask(text))

    def finditer(self, text: str):
        return self._pattern.finditer(self._mask(text))


SPLIT_UPSTREAM_PATH_SEGMENT = _LinearSplitSegmentPattern(_SPLIT_UPSTREAM_PATH_SEGMENT_RE)

#: Form 3: the same renamed source path, written as one string instead of
#: split across literals -- including inside a regex, where `r"src/pegasus/
#: content"` is exactly as dangerous as the plain string, and exactly as
#: unflagged by the first two patterns, since neither a dot nor a lone
#: `"pegasus"` literal appears in it.
#:
#: First anchored on the literal substring `src/pegasus`. But an upstream
#: agent review found a path spelled without that prefix --
#: `SKILLS_DIR = "pegasus/content/skills/"`, relative to an already-known
#: root -- escapes it entirely, so the pattern also matches `pegasus/`
#: immediately followed by one of this fork's own top-level source
#: directories, derived from the tree exactly the way agent roles are
#: derived below, never hand-typed: `pegasus/content`, `pegasus/core`,
#: `pegasus/adapters`, and so on, whatever `src/darq/` currently has. Real
#: package directories, not files, because a top-level *file* reference
#: (`pegasus/cli.py`, `pegasus/__main__`) is already the dotted form
#: `UPSTREAM_MODULE_PATH` catches, or would need a `.py` suffix this pattern
#: does not add on purpose -- adding it back would only re-derive a fact
#: `UPSTREAM_MODULE_PATH` already owns.
#:
#: Neither anchor matches `pegasus/` alone: `pegasus/capability-manifest/v1`,
#: `pegasus/model-assignment/v1`, `pegasus/artifact-catalog/v4`, `pegasus/
#: cli-report/v1` are live wire prefixes that must never be touched, and
#: `/pegasus/catalog-build` proves the slash can even come first -- none of
#: their second segments (`capability-manifest`, `model-assignment`,
#: `artifact-catalog`, `cli-report`, `catalog-build`) is a real directory
#: under `src/darq/`, and none of them is preceded by `src/`, so neither
#: branch of this pattern can ever reach them. The lookaround on each side of
#: the directory-name branch (`(?<![\w-])` / `(?![\w-])`) keeps a directory
#: name from matching as a mere prefix of a longer, unrelated segment the
#: same way `pegasus-doctor` must never trip on a bare `pegasus`.
_DARQ_SOURCE_SUBDIRECTORIES = sorted(
    path.name
    for path in (ROOT / "src" / "darq").iterdir()
    if path.is_dir() and path.name != "__pycache__"
)

#: The directory-name branch also refuses a versioned wire id,
#: `pegasus/<word>/v<digits>` (`pegasus/core/v1`, `pegasus/ports/v2`). Its
#: words come from `src/darq/`, so a frozen schema family that happens to be
#: named like a package would otherwise be reported as a source path -- a
#: false positive that fails closed on something nobody may rename. The
#: refusal is exactly the segment `/v<digits>` followed by anything that is
#: not a path continuation (`[\w./-]`): `pegasus/core/v1.py`, `pegasus/core/
#: v1/` and `pegasus/core/v1x` are still paths as code would build them, and
#: the `src/pegasus` branch has no such refusal at all, since a `src/` prefix
#: is never a schema id. A sentence that ends right after the id (`.../v1.`)
#: stays flagged, on purpose: it fails closed and is rewritten.
UPSTREAM_PATH_STRING = re.compile(
    r"src/pegasus\b"
    r"|(?<![\w-])pegasus/(?:" + "|".join(_DARQ_SOURCE_SUBDIRECTORIES) + r")(?![\w-])"
    r"(?!/v\d+(?![\w./-]))"
)

#: Form 4: an upstream agent's own name. Five of the six are derived, never
#: typed by hand, from the same two facts a distribution already owns: its
#: `program_name` (`identity.json`, read the same way `core.identity.parse`
#: reads it for the running binary) and the agent files this fork actually
#: ships (`src/darq/content/agents/*.md`). Every DARQ agent that follows the
#: `<program_name>-<role>` shape has an upstream sibling that follows the
#: same shape with `pegasus` in place of `program_name` -- `darq-orchestrator`
#: implies `pegasus-orchestrator` exists upstream, whether or not this file
#: has ever seen it -- so deriving the forbidden name from the shipped one
#: needs no enumeration of upstream's roster, the same reason
#: `UPSTREAM_MODULE_PATH` matches on the dot instead of a module list.
_IDENTITY_PATH = ROOT / "src" / "darq" / "identity.json"
_AGENTS_DIR = ROOT / "src" / "darq" / "content" / "agents"


def _darq_program_name() -> str:
    return _parse_identity(_IDENTITY_PATH.read_bytes()).program_name


def _derived_upstream_agent_names() -> frozenset[str]:
    program_name = _darq_program_name()
    prefix = f"{program_name}-"
    roles = (
        path.stem[len(prefix):]
        for path in _AGENTS_DIR.glob("*.md")
        if path.stem.startswith(prefix)
    )
    return frozenset(f"pegasus-{role}" for role in roles)


#: The one DARQ agent name derivation cannot reach: `arquitecto-darq` puts
#: the role before the program name, the reverse of every other agent, and
#: its upstream counterpart, `king-pegasus`, is not `<role>-pegasus` either --
#: it shares no word with `arquitecto-darq` at all. Nothing in the tree can
#: mechanically produce one from the other, so it is typed here by hand, with
#: the DARQ file it corresponds to named alongside it for a human to check.
UPSTREAM_AGENT_NAMES_EXPLICIT = frozenset({
    "king-pegasus",  # <-> src/darq/content/agents/arquitecto-darq.md
})

UPSTREAM_AGENT_NAMES = _derived_upstream_agent_names() | UPSTREAM_AGENT_NAMES_EXPLICIT

UPSTREAM_AGENT_NAME = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in sorted(UPSTREAM_AGENT_NAMES)) + r")\b"
)


def _agent_filename_offenders() -> list[str]:
    """A file's own name can be an upstream agent's, with a body that never
    repeats it anywhere -- an upstream agent review found this escapes
    `UPSTREAM_AGENT_NAME` entirely, since that pattern only ever reads a
    file's content, never its filename. Scoped to `_AGENTS_DIR` alone: it is
    the one place in this fork where a bare filename, not its content,
    carries this exact defect on its own -- a skill or a doc named
    `pegasus-orchestrator.md` would be strange, but an *agent* named that is
    upstream's own agent, wholesale, filename included."""
    return sorted(
        str(path.relative_to(ROOT))
        for path in _AGENTS_DIR.glob("*.md")
        if path.stem in UPSTREAM_AGENT_NAMES
    )


SCANNED_DIRS = ("src/darq", "tests", "tools", "docs")

#: Every file whose `pegasus.*` paths, split segments, path strings or
#: agent-name mentions are deliberate, mapped to a substring that must still
#: be in it -- the reason it is exempt rather than fixed, checked rather than
#: assumed, the same shape `PROTECTED_DOTTED_SPELLINGS` uses above. Reused by
#: all four checks below, rather than one exemption list per pattern, so a
#: fifth check added later inherits the same two exact paths instead of
#: starting its own list.
#:
#: - `test_architecture.py` builds throwaway packages named `pegasus` on
#:   purpose (its layering probes key off `source.name`, and the probe has
#:   to reproduce that exact name to exercise it), and it narrates a real,
#:   fixed `pegasus-orchestrator` regression by name in its own docstrings.
#:   Every one of those strings is the probe's input or the incident's
#:   record, never a pointer at a real module, path or agent.
#: - `docs/transporte-desde-pegasus.md` is this gate's own runbook: the
#:   section documenting what each pattern catches quotes every one of the
#:   four forms verbatim as a worked example, which is exactly the prose an
#:   adversarial review used to show `docs/` was not scanned at all. The
#:   fix is scanning `docs/` (see `SCANNED_DIRS` above), and the runbook's
#:   own examples are the one place in `docs/` that legitimately keeps
#:   saying them.
#:
#: Listed as exact paths, never a directory, so no third file can join
#: either one in silence -- see `ScanScopeTest.test_scanning_docs_needs_only_
#: the_runbooks_own_exemption` for the check that no other file under
#: `docs/` needed one.
EXEMPT = {
    "tests/test_architecture.py": "_write_scratch_pegasus",
    "docs/transporte-desde-pegasus.md": "Segmentos separados",
}

_FORM_PATTERNS = {
    "UPSTREAM_MODULE_PATH": UPSTREAM_MODULE_PATH,
    "SPLIT_UPSTREAM_PATH_SEGMENT": SPLIT_UPSTREAM_PATH_SEGMENT,
    "UPSTREAM_PATH_STRING": UPSTREAM_PATH_STRING,
    "UPSTREAM_AGENT_NAME": UPSTREAM_AGENT_NAME,
}

#: What an exempt file is still allowed to say, as a multiset of
#: `(pattern name, matched text)` -> how many times. An exemption is the
#: justified occurrences, not the file: `_scanned_files` still skips an exempt
#: file for the four whole-tree checks, but `ExemptionAllowlistTest` runs the
#: same four patterns over it and requires the result to equal this table
#: exactly. A new match fails (an `added` entry); an allowed one that
#: disappears fails too (a `vanished` entry), so a stale line cannot hide the
#: next offender. Line numbers are not part of the key, so editing around an
#: allowed line does not break it; the matched text, with the few trailing
#: identifier characters the match stops short of, is.
#:
#: Why each is allowed, per file, is the paragraph above `EXEMPT`: the probe
#: packages named `pegasus` and the narrated `pegasus-orchestrator` incident
#: in `test_architecture.py`, and the runbook's own worked examples.
EXEMPT_OCCURRENCES = {
    "tests/test_architecture.py": Counter({
        ("SPLIT_UPSTREAM_PATH_SEGMENT", '"pegasus"/'): 2,
        ("SPLIT_UPSTREAM_PATH_SEGMENT", '/ "pegasus"'): 1,
        ("UPSTREAM_AGENT_NAME", "pegasus-orchestrator"): 3,
        ("UPSTREAM_MODULE_PATH", "pegasus.adapters.opencode"): 2,
        ("UPSTREAM_MODULE_PATH", "pegasus.cli"): 2,
        ("UPSTREAM_MODULE_PATH", "pegasus.infra"): 4,
        ("UPSTREAM_MODULE_PATH", "pegasus.ports"): 1,
        ("UPSTREAM_PATH_STRING", "pegasus/core"): 1,
    }),
    "docs/transporte-desde-pegasus.md": Counter({
        ("SPLIT_UPSTREAM_PATH_SEGMENT", '.joinpath("pegasus")'): 1,
        ("SPLIT_UPSTREAM_PATH_SEGMENT", '/ "pegasus"'): 1,
        ("SPLIT_UPSTREAM_PATH_SEGMENT", 'os.path.join(..., "pegasus", ...)'): 1,
        ("UPSTREAM_AGENT_NAME", "king-pegasus"): 3,
        ("UPSTREAM_AGENT_NAME", "pegasus-explorer.md"): 1,
        ("UPSTREAM_AGENT_NAME", "pegasus-orchestrator"): 4,
        ("UPSTREAM_AGENT_NAME", "pegasus-orchestrator.md"): 1,
        ("UPSTREAM_MODULE_PATH", "pegasus.core.identity"): 1,
        ("UPSTREAM_MODULE_PATH", "pegasus.tui"): 1,
        ("UPSTREAM_MODULE_PATH", "pegasus.tui.app"): 1,
        ("UPSTREAM_PATH_STRING", "pegasus/content"): 1,
        ("UPSTREAM_PATH_STRING", "pegasus/core"): 3,  # the wire-id section's counter-examples
        ("UPSTREAM_PATH_STRING", "src/pegasus"): 3,
    }),
}

_IDENTIFIER_TAIL = re.compile(r"\w*(?:\.\w+)*")


def _occurrences(text: str) -> Counter:
    """Every match of the four patterns in `text`, keyed by pattern name and
    matched text, extended over any identifier characters that follow so the
    dotted-path pattern, which matches only `pegasus.i`, is recorded as
    `pegasus.infra`. Linear: one `finditer` per pattern plus a bounded tail."""
    found: Counter = Counter()
    for name, pattern in _FORM_PATTERNS.items():
        for match in pattern.finditer(text):
            end = _IDENTIFIER_TAIL.match(text, match.end()).end()
            found[(name, text[match.start():end])] += 1
    return found


def _occurrence_drift(text: str, allowed: Counter) -> tuple[Counter, Counter]:
    """`(added, vanished)`: matches in `text` beyond `allowed`, and allowed
    ones `text` no longer has. Both empty means the exemption is exact."""
    found = _occurrences(text)
    return found - allowed, allowed - found

#: This file is excluded from its own scan. Its docstring explains the shapes
#: it forbids and its tests feed those shapes to the patterns on purpose, so
#: scanning itself would report its own prose as the defect -- the failure
#: mode where a detector measures something it brought along itself.
SELF = "tests/test_upstream_module_paths.py"


def _scanned_files() -> list[Path]:
    """`.py` and `.md`, across every directory in `SCANNED_DIRS`, for all
    four checks alike. This used to split into a `.py`-only listing for the
    first three forms and a `.py`-plus-`.md` listing for agent names, on the
    assumption that a dotted path, a split path segment and a one-string path
    are Python-literal syntax that cannot occur in prose. `docs/transporte-
    desde-pegasus.md` disproves that assumption by existing: it quotes all
    three as backtick-code examples in ordinary Markdown prose, which is
    precisely how an adversarial review found `docs/` unscanned in the first
    place. One listing, read by all four checks, so a fifth form added later
    cannot silently inherit the narrower of the two by accident.
    """
    return sorted(
        path
        for directory in SCANNED_DIRS
        for extension in (".py", ".md")
        for path in (ROOT / directory).rglob(f"*{extension}")
        if "__pycache__" not in path.parts
        and str(path.relative_to(ROOT)) not in EXEMPT
        and str(path.relative_to(ROOT)) != SELF
    )


def _offenders(pattern: "re.Pattern[str] | _LinearSplitSegmentPattern") -> dict[str, list[str]]:
    """Every scanned file with at least one match, each paired with the
    lines it matched on.

    Searches a file's whole text in one pass, never one line at a time: a
    match spanning a newline -- `SPLIT_UPSTREAM_PATH_SEGMENT`'s `"src",` /
    `"pegasus",` tuple case, wrapped one element per line the way a
    formatter does it -- starts on one physical line and ends on another, so
    a line-by-line search never sees either half as a whole match. Line
    numbers are recovered from the match's own start offset
    (`text.count("\\n", 0, start)`), and de-duplicated per line -- a line
    with two matches (`pegasus-orchestrator` and `king-pegasus` on the same
    row of a table) is reported once, the same way the original line-based
    scan only ever reported a line once no matter how many times a pattern
    matched inside it.
    """
    offenders: dict[str, list[str]] = {}
    for path in _scanned_files():
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        matched_lines = sorted({text.count("\n", 0, match.start()) + 1 for match in pattern.finditer(text)})
        if matched_lines:
            offenders[str(path.relative_to(ROOT))] = [
                f"{line_number}: {lines[line_number - 1].strip()}" for line_number in matched_lines
            ]
    return offenders


class ScanScopeTest(unittest.TestCase):
    """`docs/` joined `SCANNED_DIRS`, and the two exemptions are now checked
    in one place: an adversarial review found `docs/` unscanned entirely, and
    proved it with a Markdown file quoting an upstream agent name and a
    one-string path -- both forms this gate already had patterns for, just
    never pointed at `docs/`."""

    def test_there_are_files_to_scan(self):
        self.assertTrue(_scanned_files(), "no files found -- the scan target drifted")

    def test_docs_directory_is_scanned(self):
        self.assertTrue(
            any(str(path.relative_to(ROOT)).startswith("docs/") for path in _scanned_files()),
            "no file under docs/ made it into the scan -- SCANNED_DIRS drifted",
        )

    def test_scanning_docs_needs_only_the_runbooks_own_exemption(self):
        """Bringing `docs/` into scope could have meant exempting most of
        it -- an ADR or a handoff note narrating `pegasus-orchestrator` by
        name, say. It does not: searched directly, bypassing `EXEMPT`, every
        one of the four patterns touches exactly one file anywhere under
        `docs/` -- this gate's own runbook, quoting its own worked examples.
        If a second file under `docs/` ever needs joining `EXEMPT`, this is
        the test that turns red and says so, instead of the join happening
        silently the way the missing scan itself once did."""
        patterns = (
            UPSTREAM_MODULE_PATH,
            SPLIT_UPSTREAM_PATH_SEGMENT,
            UPSTREAM_PATH_STRING,
            UPSTREAM_AGENT_NAME,
        )
        touched = set()
        for extension in (".py", ".md"):
            for path in (ROOT / "docs").rglob(f"*{extension}"):
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                if any(pattern.search(text) for pattern in patterns):
                    touched.add(str(path.relative_to(ROOT)))
        self.assertEqual(touched, {"docs/transporte-desde-pegasus.md"})

    def test_every_exemption_still_needs_it(self):
        """An exemption may not outlive its reason: each exempt file must
        still exist and still contain the substring that was its reason for
        being here, or it is dead weight hiding whatever lands there next."""
        for relative, needle in sorted(EXEMPT.items()):
            path = ROOT / relative
            with self.subTest(path=relative):
                self.assertTrue(path.is_file(), f"{relative} does not exist")
                self.assertIn(
                    needle,
                    path.read_text(encoding="utf-8"),
                    f"{relative} no longer contains {needle!r} -- its exemption may be dead weight",
                )


class ExemptionAllowlistTest(unittest.TestCase):
    """An exempt file is not invisible: it is scanned like any other, and the
    only matches it may keep are the ones `EXEMPT_OCCURRENCES` lists, each
    with the count it is expected to have."""

    SAMPLE = (
        "A probe: `pegasus.infra.foo` and again pegasus.infra.foo.\n"
        'child = ROOT / "pegasus"\n'
        "Narrates `pegasus-orchestrator`.\n"
    )
    ALLOWED = Counter({
        ("UPSTREAM_MODULE_PATH", "pegasus.infra.foo"): 2,
        ("SPLIT_UPSTREAM_PATH_SEGMENT", '/ "pegasus"'): 1,
        ("UPSTREAM_AGENT_NAME", "pegasus-orchestrator"): 1,
    })

    def test_the_sample_matches_its_allowlist_exactly(self):
        added, vanished = _occurrence_drift(self.SAMPLE, self.ALLOWED)
        self.assertEqual((added, vanished), (Counter(), Counter()))

    def test_a_new_offender_in_an_exempt_file_is_reported(self):
        for extra in (
            "see `pegasus.core.identity`\n",
            'p = Path("a") / "src" / "pegasus"\n',
            'p = "src/pegasus/content/skills/"\n',
            "delegate to king-pegasus\n",
            "a third pegasus.infra.foo\n",
        ):
            with self.subTest(extra=extra):
                added, vanished = _occurrence_drift(self.SAMPLE + extra, self.ALLOWED)
                self.assertTrue(added)
                self.assertFalse(vanished)

    def test_an_allowed_occurrence_that_disappears_is_reported(self):
        without = self.SAMPLE.replace("Narrates `pegasus-orchestrator`.\n", "")
        added, vanished = _occurrence_drift(without, self.ALLOWED)
        self.assertFalse(added)
        self.assertEqual(vanished, Counter({("UPSTREAM_AGENT_NAME", "pegasus-orchestrator"): 1}))

    def test_a_swap_that_keeps_the_count_is_still_reported(self):
        swapped = self.SAMPLE.replace("pegasus-orchestrator", "king-pegasus")
        added, vanished = _occurrence_drift(swapped, self.ALLOWED)
        self.assertEqual(added, Counter({("UPSTREAM_AGENT_NAME", "king-pegasus"): 1}))
        self.assertEqual(vanished, Counter({("UPSTREAM_AGENT_NAME", "pegasus-orchestrator"): 1}))

    def test_every_exempt_file_has_an_allowlist_and_the_reverse(self):
        self.assertEqual(set(EXEMPT), set(EXEMPT_OCCURRENCES))

    def test_every_exempt_file_keeps_exactly_its_allowed_occurrences(self):
        for relative in sorted(EXEMPT):
            with self.subTest(path=relative):
                text = (ROOT / relative).read_text(encoding="utf-8")
                added, vanished = _occurrence_drift(text, EXEMPT_OCCURRENCES[relative])
                self.assertEqual(
                    (added, vanished),
                    (Counter(), Counter()),
                    f"{relative} gained an unlocalized upstream name (added) or lost one "
                    "its allowlist still lists (vanished) -- localize the new one, or list it "
                    "in EXEMPT_OCCURRENCES with its reason; drop the stale entry",
                )


class NoUpstreamModulePathTest(unittest.TestCase):
    def test_no_file_names_an_upstream_module(self):
        offenders = _offenders(UPSTREAM_MODULE_PATH)
        self.assertEqual(
            offenders,
            {},
            "a file names a module path from the upstream engine, which does not exist in this fork -- "
            f"this is what a transported commit brings in with it; rename it to `darq.*`: {offenders}",
        )

    def test_a_transported_pointer_would_be_flagged(self):
        """The gate catches the exact shape the first transport introduced,
        and the dunder modules an enumerated pattern left out."""
        for prose in (
            "`SAFE_VERSION` (`pegasus.core.identity`) is wider",
            "from pegasus.__main__ import guard",
            "see `pegasus.__init__`",
            "a module added upstream tomorrow: pegasus.whatever",
        ):
            with self.subTest(prose=prose):
                self.assertTrue(UPSTREAM_MODULE_PATH.search(prose))

    def test_the_protected_filename_is_not_flagged(self):
        """`pegasus.md` is a filename this engine keeps on purpose, not a
        pointer at a module, and it has to survive the widened pattern."""
        self.assertIsNone(UPSTREAM_MODULE_PATH.search('SYSTEM_PROMPT = "pegasus.md"'))

    def test_every_protected_spelling_still_appears_in_the_tree(self):
        """An exception may not outlive its reason: each protected spelling
        must still be somewhere in the engine source, or it is dead weight
        widening the hole for whatever lands on that spelling next."""
        sources = "\n".join(
            path.read_text(encoding="utf-8") for path in (ROOT / "src/darq").rglob("*.py")
        )
        for suffix in PROTECTED_DOTTED_SPELLINGS:
            with self.subTest(suffix=suffix):
                self.assertIn(f"pegasus.{suffix}", sources, f"pegasus.{suffix} is no longer in the tree")

    def test_a_wire_identifier_is_not_flagged(self):
        """Every identifier that must keep saying `pegasus` forever survives."""
        for identifier in (
            'SCHEMA = "pegasus-harness/journal/v4"',
            '"pegasus/cli-report/v1"',
            '"pegasus_version": runtime.identity.version,',
            'entry["pegasus_installed"]',
            'PEGASUS_SKILL_REGISTRY_BIN',
            'TEMPORARY_PREFIX = ".pegasus-"',
            'CLIENT_NAME = "pegasus-doctor"',
        ):
            with self.subTest(identifier=identifier):
                self.assertIsNone(UPSTREAM_MODULE_PATH.search(identifier))


class NoSplitUpstreamPathSegmentTest(unittest.TestCase):
    """Form 2: the renamed source path, split one segment per string literal."""

    def test_no_file_contains_a_split_upstream_path_segment(self):
        offenders = _offenders(SPLIT_UPSTREAM_PATH_SEGMENT)
        self.assertEqual(
            offenders,
            {},
            "a file spells the renamed source path one segment at a time -- a bare "
            f"`\"pegasus\"` literal next to a `/`, a `\"src\"` segment, or a `join`/`joinpath` "
            f"call -- rename it to `darq`: {offenders}",
        )

    def test_a_transported_split_segment_would_be_flagged(self):
        """The shapes a transport actually produces: `Path` division, a tuple
        or list of literal segments (on one line or wrapped across several,
        the way a formatter does it), and a `join`/`joinpath` call."""
        for snippet in (
            '_ROOT / "src" / "pegasus" / "content"',
            "_ROOT / 'src' / 'pegasus' / 'content'",
            '("src", "pegasus", "content")',
            '["src", "pegasus", "content"]',
            'SRC_DIR / "pegasus"',
            '"pegasus" / "content"',
            '(\n    "src",\n    "pegasus",\n    "content",\n)',
            'os.path.join("some", "root", "pegasus", "content")',
            'os.path.join("pegasus")',
            '.joinpath("pegasus")',
            'ROOT.joinpath("pegasus")',
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(SPLIT_UPSTREAM_PATH_SEGMENT.search(snippet))

    def test_a_nested_call_is_not_caught(self):
        """Declared residue, not an oversight: `[^)]*?` inside the `join`/
        `joinpath` alternatives is bounded by the first `)` it meets, which
        belongs to a nested call's own parentheses, not to `join`'s. A guard
        built on `re`, not a real parser, cannot balance parentheses, and
        nothing in this fork's current style nests a call inside a path
        join, so the gap is accepted rather than chased with a heavier tool."""
        for snippet in (
            'os.path.join(str(ROOT), "pegasus")',
            'ROOT.joinpath(str(x), "pegasus")',
        ):
            with self.subTest(snippet=snippet):
                self.assertIsNone(SPLIT_UPSTREAM_PATH_SEGMENT.search(snippet))

    def test_a_brand_word_list_is_not_flagged(self):
        """`tests/brand_fragments.py`'s own data tuple, and the bare,
        unanchored literals `test_architecture.py` builds probes from, must
        survive: none of them touch a `/`, follow a literal `"src"`, or sit
        inside a `join`/`joinpath` call. A `join`/`joinpath` call naming this
        fork's own program, not upstream's, must also survive."""
        for snippet in (
            'BANNED_FRAGMENTS = ("pegasus", "harness", "balerdis")',
            'root = _package_files("pegasus")',
            'asset = "pegasus"',
            "sys.argv = ['pegasus'] + args",
            'os.path.join("darq", "content")',
            'ROOT.joinpath("darq")',
        ):
            with self.subTest(snippet=snippet):
                self.assertIsNone(SPLIT_UPSTREAM_PATH_SEGMENT.search(snippet))

    def test_a_wire_identifier_is_not_flagged(self):
        for identifier in (
            'SCHEMA = "pegasus-harness/journal/v4"',
            '"pegasus/cli-report/v1"',
            '"pegasus/capability-manifest/v1"',
            '"/pegasus/catalog-build"',
            'CLIENT_NAME = "pegasus-doctor"',
            'REGISTRY_ASSETS = "pegasus-registry-assets/v3"',
        ):
            with self.subTest(identifier=identifier):
                self.assertIsNone(SPLIT_UPSTREAM_PATH_SEGMENT.search(identifier))


class SplitUpstreamPathSegmentLinearityTest(unittest.TestCase):
    """The `join`/`joinpath` alternatives used to be quadratic on an opening
    that never closes, repeated; `_LinearSplitSegmentPattern` removes that
    without changing a single match."""

    #: The pattern as it was before the pre-pass, kept verbatim as the oracle.
    REFERENCE = re.compile(
        r'(["\'])pegasus\1\s*/'
        r'|/\s*(["\'])pegasus\2'
        r'|(["\'])src\3\s*,\s*(["\'])pegasus\4'
        r'|\.joinpath\([^)]*?(["\'])pegasus\5[^)]*?\)'
        r'|os\.path\.join\([^)]*?(["\'])pegasus\6[^)]*?\)'
    )

    @staticmethod
    def _spans(pattern, text):
        return [(match.start(), match.end(), match.group(0)) for match in pattern.finditer(text)]

    def assertSameMatches(self, text):
        self.assertEqual(
            self._spans(SPLIT_UPSTREAM_PATH_SEGMENT, text),
            self._spans(self.REFERENCE, text),
            repr(text),
        )

    def test_the_known_fixtures_match_exactly_as_before(self):
        for snippet in (
            '_ROOT / "src" / "pegasus" / "content"',
            "_ROOT / 'src' / 'pegasus' / 'content'",
            '("src", "pegasus", "content")',
            '(\n    "src",\n    "pegasus",\n    "content",\n)',
            'os.path.join("some", "root", "pegasus", "content")',
            'os.path.join("pegasus")',
            '.joinpath("pegasus")',
            'ROOT.joinpath("pegasus")',
            'os.path.join(str(ROOT), "pegasus")',
            'ROOT.joinpath(str(x), "pegasus")',
            'BANNED_FRAGMENTS = ("pegasus", "harness", "balerdis")',
            'root = _package_files("pegasus")',
            "sys.argv = ['pegasus'] + args",
            'os.path.join("darq", "content")',
            'ROOT.joinpath("darq")',
            'SCHEMA = "pegasus-harness/journal/v4"',
            '"pegasus/cli-report/v1"',
            '"/pegasus/catalog-build"',
            'CLIENT_NAME = "pegasus-doctor"',
            '.joinpath("pegasus"',
            '.joinpath(.joinpath("pegasus", .joinpath(x)) os.path.join("pegasus")',
        ):
            with self.subTest(snippet=snippet):
                self.assertSameMatches(snippet)

    def test_every_scanned_file_matches_exactly_as_before(self):
        for path in _scanned_files():
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertSameMatches(path.read_text(encoding="utf-8"))

    def test_generated_inputs_match_exactly_as_before(self):
        import itertools
        import random

        tokens = (
            ".joinpath(", "os.path.join(", ")", "(", '"pegasus"', "'pegasus'", '"pegasus\'',
            '"src"', ",", " ", "\n", "/", "x", '"darq"', "str(r)",
        )
        rng = random.Random(20261003)
        generated = [
            "".join(combo) for size in (1, 2, 3) for combo in itertools.product(tokens, repeat=size)
        ]
        for _ in range(3000):
            generated.append("".join(rng.choice(tokens) for _ in range(rng.randint(1, 14))))
        for text in generated:
            self.assertSameMatches(text)

    def test_an_opening_that_never_closes_is_linear(self):
        """Measured on the old pattern: ~3.5 s at n=4000, ~12 s at n=8000,
        ~47 s at n=16000. The linear version takes milliseconds; the
        threshold is a hundred times that to stay robust on a slow machine."""
        import time

        for opening in (".joinpath(", "os.path.join(", '.joinpath("pegasus"'):
            text = opening * 6000
            with self.subTest(opening=opening):
                started = time.perf_counter()
                SPLIT_UPSTREAM_PATH_SEGMENT.search(text)
                list(SPLIT_UPSTREAM_PATH_SEGMENT.finditer(text))
                elapsed = time.perf_counter() - started
                self.assertLess(elapsed, 1.0, f"{opening!r} x 6000 took {elapsed:.2f}s -- quadratic again")


class NoUpstreamPathStringTest(unittest.TestCase):
    """Form 3: the same renamed source path, written as one string, including
    inside a regex, with or without its `src/` prefix."""

    def test_no_file_contains_the_upstream_path_as_one_string(self):
        offenders = _offenders(UPSTREAM_PATH_STRING)
        self.assertEqual(
            offenders,
            {},
            "a file spells the renamed source path as one string or regex -- "
            f"rename it to `darq`, or to `src/darq` with the prefix: {offenders}",
        )

    def test_darq_source_subdirectories_are_derived_not_typed(self):
        """Pinned to today's roster, the same way agent roles are, so a
        renamed or removed top-level package -- not just an addition -- still
        shows up as a diff here."""
        self.assertEqual(
            _DARQ_SOURCE_SUBDIRECTORIES,
            sorted(["adapters", "content", "core", "infra", "ports", "tui"]),
        )

    def test_a_transported_path_string_would_be_flagged(self):
        for snippet in (
            '"src/pegasus/content/skills/"',
            'r"src/pegasus/content"',
            "PATTERN = re.compile(r'^src/pegasus/')",
            'SKILLS_DIR = "pegasus/content/skills/"',
            'pegasus/core/identity.py',
            'from the old pegasus/adapters tree',
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(UPSTREAM_PATH_STRING.search(snippet))

    def test_a_wire_identifier_is_not_flagged(self):
        """Every `pegasus/...` wire identifier either lacks the `src/` prefix
        that makes the other form a source-tree path instead of a schema id,
        or its second segment is not one of this fork's real top-level
        packages."""
        for identifier in (
            '"pegasus/capability-manifest/v1"',
            '"pegasus/model-assignment/v1"',
            '"pegasus/artifact-catalog/v4"',
            '"pegasus/cli-report/v1"',
            '"/pegasus/catalog-build"',
            'SCHEMA = "pegasus-harness/journal/v4"',
            'REGISTRY_ASSETS = "pegasus-registry-assets/v3"',
        ):
            with self.subTest(identifier=identifier):
                self.assertIsNone(UPSTREAM_PATH_STRING.search(identifier))

    def test_a_versioned_wire_id_named_like_a_directory_is_not_flagged(self):
        """A frozen wire id is `pegasus/<word>/v<digits>`. The directory
        branch derives its words from `src/darq/`, so a schema family that
        happens to be called `core` or `ports` is not a path: no source file
        is ever named `v1`, and the shape is how every wire id spells itself."""
        for identifier in (
            '"pegasus/core/v1"',
            '"pegasus/ports/v2"',
            'SCHEMA = "pegasus/adapters/v10"',
            "`pegasus/content/v3`",
            "(pegasus/tui/v1)",
        ):
            with self.subTest(identifier=identifier):
                self.assertIsNone(UPSTREAM_PATH_STRING.search(identifier))

    def test_a_real_path_that_starts_like_a_version_is_still_flagged(self):
        """The wire-id exemption is the whole `/v<digits>` segment and nothing
        longer: a file, a directory or a longer name under a real
        subdirectory is a path the way code would build it."""
        for snippet in (
            '"pegasus/core/v1.py"',
            '"pegasus/core/v1/"',
            '"pegasus/core/v1/identity.py"',
            '"pegasus/core/v1x"',
            '"pegasus/core/version.py"',
            '"pegasus/core/identity.py"',
            '"pegasus/core"',
            "SRC / 'src/pegasus/core/v1'",
        ):
            with self.subTest(snippet=snippet):
                self.assertTrue(UPSTREAM_PATH_STRING.search(snippet))

    def test_a_directory_name_used_as_a_mere_prefix_is_not_flagged(self):
        """The lookaround keeps `core`, a real subdirectory, from matching
        inside `pegasus/core-legacy`, a segment that is not actually that
        directory -- the same discipline `pegasus-doctor` needs against a
        bare `pegasus`."""
        self.assertIsNone(UPSTREAM_PATH_STRING.search('"pegasus/core-legacy/notes.md"'))


class NoUpstreamAgentNameTest(unittest.TestCase):
    """Form 4: an upstream agent's own name, mostly derived from this fork's
    own `identity.json` and agent directory -- in a file's own prose, or in a
    file's own filename."""

    def test_there_are_darq_agent_names_to_derive_from(self):
        self.assertTrue(
            _derived_upstream_agent_names(),
            "no `<program_name>-<role>` agent found under src/darq/content/agents/ -- "
            "derivation has nothing to derive from",
        )

    def test_the_derived_names_match_the_five_generic_roles(self):
        """Pinned to today's roster so a silent rename of a role -- not just
        an addition -- still shows up as a diff here."""
        self.assertEqual(
            _derived_upstream_agent_names(),
            frozenset({
                "pegasus-explorer",
                "pegasus-general",
                "pegasus-implementer",
                "pegasus-orchestrator",
                "pegasus-verifier",
            }),
        )

    def test_no_file_names_an_upstream_agent(self):
        offenders = _offenders(UPSTREAM_AGENT_NAME)
        self.assertEqual(
            offenders,
            {},
            "a file names an upstream agent that this fork does not ship -- "
            f"rename it to its DARQ counterpart: {offenders}",
        )

    def test_a_transported_agent_name_would_be_flagged(self):
        for name in (
            "pegasus-orchestrator",
            "pegasus-explorer",
            "pegasus-implementer",
            "pegasus-verifier",
            "pegasus-general",
            "king-pegasus",
        ):
            with self.subTest(name=name):
                self.assertTrue(UPSTREAM_AGENT_NAME.search(f"delegate to `{name}` for this"))

    def test_darqs_own_agent_names_are_not_flagged(self):
        for name in (
            "darq-orchestrator",
            "darq-explorer",
            "darq-implementer",
            "darq-verifier",
            "darq-general",
            "arquitecto-darq",
        ):
            with self.subTest(name=name):
                self.assertIsNone(UPSTREAM_AGENT_NAME.search(f"delegate to `{name}` for this"))

    def test_the_explicit_exception_still_names_a_file_that_needs_it(self):
        """The hand-typed exception may not outlive its reason: the DARQ file
        it is paired with, in the comment next to it, must still exist."""
        self.assertTrue(
            (ROOT / "src/darq/content/agents/arquitecto-darq.md").is_file(),
            "arquitecto-darq.md is gone -- UPSTREAM_AGENT_NAMES_EXPLICIT's "
            "`king-pegasus` entry has lost the DARQ name it was paired with",
        )

    def test_a_wholly_new_upstream_agent_role_is_not_caught(self):
        """The residue this form cannot see, measured rather than assumed:
        derivation only ever produces `pegasus-<role>` for a role this fork
        has *already* mirrored as `darq-<role>`. An upstream role with no
        DARQ counterpart yet -- say Pegasus ships a sixth generic agent,
        `pegasus-scribe`, before anyone creates `darq-scribe` -- derives
        nothing, because there is no `darq-scribe` file to read the role off
        of, and `pegasus-scribe` is not in `UPSTREAM_AGENT_NAMES_EXPLICIT`
        either: that list is reserved for names derivation is structurally
        unable to reach (`king-pegasus`), not for names it merely has not
        seen yet. So a file naming `pegasus-scribe` today would ride in
        unflagged, exactly the way `__main__` once did for the dotted-path
        pattern before that pattern stopped enumerating modules -- except
        this form has no dot to match on instead, so the gap stays open
        until the day this fork actually ships `darq-scribe`, at which point
        the very next run derives `pegasus-scribe` and starts catching it."""
        self.assertNotIn("pegasus-scribe", UPSTREAM_AGENT_NAMES)
        self.assertIsNone(UPSTREAM_AGENT_NAME.search("`pegasus-scribe` writes the changelog"))

    def test_no_agent_file_has_an_upstream_name_as_its_own_filename(self):
        """An upstream agent review found a file whose *filename* is an
        upstream agent's name -- `pegasus-explorer.md` -- with a body that
        never repeats it anywhere, escapes `test_no_file_names_an_upstream_
        agent` entirely: that check only ever reads content. Proven against
        a real file under `_AGENTS_DIR`, written and removed during
        development (never committed), whose body was deliberately silent
        about its own filename; this test is the permanent regression."""
        offenders = _agent_filename_offenders()
        self.assertEqual(
            offenders,
            [],
            "an agent file's own filename is an upstream agent's name, even though its body "
            f"never repeats it -- rename the file to its DARQ counterpart: {offenders}",
        )

    def test_a_matching_filename_would_be_flagged(self):
        """The scan is a plain `path.stem in UPSTREAM_AGENT_NAMES` check on
        `_AGENTS_DIR.glob("*.md")` -- exercised here against an isolated
        temporary directory standing in for `_AGENTS_DIR`, so the mechanism
        stays under a permanent regression test without ever writing an
        upstream-named file into the real one."""
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp)
            (agents_dir / "pegasus-explorer.md").write_text(
                "A file whose body never repeats its own filename.\n", encoding="utf-8"
            )
            (agents_dir / "darq-explorer.md").write_text(
                "A legitimate DARQ agent.\n", encoding="utf-8"
            )
            offenders = sorted(
                path.name for path in agents_dir.glob("*.md") if path.stem in UPSTREAM_AGENT_NAMES
            )
        self.assertEqual(offenders, ["pegasus-explorer.md"])


if __name__ == "__main__":
    unittest.main()
