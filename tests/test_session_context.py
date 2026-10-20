"""Session context across window boundaries (decisions/0083).

A ten-message window ends wherever ten messages happen to end, so "that hotel"
in the window often points at a turn just before it. Prompt v12 shows the last
few earlier messages as EARLIER IN THIS SESSION: unnumbered, so the model cannot
cite them, and checked anyway, because a prompt rule is a request. Older
versions render exactly as before.
"""

from __future__ import annotations

from memkit import judge
from tests.fixtures import add_messages
from tests.test_extraction_pipeline import PipelineCase, _add, _result


class SessionContextTest(PipelineCase):
    def earlier(self) -> list[int]:
        """Two exchanges already extracted, ending just before the next window."""
        ids = []
        for role, content in (
            ("user", "Planning a March trip to Lisbon"),
            ("assistant", "Lisbon in March is mild; Alfama is lovely"),
            ("user", "Which hotel would you suggest there?"),
            ("assistant", "Hotel Lisboa Plaza near Avenida da Liberdade"),
        ):
            ids += add_messages(self.conn, n=1, role=role, content=content)
        with self.conn.transaction():
            self.conn.execute("UPDATE messages SET processed=true WHERE id=ANY(%s)", (ids,))
        return ids

    def capture(self, operations=None):
        prompts: list[str] = []

        def handler(**kwargs):
            prompts.append(kwargs["prompt"])
            return _result(operations or [])

        return prompts, handler

    def test_v12_shows_earlier_messages_without_numbers(self) -> None:
        earlier = self.earlier()
        add_messages(self.conn, n=10, content="Booked it for the 14th")
        prompts, handler = self.capture()
        outcome = self.run_extraction(handler, force=True, prompt_version="v12")
        self.assertIsNone(outcome.error)
        header = "EARLIER IN THIS SESSION (context only; never cite it)\n"
        block = prompts[0].split(header)[1].split("\n\nCONVERSATION WINDOW")[0]
        self.assertIn("assistant: Hotel Lisboa Plaza near Avenida da Liberdade 0", block)
        for message_id in earlier:
            self.assertNotIn(f"[{message_id}]", block)
        run = self.conn.execute(
            "SELECT input FROM judge_runs WHERE id=%s", (outcome.judge_run_id,)
        ).fetchone()
        self.assertEqual(run["input"]["prior_message_ids"], earlier)
        self.assertEqual(run["input"]["assistant_chars"], 1200)

    def test_older_versions_render_without_earlier_messages(self) -> None:
        self.earlier()
        add_messages(self.conn, n=10, content="Booked it for the 14th")
        prompts, handler = self.capture()
        outcome = self.run_extraction(handler, force=True, prompt_version="v11")
        self.assertNotIn("EARLIER IN THIS SESSION", prompts[0])
        self.assertNotIn("Lisboa Plaza", prompts[0])
        run = self.conn.execute(
            "SELECT input FROM judge_runs WHERE id=%s", (outcome.judge_run_id,)
        ).fetchone()
        self.assertEqual(run["input"]["prior_message_ids"], [])
        self.assertEqual(run["input"]["assistant_chars"], judge.ASSISTANT_CONTEXT_CHARS)

    def test_an_earlier_message_cannot_be_cited(self) -> None:
        earlier = self.earlier()
        add_messages(self.conn, n=10, content="Booked it for the 14th")
        _, handler = self.capture(
            [_add("The user is planning a March trip", message_id=earlier[0], quote="March trip")]
        )
        outcome = self.run_extraction(handler, force=True, prompt_version="v12")
        self.assertEqual(outcome.added, 0)
        self.assertEqual([r["reason"] for r in outcome.rejections], ["evidence_invalid"])

    def test_an_answer_cut_off_from_its_question_is_still_read_under_v12(self) -> None:
        self.earlier()
        add_messages(self.conn, n=1, role="assistant", content="Its rooms start at 180 euros")
        prompts, handler = self.capture()
        skipped = self.run_extraction(handler, force=True, prompt_version="v11")
        self.assertEqual(prompts, [])
        self.assertEqual(skipped.skipped, 1)

        add_messages(self.conn, n=1, role="assistant", content="Breakfast is included")
        outcome = self.run_extraction(handler, force=True, prompt_version="v12")
        self.assertIsNone(outcome.error)
        self.assertEqual(len(prompts), 1)
        self.assertIn("Breakfast is included", prompts[0])

    def test_a_tail_with_no_question_before_it_is_still_skipped(self) -> None:
        add_messages(self.conn, n=2, role="assistant", content="Done, tests pass")
        prompts, handler = self.capture()
        outcome = self.run_extraction(handler, force=True, prompt_version="v12")
        self.assertEqual(prompts, [])
        self.assertEqual(outcome.skipped, 2)
