"""Classifier tests.

Written with stdlib unittest so they run with no third-party dependency:
    python3 -m unittest discover -s tests -t .

Every rejection case here was observed in the real corpus under
``~/.claude/projects``, with the measured counts recorded in the module
docstring of the classifier. These are regression guards against re-admitting
machine-authored text as "facts about the user".
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit.importers.claude_code import (  # noqa: E402
    MAX_TURN_CHARS,
    MIN_INDEX_CHARS,
    classify,
    extract_text,
)


def line(**kw):
    base = {
        "type": "user",
        "uuid": "u-1",
        "sessionId": "s-1",
        "timestamp": "2026-07-01T10:00:00Z",
        "cwd": "/Users/me/dev/notiky",
        "gitBranch": "main",
        "promptSource": "typed",
        "message": {"content": "a real question about my project setup"},
    }
    base.update(kw)
    return base


def text_line(text: str, **kw):
    return line(message={"content": text}, **kw)


class TestExtractText(unittest.TestCase):
    def test_string_content(self):
        self.assertEqual(extract_text("  hello  "), "hello")

    def test_joins_text_blocks_only(self):
        content = [
            {"type": "text", "text": "keep me"},
            {"type": "thinking", "thinking": "drop me"},
            {"type": "tool_use", "name": "Bash", "input": {}},
            {"type": "text", "text": "and me"},
        ]
        self.assertEqual(extract_text(content), "keep me\nand me")

    def test_tool_result_yields_nothing(self):
        content = [{"type": "tool_result", "content": "AWS_SECRET=abc"}]
        self.assertEqual(extract_text(content), "")

    def test_unknown_shape(self):
        self.assertEqual(extract_text(None), "")
        self.assertEqual(extract_text(42), "")


class TestRejections(unittest.TestCase):
    def assertRejected(self, ln, reason):
        turn, got = classify(ln)
        self.assertIsNone(turn, f"expected rejection, got a turn ({got})")
        self.assertEqual(got, reason)

    def test_interrupt_marker(self):
        self.assertRejected(
            text_line("[Request interrupted by user]", promptSource=None),
            "interrupt-marker",
        )

    def test_interrupt_marker_tool_variant(self):
        self.assertRejected(
            text_line("[Request interrupted by user for tool use]", promptSource=None),
            "interrupt-marker",
        )

    def test_slash_command(self):
        self.assertRejected(
            text_line("<command-name>/model</command-name>", promptSource=None),
            "slash-command",
        )

    def test_local_command_output(self):
        self.assertRejected(
            text_line("<local-command-stdout>Set model</local-command-stdout>",
                      promptSource=None),
            "command-output",
        )

    def test_bash_io(self):
        self.assertRejected(
            text_line("<bash-input>pnpm i -g pnpm</bash-input>", promptSource=None),
            "bash-io",
        )

    def test_task_notification(self):
        self.assertRejected(
            text_line("<task-notification>\n<task-id>abc</task-id>", promptSource="sdk"),
            "task-notification",
        )

    def test_compaction_summary(self):
        self.assertRejected(
            text_line("This session is being continued from a previous conversation",
                      promptSource=None),
            "compaction-summary",
        )

    def test_agent_brief(self):
        self.assertRejected(
            text_line("# Peer brief\n\nRole: reviewer", promptSource=None),
            "agent-brief",
        )

    def test_system_prompt_source(self):
        self.assertRejected(text_line("injected text", promptSource="system"),
                            "source:system")

    def test_tool_result_content(self):
        self.assertRejected(
            line(message={"content": [{"type": "tool_result", "content": "x"}]}),
            "tool_result",
        )

    def test_sidechain(self):
        self.assertRejected(line(isSidechain=True), "sidechain")

    def test_meta(self):
        self.assertRejected(line(isMeta=True), "meta")

    def test_non_conversational_type(self):
        self.assertRejected(line(type="ai-title"), "type:ai-title")

    def test_empty_text(self):
        self.assertRejected(line(message={"content": ""}), "no-text")

    def test_oversized_document_is_rejected(self):
        # The three real offenders were 78k, 86k and 129k chars: copies of a
        # plan document that alone accounted for 63% of all user text.
        doc = "# Clockster LMS Module — Implementation Plan\n\n" + ("x" * MAX_TURN_CHARS)
        self.assertRejected(text_line(doc, promptSource=None), "oversized-document")

    def test_oversized_applies_to_assistant_too(self):
        self.assertRejected(
            line(type="assistant", message={"content": "y" * (MAX_TURN_CHARS + 1)}),
            "oversized-document",
        )

    def test_missing_ids(self):
        self.assertRejected(line(uuid=None), "missing-ids")


class TestAcceptances(unittest.TestCase):
    def test_typed_turn_accepted(self):
        turn, reason = classify(text_line("can you work on the certificates page?"))
        self.assertIsNotNone(turn)
        self.assertEqual(reason, "user:typed")
        self.assertEqual(turn.external_id, "u-1")
        self.assertEqual(turn.project, "notiky")
        self.assertEqual(turn.git_branch, "main")
        self.assertTrue(turn.indexable)

    def test_desktop_sdk_turn_accepted(self):
        # 419 of the corpus's user turns arrive this way: entrypoint
        # claude-desktop, userType external. Real humans, despite the name.
        turn, reason = classify(
            text_line("where do i see the list of conversations?",
                      promptSource="sdk", entrypoint="claude-desktop")
        )
        self.assertIsNotNone(turn)
        self.assertEqual(reason, "user:sdk")

    def test_unlabelled_but_conversational_accepted(self):
        turn, reason = classify(
            text_line("Analytics page is very bad looking, you gotta work on this",
                      promptSource=None)
        )
        self.assertIsNotNone(turn)
        self.assertEqual(reason, "user:n/a")

    def test_short_filler_stored_but_not_indexed(self):
        # "continue" and "go on" are genuinely human, so they stay in SQLite to
        # keep extraction windows faithful, but indexing them is pure noise.
        turn, _ = classify(text_line("continue"))
        self.assertIsNotNone(turn)
        self.assertFalse(turn.indexable)
        self.assertLess(len(turn.text), MIN_INDEX_CHARS)

    def test_assistant_text_kept_but_never_indexable(self):
        turn, reason = classify(
            line(type="assistant",
                 message={"content": [{"type": "text", "text": "x" * 200}]})
        )
        self.assertIsNotNone(turn)
        self.assertEqual(reason, "assistant")
        # Needed for stage-2 window context; must not pollute a search over the
        # user's own history.
        self.assertFalse(turn.indexable)

    def test_cyrillic_preserved(self):
        turn, _ = classify(text_line("но не всегда же подставляются, проверь пожалуйста"))
        self.assertIsNotNone(turn)
        self.assertIn("подставляются", turn.text)

    def test_missing_cwd_gives_no_project(self):
        turn, _ = classify(text_line("a question long enough to index", cwd=None))
        self.assertIsNotNone(turn)
        self.assertIsNone(turn.project)


if __name__ == "__main__":
    unittest.main(verbosity=2)
