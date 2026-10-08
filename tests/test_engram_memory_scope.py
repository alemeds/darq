"""Closed-world pin: who writes to Engram, and when a session closes.

7.1.0 changed a decision that used to read as blanket pressure -- "save NOW",
"waiting to be asked is the failure mode" -- into a conditional one: a
sub-agent (an agent launched by another agent) makes no memory write unless
its own brief asks for one, and only the agent talking with the person calls
`mem_session_summary`, only at a real close. The prose that carries this now
lives in two places every agent reads: the ambient system-prompt block
(`system-prompt/mcp/engram.md`) and the convention it points at
(`mcp/engram.md`). Both are closed-world here: the unit is the paragraph
(blank-line separated), not the sentence, because a heading glued to its own
paragraph and a fenced template inside a paragraph make sentence-splitting
unreliable over this content -- the same reason `test_orchestrator_routing.py`
warns a naive scan does not follow prose across units it was not built to
read. A rewording of a pinned paragraph, an inverted clause, or a second
paragraph that touches the same subject elsewhere in the file fails here,
whatever it says.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "darq" / "content"
PLUGIN = ROOT / "src/darq/adapters/opencode/assets/plugins/engram.ts"
PLUGIN_HARNESS = ROOT / "tests/fixtures/engram_plugin_harness.mjs"

#: engram v1.20.0's own heading matcher, copied from `internal/store/store.go`
#: (`ExtractLearnings`), not retyped from memory. DARQ's ambient content
#: MUST write a heading that satisfies this exact pattern, or nothing a
#: sub-agent writes is ever captured, however conversational the wording.
ENGRAM_LEARNING_HEADER_PATTERN = re.compile(
    r"(?im)^#{2,3}\s+(?:Aprendizajes(?:\s+Clave)?|Key\s+Learnings?|Learnings?):?\s*$"
)

AMBIENT = CONTENT / "system-prompt/mcp/engram.md"
CONVENTION = CONTENT / "mcp/engram.md"
FRAGMENT = CONTENT / "agents/mcp/engram.md"
PERSISTENCE = CONTENT / "skills/_shared/persistence-contract.md"
PHASE_COMMON = CONTENT / "skills/_shared/sdd-phase-common.md"

#: A paragraph that grants or denies a sub-agent (an agent launched by
#: another agent) standing to write memory.
SUBAGENT_WRITE_STEM = re.compile(
    r"launched by another agent|launched you|\bsub[- ]?agents?\b",
    re.IGNORECASE,
)

#: A paragraph that says when `mem_session_summary` may be called.
SESSION_CLOSE_STEM = re.compile(
    r"mem_session_summary|real close|\bnot a close\b",
    re.IGNORECASE,
)

#: A paragraph that discusses the `## Key Learnings` opt-in save mechanism
#: (7.2.0): a sub-agent whose brief asks for it ends its reply with a
#: `## Key Learnings` section; the passive capture (the engram plugin on the
#: `task` output in OpenCode, the `SubagentStop` hook in Claude Code) saves
#: it -- no memory tool call from the sub-agent itself.
KEY_LEARNINGS_STEM = re.compile(r"key learnings", re.IGNORECASE)

#: Phrasing that would re-open a blanket mandate on this specific
#: mechanism: a sub-agent told to always write the section regardless of
#: its brief, or told to call the capture tool directly -- both defeat the
#: "unless your brief asks for one" rule the rest of this file pins.
KEY_LEARNINGS_MANDATE_STEM = re.compile(
    r"always (write|include|end (your reply )?with).{0,20}Key Learnings"
    r"|mem_capture_passive",
    re.IGNORECASE,
)

#: A paragraph on the subject of looking memory up to confirm a
#: `## Key Learnings` capture landed -- the lookup a literal launcher would
#: run after every delegation instead of trusting the deterministic
#: "your own instructions already say which case applies" signal (review
#: item 2). Matches the subject regardless of negation -- no lookbehind
#: guard for "never"/"don't": a lexical negation classifier is exactly the
#: kind of check this repo has watched fail (inverted bullets, passive
#: voice, "don't forget to check whether..."). Closed-world instead: every
#: paragraph this matches is pinned verbatim below, by set equality, in
#: `AMBIENT_VERIFICATION_LOOP_PARAGRAPHS` and
#: `CONVENTION_VERIFICATION_LOOP_PARAGRAPHS` -- the sanctioned negated
#: sentences are allowed only because they are pinned; any other sentence on
#: this subject, negated or not, fails elsewhere in this file.
VERIFICATION_LOOP_STEM = re.compile(
    r"checks? (that|whether) (they|the items|it) landed"
    r"|search(?:es)? memory (to|and|just to) confirm"
    r"|confirms? (that|whether) (they|the items|it) (landed|(?:were|was) saved)"
    r"|verif(?:y|ies) (that|whether) (they|the items|it) (landed|(?:were|was) saved)",
    re.IGNORECASE,
)

#: A paragraph that mandates a non-SDD sub-agent write to memory before
#: returning, regardless of its brief -- the shape an independent review
#: found still shipped in the orchestrator's Non-SDD launch template
#: ("you MUST save them to engram before returning ... Do NOT return
#: without saving what you learned"). An SDD phase's own artifact mandate
#: ("you MUST call: mem_save(title: \"sdd/...")) does not use any of this
#: phrasing -- it names its artifact, never "to engram" or "before
#: returning" or "what you learned" -- so it never trips this stem.
NON_SDD_MANDATE_STEM = re.compile(
    r"must save (them |it |your \w+ )?to engram"
    r"|save (it |them |your \w+ )?before returning"
    r"|without saving what you learned"
    r"|do not return without saving",
    re.IGNORECASE,
)

#: Phrasing 7.1.0 retired: every task end read as a save trigger, and any
#: session end (a reply, a "done") read as a close. None of it may survive
#: anywhere in shipped content -- the shared block, the convention, the
#: skills and the plugin source -- not reworded, not restated with new words.
RETIRED_PRESSURE_PHRASES = (
    "save NOW",
    "Self-check after",
    "the failure mode this protocol exists to prevent",
    'Before ending a session or saying "done"',
    'before ending a session or saying "done"',
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def paragraphs_of(text: str) -> list[str]:
    """Blank-line separated blocks of `text`, each whitespace-collapsed."""
    found = []
    for block in re.split(r"\n\s*\n", text):
        collapsed = " ".join(block.split())
        if collapsed:
            found.append(collapsed)
    return found


def paragraphs_on(text: str, stem: re.Pattern[str]) -> set[str]:
    return {p for p in paragraphs_of(text) if stem.search(p)}


#: The two paragraphs `system-prompt/mcp/engram.md` carries on each subject,
#: pinned as written. The heading-only block above the first is not itself
#: on either subject (it names the section, it does not state the rule).
AMBIENT_SUBAGENT_WRITE_PARAGRAPHS = frozenset(
    {
        '### If you were launched by another agent',
        'You make no memory writes — no `mem_save`, `mem_update`, `mem_session_summary`, nor the `mem_judge` that follows a save — unless your brief asks for one. You may still read memory: `mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping goes in your reply; whoever launched you decides what to save.',
    }
)
AMBIENT_SESSION_CLOSE_PARAGRAPHS = frozenset(
    {
        "You make no memory writes — no `mem_save`, `mem_update`, `mem_session_summary`, nor the "
        "`mem_judge` that follows a save — unless your brief asks for one. You may still read memory: "
        "`mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping goes in your reply; "
        "whoever launched you decides what to save.",
        'Only you call `mem_session_summary`, and only at a real close: the person says the session is '
        'ending, or asks for it. Finishing a task, getting a delegation back, or delivering a reply is '
        'not a close, and neither is saying "done" or "listo".',
        "If you hit a compaction, call `mem_session_summary` with the compacted summary FIRST, so what "
        "happened before it is not lost, then `mem_context`, and only then continue working.",
    }
)

#: Same two subjects, for `mcp/engram.md` (the convention). Grew from four to
#: eight in 7.2.0: the new `## Sub-Agent Findings` section (the `##
#: Key Learnings` mechanism) names "sub-agent" in its own heading and three
#: of its four paragraphs, so it lands here too, alongside the two subjects
#: that section is not about.
CONVENTION_SUBAGENT_WRITE_PARAGRAPHS = frozenset(
    {
        '## Sub-Agent Findings (`## Key Learnings`)',
        "- Always write the heading exactly as `## Key Learnings`, on its own line. As compatibility forms only, engram v1.20.0's extractor (`ExtractLearnings`, `internal/store/store.go`) also recognizes `### Key Learnings`, `## Learnings` and `### Learnings` — never a heading with a single `#`: the extractor's heading pattern is anchored to two or three `#` (`^#{2,3}`), so one `#` is not recognized and nothing under it is saved. - Items are numbered (`1.`, `2.`, ...), one durable finding per item, each a self-contained sentence on its own line. A bulleted list is used only as a fallback when there are no numbered items. - Each item needs 20 or more characters and 4 or more words after stripping bold, italic and inline-code markup — a fragment shorter than that is dropped, not saved short. - If the reply has more than one such section, only the **last** one that yields valid items is used; an earlier one is discarded, not merged. - Saved items are deduplicated by a normalized hash within the project — the same finding written twice does not produce two observations. - Each item lands as its own observation, type `passive`, scope project, linked to the **launcher's** session — the passive capture runs in the launching agent's hook, not the sub-agent's.",
        'Do not skip step 1. Without it, everything done before compaction is lost from memory. A sub-agent that hits compaction follows the Memory Scope rule above instead: no `mem_session_summary` unless its brief asks for one.',
        "For an SDD phase sub-agent, the `Artifact store mode` line in your launch — `engram` or `hybrid` — is the brief asking for exactly this artifact write; it is not a license to save anything else. Ad-hoc discovery saves and `mem_session_summary` stay the launching agent's job, not yours, per the Memory Scope rule above.",
        'If you were launched by another agent, you make no memory writes — no `mem_save`, `mem_update`, `mem_session_summary`, nor the `mem_judge` that follows a save — unless your brief asks for one. You may still read: `mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping goes in your reply; whoever launched you decides what to save.',
        "NOTE: Critical engram calls (`mem_search`, `mem_save`, `mem_get_observation`) are inlined directly in each skill's SKILL.md. This section is supplementary reference — sub-agents do NOT need to read it to function.",
        "This save runs on every platform whenever engram is selected. The agent that launched the sub-agent leaves its `## Key Learnings` items to that capture: it does not save them again and never searches memory just to confirm they landed. Anything else durable in the reply is still its to save.",
        "When engram is selected, a passive capture runs on the way back from a launched agent — the platform's own plugin on the sub-agent tool's output, or its hook on the sub-agent's last message, whichever the platform provides. A sub-agent can therefore have specific findings saved for it without ever calling a memory tool: when its brief asks for this, it ends its reply with a `## Key Learnings` section, and that section is saved automatically once the reply returns.",
    }
)

#: The `## Key Learnings` opt-in save mechanism, pinned by file. Ambient and
#: convention are exact-set pinned like the two subjects above; the shared
#: persistence contract is checked by substring,
#: consistent with how this module already checks those two files elsewhere.
AMBIENT_KEY_LEARNINGS_PARAGRAPHS = frozenset(
    {
        "To have a launched agent's findings saved this way, ask its brief to end with a `## Key Learnings` section. Its items are saved automatically when its reply returns, one observation each: don't save them again yourself, and never search memory just to confirm they landed. Anything else durable in its reply is still yours to save.",
        'When your brief asks you to record learnings, end your reply with a `## Key Learnings` section: numbered, one durable finding per item, each a self-contained sentence on one line. Call no memory tool for it — it is saved automatically when your reply returns. Without that request, write no such section.',
    }
)
CONVENTION_KEY_LEARNINGS_PARAGRAPHS = frozenset(
    {
        '## Sub-Agent Findings (`## Key Learnings`)',
        "- Always write the heading exactly as `## Key Learnings`, on its own line. As compatibility forms only, engram v1.20.0's extractor (`ExtractLearnings`, `internal/store/store.go`) also recognizes `### Key Learnings`, `## Learnings` and `### Learnings` — never a heading with a single `#`: the extractor's heading pattern is anchored to two or three `#` (`^#{2,3}`), so one `#` is not recognized and nothing under it is saved. - Items are numbered (`1.`, `2.`, ...), one durable finding per item, each a self-contained sentence on its own line. A bulleted list is used only as a fallback when there are no numbered items. - Each item needs 20 or more characters and 4 or more words after stripping bold, italic and inline-code markup — a fragment shorter than that is dropped, not saved short. - If the reply has more than one such section, only the **last** one that yields valid items is used; an earlier one is discarded, not merged. - Saved items are deduplicated by a normalized hash within the project — the same finding written twice does not produce two observations. - Each item lands as its own observation, type `passive`, scope project, linked to the **launcher's** session — the passive capture runs in the launching agent's hook, not the sub-agent's.",
        "This save runs on every platform whenever engram is selected. The agent that launched the sub-agent leaves its `## Key Learnings` items to that capture: it does not save them again and never searches memory just to confirm they landed. Anything else durable in the reply is still its to save.",
        "When engram is selected, a passive capture runs on the way back from a launched agent — the platform's own plugin on the sub-agent tool's output, or its hook on the sub-agent's last message, whichever the platform provides. A sub-agent can therefore have specific findings saved for it without ever calling a memory tool: when its brief asks for this, it ends its reply with a `## Key Learnings` section, and that section is saved automatically once the reply returns.",
    }
)
CONVENTION_SESSION_CLOSE_PARAGRAPHS = frozenset(
    {
        "If you were launched by another agent, you make no memory writes — no `mem_save`, `mem_update`, "
        "`mem_session_summary`, nor the `mem_judge` that follows a save — unless your brief asks for one. "
        "You may still read: `mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping "
        "goes in your reply; whoever launched you decides what to save.",
        "Only the agent talking with the person calls `mem_session_summary`, and only at a real close: "
        "the person says the session is ending, or asks for it (or the equivalent in the user's "
        'language). Finishing a task, getting a delegation back, or delivering a reply is not a close, '
        'and neither is saying "done" / "listo" / "that\'s it". At a real close, call '
        "`mem_session_summary` with this shape:",
        # Gated (Blocking 2 fix): unlike the retired ungated form -- "If you
        # see a compaction message or ..." -- this now names who it is for
        # in the same paragraph the closed-world stem matches, so an
        # ungated rewrite fails the exact-set equality below.
        'If you are the agent talking with the person and you see a compaction message or "FIRST ACTION '
        'REQUIRED": 1. IMMEDIATELY call `mem_session_summary` with the compacted summary content — this '
        "persists what was done before compaction 2. Call `mem_context` to recover additional context "
        "from previous sessions 3. Only THEN continue working",
        "Do not skip step 1. Without it, everything done before compaction is lost from memory. A "
        "sub-agent that hits compaction follows the Memory Scope rule above instead: no "
        "`mem_session_summary` unless its brief asks for one.",
        "For an SDD phase sub-agent, the `Artifact store mode` line in your launch — `engram` or "
        "`hybrid` — is the brief asking for exactly this artifact write; it is not a license to save "
        "anything else. Ad-hoc discovery saves and `mem_session_summary` stay the launching agent's job, "
        "not yours, per the Memory Scope rule above.",
    }
)


class AmbientBlockScopeTest(unittest.TestCase):
    def setUp(self):
        self.text = read(AMBIENT)

    def test_subagent_write_paragraphs_are_exactly_the_pinned_two(self):
        self.assertEqual(paragraphs_on(self.text, SUBAGENT_WRITE_STEM), AMBIENT_SUBAGENT_WRITE_PARAGRAPHS)

    def test_session_close_paragraphs_are_exactly_the_pinned_three(self):
        self.assertEqual(paragraphs_on(self.text, SESSION_CLOSE_STEM), AMBIENT_SESSION_CLOSE_PARAGRAPHS)

    def test_key_learnings_paragraphs_are_exactly_the_pinned_two(self):
        self.assertEqual(paragraphs_on(self.text, KEY_LEARNINGS_STEM), AMBIENT_KEY_LEARNINGS_PARAGRAPHS)

    def test_no_key_learnings_mandate_regardless_of_brief(self):
        self.assertEqual(paragraphs_on(self.text, KEY_LEARNINGS_MANDATE_STEM), set())

    def test_the_section_opens_with_a_level_two_heading(self):
        # test_content.py:test_every_agent_mcp_section_opens_with_its_own_heading
        # pins this shape; guard it here too so a rewrite of this file cannot
        # silently break the composed agent prompt.
        after_marker = self.text.split("darq:engram -->", 1)[1]
        self.assertTrue(after_marker.lstrip().startswith("## "))


class ConventionScopeTest(unittest.TestCase):
    def setUp(self):
        self.text = read(CONVENTION)

    def test_subagent_write_paragraphs_are_exactly_the_pinned_eight(self):
        self.assertEqual(paragraphs_on(self.text, SUBAGENT_WRITE_STEM), CONVENTION_SUBAGENT_WRITE_PARAGRAPHS)

    def test_session_close_paragraphs_are_exactly_the_pinned_five(self):
        self.assertEqual(paragraphs_on(self.text, SESSION_CLOSE_STEM), CONVENTION_SESSION_CLOSE_PARAGRAPHS)

    def test_key_learnings_paragraphs_are_exactly_the_pinned_four(self):
        self.assertEqual(paragraphs_on(self.text, KEY_LEARNINGS_STEM), CONVENTION_KEY_LEARNINGS_PARAGRAPHS)

    def test_no_key_learnings_mandate_regardless_of_brief(self):
        self.assertEqual(paragraphs_on(self.text, KEY_LEARNINGS_MANDATE_STEM), set())


class WholeWordMemoryWritesTest(unittest.TestCase):
    """Long sessions can fuse words in memory writes ("credentialchanges"), and
    memory search matches whole words, so such a memory is never found. Both the
    ambient block and the convention carry the rule: title and content, whole
    words, and it holds however long the session runs."""

    AMBIENT_RULE = (
        "Write every memory \u2014 title and content alike \u2014 in normal prose, with a space between words "
        "and every word spelled out whole. Memory search matches whole words, so a fused word like "
        "`credentialchanges` is never found by a search for `credential`, and a memory nobody can find is a "
        "memory lost. This holds however long the session has run."
    )
    CONVENTION_RULE = (
        "Write the title and the content in normal prose, with a space between words and every word spelled "
        "out whole. Memory search matches whole words, so a fused word like `credentialchanges` is never "
        "found by a search for `credential`. This holds however long the session has run."
    )

    @staticmethod
    def _paragraphs(text):
        return [" ".join(p.split()) for p in re.split(r"\n\s*\n", text)]

    def test_the_ambient_block_carries_the_pinned_paragraph_once(self):
        found = [p for p in self._paragraphs(read(AMBIENT)) if "fused word" in p]
        self.assertEqual(found, [self.AMBIENT_RULE])

    def test_the_convention_carries_the_pinned_paragraph_once(self):
        found = [p for p in self._paragraphs(read(CONVENTION)) if "fused word" in p]
        self.assertEqual(found, [self.CONVENTION_RULE])

    def test_the_rule_covers_title_and_content_whole_words_and_any_session_length(self):
        for path in (AMBIENT, CONVENTION):
            with self.subTest(path=path.name):
                text = " ".join(read(path).split())
                self.assertIn("title and", text)
                self.assertIn("content", text)
                self.assertIn("matches whole words", text)
                self.assertIn("however long the session has run", text)

    def test_the_convention_rule_sits_in_the_save_format_part(self):
        text = read(CONVENTION)
        self.assertLess(text.index("## Save Format"), text.index("fused word"))
        self.assertLess(text.index("fused word"), text.index("## Topic Update Rules"))


class NonSDDWriteMandateGoneTest(unittest.TestCase):
    """Blocking 1: the orchestrator's Non-SDD launch template used to read
    "you MUST save them to engram before returning ... Do NOT return without
    saving what you learned" -- a blanket mandate on the most common
    delegation path, contradicting the Memory Scope rule for every other
    sub-agent that reads it. `NON_SDD_MANDATE_STEM` is deliberately narrow:
    an SDD phase's own artifact mandate (`you MUST call: mem_save(title:
    "sdd/...")`) never says "to engram", "before returning" or "what you
    learned", so it never trips this stem -- only a re-opened blanket
    mandate does."""

    def test_no_content_file_carries_a_non_sdd_write_mandate(self):
        for path in CONTENT.rglob("*.md"):
            text = read(path)
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(paragraphs_on(text, NON_SDD_MANDATE_STEM), set())

    def test_the_plugin_source_carries_no_non_sdd_write_mandate(self):
        self.assertEqual(paragraphs_on(read(PLUGIN), NON_SDD_MANDATE_STEM), set())


class UnreadableConventionFallbackIsScopedTest(unittest.TestCase):
    """Non-blocking 4: "save anyway" / "still save rather than skipping the
    write" read, to a literal sub-agent, as "write regardless of scope" --
    exactly the license the Memory Scope rule takes away. Both fallbacks now
    name which write is already the agent's own before saying to make it
    anyway."""

    def test_the_fragment_fallback_names_the_write_that_is_already_yours(self):
        text = read(FRAGMENT)
        self.assertIn("still make whatever write is already yours", text)
        self.assertNotIn("save anyway rather than skipping the write", text)

    def test_the_ambient_fallback_names_the_write_that_is_already_yours(self):
        text = read(AMBIENT)
        self.assertIn("still make whatever write is already yours", text)
        self.assertNotIn("still save rather than skipping the write", text)


class RetiredPressurePhrasesGoneTest(unittest.TestCase):
    """None of 7.1.0's retired pressure phrasing survives anywhere shipped."""

    def test_no_shipped_content_file_carries_retired_pressure_phrasing(self):
        for path in CONTENT.rglob("*.md"):
            text = read(path)
            for phrase in RETIRED_PRESSURE_PHRASES:
                with self.subTest(path=path.relative_to(ROOT), phrase=phrase):
                    self.assertNotIn(phrase, text)

    def test_the_plugin_source_carries_no_retired_pressure_phrasing(self):
        text = read(PLUGIN)
        for phrase in RETIRED_PRESSURE_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)


class PersistenceContractKeyLearningsTest(unittest.TestCase):
    """7.2.0: the Non-SDD opt-in `PERSISTENCE:` line used to instruct a direct
    `mem_save` call, which the sub-agent memory-scope rule already forbids
    unless the brief asks for exactly that write. It now asks for a
    `## Key Learnings` section instead -- the sub-agent still calls no
    memory tool; the plugin's passive capture saves it."""

    def setUp(self):
        self.text = read(PERSISTENCE)

    def test_the_opt_in_line_asks_for_the_section_not_a_mem_save_call(self):
        self.assertIn(
            "PERSISTENCE: End your reply with a `## Key Learnings` section",
            self.text,
        )
        self.assertIn("Call no memory tool for it; it is saved automatically when your reply returns.", self.text)
        self.assertNotIn("Call mem_save(title:", self.text)

    def test_no_key_learnings_mandate_regardless_of_brief(self):
        self.assertEqual(paragraphs_on(self.text, KEY_LEARNINGS_MANDATE_STEM), set())


class KeyLearningsMandateNeverShipsTest(unittest.TestCase):
    """Repo-wide: no shipped content file or the plugin source may tell a
    sub-agent to always write a `## Key Learnings` section regardless of its
    brief, or to call `mem_capture_passive` directly -- both would re-open
    the write sub-agents do not otherwise have."""

    def test_no_content_file_carries_the_mandate(self):
        for path in CONTENT.rglob("*.md"):
            text = read(path)
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(paragraphs_on(text, KEY_LEARNINGS_MANDATE_STEM), set())

    def test_the_plugin_source_carries_no_such_mandate(self):
        self.assertEqual(paragraphs_on(read(PLUGIN), KEY_LEARNINGS_MANDATE_STEM), set())


#: The one paragraph each of `AMBIENT` and `CONVENTION` is allowed to carry on
#: the "look memory up to confirm" subject: the sanctioned negation ("never
#: search memory just to confirm..."). Pinned verbatim, closed-world style --
#: see `VERIFICATION_LOOP_STEM` above for why this replaced a lookbehind.
AMBIENT_VERIFICATION_LOOP_PARAGRAPHS = frozenset(
    {
        "To have a launched agent's findings saved this way, ask its brief to end with a "
        "`## Key Learnings` section. Its items are saved automatically when its reply returns, one "
        "observation each: don't save them again yourself, and never search memory just to confirm "
        "they landed. Anything else durable in its reply is still yours to save.",
    }
)
CONVENTION_VERIFICATION_LOOP_PARAGRAPHS = frozenset(
    {
        "This save runs on every platform whenever engram is selected. The agent that launched the sub-agent leaves its `## Key Learnings` items to that capture: it does not save them again and never searches memory just to confirm they landed. Anything else durable in the reply is still its to save.",
    }
)


class NoVerificationLoopForKeyLearningsTest(unittest.TestCase):
    """Review item 2: "check that they landed" invites a literal launcher to
    run `mem_search` after every delegation. The fix is a deterministic
    signal instead -- the launcher's own instructions either state the save
    runs automatically (both the shared block and the convention say so
    unconditionally: the capture runs in OpenCode and in Claude Code whenever
    engram is selected), so the launcher never saves the items again nor
    searches to confirm them. Only `AMBIENT` and `CONVENTION` may
    touch this subject at all, and only through their one pinned, negated
    paragraph each -- every other file, and any other paragraph in those two,
    fails."""

    def test_no_other_content_file_touches_the_subject(self):
        for path in CONTENT.rglob("*.md"):
            if path in (AMBIENT, CONVENTION):
                continue
            text = read(path)
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(paragraphs_on(text, VERIFICATION_LOOP_STEM), set())

    def test_the_plugin_source_never_touches_the_subject(self):
        self.assertEqual(paragraphs_on(read(PLUGIN), VERIFICATION_LOOP_STEM), set())

    def test_ambient_paragraphs_on_the_subject_are_exactly_the_pinned_one(self):
        self.assertEqual(
            paragraphs_on(read(AMBIENT), VERIFICATION_LOOP_STEM), AMBIENT_VERIFICATION_LOOP_PARAGRAPHS
        )

    def test_convention_paragraphs_on_the_subject_are_exactly_the_pinned_one(self):
        self.assertEqual(
            paragraphs_on(read(CONVENTION), VERIFICATION_LOOP_STEM), CONVENTION_VERIFICATION_LOOP_PARAGRAPHS
        )


class SubagentScopeReachesSharedSkillFilesTest(unittest.TestCase):
    """`persistence-contract.md` and `sdd-phase-common.md` are not closed-world
    here (both use "sub-agent" densely for unrelated things: skill loading,
    response ordering), but each MUST state that the artifact-store-mode line
    is the brief asking, and neither may re-open a blanket save mandate."""

    def test_persistence_contract_names_the_artifact_mode_as_the_brief(self):
        text = read(PERSISTENCE)
        self.assertIn(
            "IS the brief asking for that phase's own artifact write — nothing else.",
            text,
        )

    def test_phase_common_names_the_artifact_write_as_the_one_brief_ask(self):
        text = read(PHASE_COMMON)
        self.assertIn(
            "This is the one memory write your launch brief asks for, per the ambient memory-scope rule",
            text,
        )

    def test_the_fragment_names_the_launched_by_another_agent_condition(self):
        text = read(FRAGMENT)
        self.assertIn("whether you were launched by another agent", text)
        self.assertIn("you make no memory writes unless your brief asks for one", text)

    def test_the_non_sdd_template_asks_for_findings_not_a_mandate(self):
        text = read(PERSISTENCE)
        self.assertIn("Return durable findings in your reply", text)
        self.assertIn("You make no memory write; the launcher decides what to save", text)

    def test_the_who_writes_line_no_longer_says_sub_agents_always_write(self):
        text = read(PERSISTENCE)
        self.assertNotIn("Sub-agents always write:", text)
        self.assertIn(
            "SDD phases write their own artifact: the `Artifact store mode` line in their launch asks "
            "for exactly that write",
            text,
        )


class EngramPluginPassiveCaptureNodeTest(unittest.TestCase):
    """Behavioral coverage for the fix in `tool.execute.after`: the trigger
    was dead because OpenCode reports the sub-agent tool id as lowercase
    `task`, never the capitalized `Task` this check was copied from (see
    the docs/arquitectura/arquitectura.md 7.2.0 section for the evidence).
    This drives the real plugin under Node with a stubbed `Bun` global and a
    recording `fetch`, rather than re-deriving the fix from a regex over the
    source -- a static check could not tell a working trigger from a
    string that merely mentions "task"."""

    @classmethod
    def setUpClass(cls):
        if shutil.which("node") is None:
            raise unittest.SkipTest("node is not installed — cannot run the plugin harness")

    def _run_harness(self) -> dict:
        result = subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                str(PLUGIN_HARNESS),
                str(PLUGIN),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"plugin harness failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )
        return json.loads(result.stdout)

    def test_task_tool_id_fires_a_passive_capture_post(self):
        data = self._run_harness()
        cases = {c["tool"]: c for c in data["cases"]}
        self.assertTrue(cases["task"]["posted"], "lowercase 'task' — OpenCode's real tool id — did not fire")

    def test_capitalized_task_and_reported_subagent_rename_also_fire(self):
        data = self._run_harness()
        cases = {c["tool"]: c for c in data["cases"]}
        self.assertTrue(cases["Task"]["posted"], "capitalized 'Task' regressed")
        self.assertTrue(cases["subagent"]["posted"], "the reported 'subagent' rename was not covered")

    def test_unrelated_tools_fire_no_passive_capture(self):
        data = self._run_harness()
        cases = {c["tool"]: c for c in data["cases"]}
        self.assertFalse(cases["read"]["posted"], "'read' must never trigger passive capture")
        self.assertFalse(cases["bash"]["posted"], "'bash' must never trigger passive capture")

    def test_engram_own_tools_return_before_the_session_is_registered(self):
        """OpenCode 1.x reports the plugin's own MCP tools as `engram_mem_*`
        (a live install's DB has thousands of `engram_mem_save` calls and no
        `mem_save`), while the exclusion list held only the bare names, so
        it never matched. An excluded call must return before `ensureSession`
        and the counters; the control shows the same session id otherwise
        does register."""
        cases = {c["tool"]: c for c in self._run_harness()["cases"]}
        for tool in ("engram_mem_save", "ENGRAM_mem_search", "mem_save"):
            with self.subTest(tool=tool):
                self.assertFalse(cases[tool]["sessionRegistered"], f"{tool} reached ensureSession")
                self.assertFalse(cases[tool]["posted"], f"{tool} reached passive capture")
        self.assertTrue(cases["read-control"]["sessionRegistered"], "the control never registered a session")

    def test_a_sub_agent_session_running_the_tool_fires_no_passive_capture(self):
        """A sub-agent never launches its own sub-agents with a `## Key
        Learnings` request -- that criterion belongs to the agent talking
        with the person -- so a sub-sub-agent's findings reach memory
        through the intermediate agent's own `## Key Learnings` section,
        captured under the root session. Posting a second, nested passive
        capture for the session that ran the sub-agent tool used to hand
        engram a session id it never registered (a sub-agent session is
        never `ensureSession`-ed), which engram rejected and `engramFetch`
        swallowed silently -- see the plugin's `tool.execute.after`."""
        data = self._run_harness()
        cases = {c["tool"]: c for c in data["cases"]}
        self.assertFalse(
            cases["task-from-subagent-session"]["posted"],
            "a sub-agent session completing a 'task' tool must not post a nested passive capture",
        )
        # The root session's own 'task' completion, from the very same run,
        # still posts -- confirming the guard is scoped to sub-agent
        # sessions, not a global regression that silenced every post.
        self.assertTrue(
            cases["task"]["posted"],
            "the root session's own 'task' completion must still fire a passive capture",
        )

    def test_the_plugin_registers_no_system_prompt_hook(self):
        """The plugin used to append its own copy of the protocol to the root
        session's system prompt. That copy is gone: the shared block carries
        the protocol, so the plugin must not register the hook at all."""
        hooks = self._run_harness()["hooks"]
        self.assertNotIn("experimental.chat.system.transform", hooks)
        self.assertIn("tool.execute.after", hooks)
        self.assertIn("experimental.session.compacting", hooks)

    def test_the_posted_content_has_real_newlines_and_a_line_start_heading(self):
        data = self._run_harness()
        cases = {c["tool"]: c for c in data["cases"]}
        content = cases["task"]["body"]["content"]
        # A literal "\n" surviving as two characters (backslash, n) would
        # mean the plugin sent a JSON.stringify() dump instead of the raw
        # output string -- the exact regression this fix removes.
        self.assertIn("\n", content)
        self.assertNotIn("\\n", content)
        self.assertRegex(content, ENGRAM_LEARNING_HEADER_PATTERN)


class EngramLearningsFormatContractTest(unittest.TestCase):
    """The heading DARQ's ambient content tells a sub-agent to write must
    be one engram v1.20.0's extractor actually recognizes, and an example
    item must clear its own length floor (20+ chars, 4+ words) -- both
    checked against the pattern copied from engram's source, not restated
    from what this repo hopes the server does."""

    def test_the_key_learnings_heading_matches_engrams_extractor(self):
        self.assertRegex("## Key Learnings", ENGRAM_LEARNING_HEADER_PATTERN)

    def test_a_conforming_item_clears_engrams_length_floor(self):
        item = "This is a durable finding worth keeping across sessions."
        stripped = re.sub(r"[*_`]", "", item)
        self.assertGreaterEqual(len(stripped), 20)
        self.assertGreaterEqual(len(stripped.split()), 4)

    def test_every_heading_form_the_content_or_plugin_names_matches_engrams_regex(self):
        # Review item 1 (Blocking): the convention and the plugin used to
        # list `# Learnings` (H1) as a recognized heading, but engram
        # v1.20.0's own pattern is anchored to two or three `#` -- an H1
        # never matches it, so a sub-agent following that doc would lose
        # its items silently. This scans every backtick-quoted
        # `#`/`##`/`###` + "Learnings" mention in shipped content and the
        # plugin source and asserts each one actually matches engram's
        # regex; `# Learnings` reappearing anywhere would fail this.
        pattern = re.compile(r"`(#{1,3}\s*(?:Key\s+)?Learnings)`")
        mentions: dict[str, list[str]] = {}
        for path in list(CONTENT.rglob("*.md")) + [PLUGIN]:
            text = read(path)
            for match in pattern.finditer(text):
                mentions.setdefault(match.group(1), []).append(str(path.relative_to(ROOT)))
        self.assertTrue(mentions, "no heading form found — the extraction pattern may have drifted")
        for heading, paths in mentions.items():
            with self.subTest(heading=heading, files=paths):
                self.assertRegex(heading, ENGRAM_LEARNING_HEADER_PATTERN)


class PluginNoLongerInjectsProtocolTest(unittest.TestCase):
    """The protocol reaches every session through the shared block alone."""

    def setUp(self):
        self.text = read(PLUGIN)

    def test_no_system_prompt_hook_in_the_source(self):
        self.assertNotIn("system.transform", self.text)
        self.assertNotIn("output.system", self.text)

    def test_no_protocol_constant_in_the_source(self):
        self.assertNotIn("MEMORY_INSTRUCTIONS", self.text)
        self.assertNotIn("WHO WRITES", self.text)


#: The sentence the shared block states for the agent talking with the person.
KEY_LEARNINGS_AUTOMATIC = (
    "Its items are saved automatically when its reply returns, one observation each: "
    "don't save them again yourself, and never search memory just to confirm they landed."
)


class KeyLearningsAutomaticStatementTest(unittest.TestCase):
    """The shared block states, unconditionally, that a launched agent's
    `## Key Learnings` items are saved automatically. That is only true
    because a capture is installed wherever the block is: the OpenCode
    plugin ships on every install, and Claude Code's `SubagentStop` hook
    ships whenever engram is selected -- the same condition that installs
    the block. These tests render both CLIs with the shipped content."""

    @classmethod
    def setUpClass(cls):
        from darq import cli
        from darq.adapters.claudecode import Adapter as ClaudeAdapter
        from darq.adapters.opencode import Adapter as OpenCodeAdapter
        from darq.core import content as content_module
        from darq.core.types import ConfigKeyArtifact, Environment, FileArtifact

        cls.ConfigKeyArtifact, cls.FileArtifact = ConfigKeyArtifact, FileArtifact
        home = Path("/home/example")
        environment = Environment(home=home, data_dir=home / ".local" / "share" / "darq")
        cls.identity = cli.default_identity()
        loaded = content_module.load()
        cls.with_engram = content_module.select_mcp(loaded, ["engram"])
        cls.without_engram = content_module.select_mcp(loaded, [])
        cls.adapters = {"opencode": OpenCodeAdapter(), "claudecode": ClaudeAdapter()}
        cls.layouts = {name: adapter.layout(environment) for name, adapter in cls.adapters.items()}

    def _rendered(self, name: str, loaded) -> str:
        artifacts = self.adapters[name].render_system_prompt(
            self.layouts[name], loaded.system_prompt, self.identity
        )
        files = [item for item in artifacts if isinstance(item, self.FileArtifact)]
        self.assertEqual(len(files), 1)
        return files[0].content.decode("utf-8")

    def test_the_block_source_states_it_once(self):
        self.assertEqual(" ".join(read(AMBIENT).split()).count(KEY_LEARNINGS_AUTOMATIC), 1)

    def test_the_block_no_longer_hedges_on_the_launchers_own_instructions(self):
        self.assertNotIn("If your own instructions state", read(AMBIENT))

    def test_both_clis_render_the_statement_once_when_engram_is_selected(self):
        for name in self.adapters:
            with self.subTest(cli=name):
                text = " ".join(self._rendered(name, self.with_engram).split())
                self.assertEqual(text.count(KEY_LEARNINGS_AUTOMATIC), 1)

    def test_neither_cli_renders_it_without_engram(self):
        for name in self.adapters:
            with self.subTest(cli=name):
                text = " ".join(self._rendered(name, self.without_engram).split())
                self.assertNotIn("saved automatically", text)

    def test_claude_code_installs_the_subagent_stop_capture_with_engram(self):
        engram = next(item for item in self.with_engram.mcp if item.name == "engram")
        artifacts = self.adapters["claudecode"].render_mcp(self.layouts["claudecode"], engram)
        pointers = {item.pointer for item in artifacts if isinstance(item, self.ConfigKeyArtifact)}
        self.assertIn("/hooks/SubagentStop/-", pointers)

    def test_opencode_ships_the_capturing_plugin_unconditionally(self):
        adapter, layout = self.adapters["opencode"], self.layouts["opencode"]
        artifacts = adapter.own_artifacts(layout, "darq-orchestrator", self.identity, ())
        self.assertTrue(any(str(item.path).endswith("plugins/engram.ts") for item in artifacts))


if __name__ == "__main__":
    unittest.main()
