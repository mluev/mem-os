"""Extraction end to end, against a real database and a fake provider.

The pipeline was only ever exercised at its edges: `apply_ops` had thorough
unit coverage and `judge.extract` was tested with a patched provider, but
nothing drove `run_extraction` itself. The failures that hurt live there --
what a window costs when the provider is unreachable, whether a batch of
messages is ever finished, and whether a leased window can wedge a loop.
"""

from __future__ import annotations

import os
import threading
import unittest
from datetime import timedelta

from memkit import entities, extract, judge, providers
from memkit.db import ConnectionPool, advisory_lock, connect, utcnow
from memkit.retrieval import _token_count
from tests.fixtures import add_messages, fake_provider, make_db, make_session, seed_team

MODEL = "fake-judge"


def _result(operations=None, **kw):
    return providers.ProviderResult(operations=operations or [], raw={"operations": []}, **kw)


def _add(text: str, **kw):
    return {
        "op": "ADD",
        "text": text,
        "kind": "preference",
        "reason": "stated by the user",
        # Offsets are required keys even when a quote supersedes them: the
        # server derives authoritative offsets from a unique verbatim quote.
        "evidence": [
            {
                "message_id": kw["message_id"],
                "start_char": 0,
                "end_char": 0,
                "quote": kw["quote"],
            }
        ],
        **{key: value for key, value in kw.items() if key in {"scope", "subject", "subject_name"}},
    }


class PipelineCase(unittest.TestCase):
    """A seeded team with one session of Alice's, ready to be extracted from."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)

    def tearDown(self) -> None:
        self.conn.close()

    def run_extraction(self, handler, **kw):
        with fake_provider(handler):
            return extract.run_extraction(
                self.conn,
                session_id="s-1",
                agent_id="chat",
                monthly_limit_usd=10.0,
                model=MODEL,
                api_key="",
                gemini_api_key="",
                project="",
                location="",
                **kw,
            )

    def ref(self, name: str) -> int:
        """The number the prompt shows for an entity, as the extractor builds it."""
        block = entities.for_prompt(self.conn, user_id=self.team.alice_id)
        return next(index + 1 for index, item in enumerate(block) if item["name"] == name)

    def unprocessed(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM messages WHERE NOT processed").fetchone()
        return int(row["n"])


class ExtractionRunTest(PipelineCase):
    def test_a_cited_user_statement_becomes_a_memory(self) -> None:
        ids = add_messages(self.conn, n=10, content="I always use pnpm, never npm")
        outcome = self.run_extraction(
            lambda **_: _result(
                [_add("Prefers pnpm over npm", message_id=ids[0], quote="I always use pnpm")],
                input_tokens=900,
                output_tokens=40,
            ),
            force=True,
        )
        self.assertIsNone(outcome.error)
        self.assertEqual(outcome.added, 1)
        row = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertEqual(row["text"], "Prefers pnpm over npm")
        self.assertEqual(row["source_role"], "user")
        self.assertEqual(str(row["scope_id"]), self.team.scope_of("alice"))
        self.assertTrue(
            self.conn.execute(
                "SELECT 1 FROM memory_evidence WHERE memory_id=%s", (row["id"],)
            ).fetchone()
        )
        self.assertEqual(self.unprocessed(), 0)

    def test_the_session_decides_whose_memory_a_window_becomes(self) -> None:
        """The authorization anchor is the session row, not a parameter.

        Nothing a client sends may redirect extraction into another person's
        space, so a session of Bob's writes to Bob even when the run is started
        by whatever process happens to hold the queue.
        """
        make_session(self.conn, self.team, session_id="s-bob", who="bob")
        ids = add_messages(self.conn, n=10, content="I always use fish, never zsh", session="s-bob")
        with fake_provider(
            lambda **_: _result(
                [_add("Prefers fish over zsh", message_id=ids[0], quote="I always use fish")]
            )
        ):
            outcome = extract.run_extraction(
                self.conn,
                session_id="s-bob",
                agent_id="chat",
                monthly_limit_usd=10.0,
                model=MODEL,
                api_key="",
                gemini_api_key="",
                project="",
                location="",
                force=True,
            )
        self.assertEqual(outcome.added, 1)
        row = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertEqual(str(row["scope_id"]), self.team.scope_of("bob"))
        self.assertEqual(str(row["author_id"]), self.team.bob_id)

    def test_a_fact_about_a_teammate_is_routed_by_number(self) -> None:
        """The whole routing chain, from entity block to stored scope.

        Unit tests fix each half; only this one proves the numbering the prompt
        showed is the numbering `apply_ops` resolves against.
        """
        ids = add_messages(self.conn, n=10, content="Bob Petrov reviews only on Fridays")
        outcome = self.run_extraction(
            lambda **_: _result(
                [
                    _add(
                        "Bob reviews only on Fridays",
                        message_id=ids[0],
                        quote="Bob Petrov reviews only on Fridays",
                        subject=self.ref("Bob Petrov"),
                    )
                ]
            ),
            force=True,
        )
        self.assertEqual(outcome.added, 1)
        row = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertEqual(str(row["scope_id"]), self.team.team_id)
        self.assertEqual(str(row["subject_id"]), self.team.scope_of("bob"))
        self.assertEqual(row["review_status"], "pending")

    def test_an_unreachable_provider_costs_nothing(self) -> None:
        """A failure that never reached a model must not be charged.

        The cost of a failed call used to be recorded as the reservation
        ceiling: a UTF-8-byte input estimate plus a full 4096-token completion.
        Because the monthly ceiling is enforced by summing judge_runs.cost_usd,
        a bad key or a network outage could exhaust the budget on spend that was
        never billed, and nothing reconciled it afterwards.
        """
        add_messages(self.conn, n=10)

        def refuse(**_):
            raise ConnectionRefusedError("connection refused")

        outcome = self.run_extraction(refuse, force=True)
        self.assertIsNotNone(outcome.error)
        run = self.conn.execute("SELECT cost_usd, error FROM judge_runs").fetchone()
        self.assertEqual(float(run["cost_usd"]), 0.0)
        self.assertTrue(run["error"].startswith("unbilled:"))
        self.assertEqual(outcome.cost_usd, 0.0)

    def test_a_missing_key_costs_nothing(self) -> None:
        add_messages(self.conn, n=10)
        outcome = self.run_extraction(
            lambda **_: _result(error="no GEMINI_API_KEY set"), force=True
        )
        self.assertIsNotNone(outcome.error)
        run = self.conn.execute("SELECT cost_usd FROM judge_runs").fetchone()
        self.assertEqual(float(run["cost_usd"]), 0.0)

    def test_an_unclassified_failure_is_estimated_without_a_completion(self) -> None:
        """Unknown failures may have been billed for the prompt, never for output."""
        add_messages(self.conn, n=10)
        seen: dict[str, str] = {}

        def explode(**kwargs):
            seen["prompt"] = kwargs["prompt"]
            raise RuntimeError("something unrecognised")

        self.run_extraction(explode, force=True)
        run = self.conn.execute("SELECT cost_usd, error FROM judge_runs").fetchone()
        self.assertTrue(run["error"].startswith("cost_unknown:"))
        # The same conservative input estimate the reservation used, priced with
        # no completion at all -- that difference is the whole regression.
        prompt = seen["prompt"]
        estimate = max(_token_count(prompt), len(prompt.encode("utf-8")))
        self.assertEqual(float(run["cost_usd"]), judge.cost_of(estimate, 0, model=MODEL))
        self.assertLess(float(run["cost_usd"]), judge.cost_of(estimate, 4096, model=MODEL))


class RememberGateTest(PipelineCase):
    """ "Remember this" anywhere in the window must trigger extraction.

    The gate read only the last message of the claimed window, so on the batch
    path an explicit request buried mid-window was invisible whenever the final
    claimed message was an assistant turn.
    """

    def test_request_in_an_earlier_message_is_honoured(self) -> None:
        add_messages(self.conn, n=1, content="запомни: мы используем pnpm везде")
        add_messages(self.conn, n=1, role="assistant", content="Готово.")
        calls: list[str] = []

        def handler(**kwargs):
            calls.append(kwargs["prompt"])
            return _result()

        outcome = self.run_extraction(handler)
        self.assertEqual(len(calls), 1, "an explicit remember request was ignored")
        self.assertFalse(outcome.declined)


class SessionDrainTest(PipelineCase):
    """A queued job must finish the session, not one window of it.

    `run_extraction` claims exactly one ten-message window; nothing re-queued it
    on success. The batch evidence endpoint queues one job per session per
    request and the Claude Code hook posts in hundred-event chunks, so a long
    session kept most of its messages unprocessed forever.
    """

    def drain(self, *, max_windows: int, handler=None, cancelled=None):
        handler = handler or (lambda **_: _result())
        with fake_provider(handler):
            return extract.run_session_extraction(
                self.conn,
                max_windows=max_windows,
                cancelled=cancelled,
                session_id="s-1",
                agent_id="chat",
                monthly_limit_usd=10.0,
                model=MODEL,
                api_key="",
                gemini_api_key="",
                project="",
                location="",
                force=True,
            )

    def test_one_run_clears_a_multi_window_backlog(self) -> None:
        add_messages(self.conn, n=25)
        outcome = self.drain(max_windows=3)
        self.assertEqual(outcome.windows, 3)
        self.assertEqual(outcome.claimed, 25)
        self.assertEqual(self.unprocessed(), 0)

    def test_the_window_cap_is_respected(self) -> None:
        add_messages(self.conn, n=25)
        outcome = self.drain(max_windows=2)
        self.assertEqual(outcome.windows, 2)
        self.assertEqual(self.unprocessed(), 5)

    def test_a_provider_error_stops_the_loop(self) -> None:
        add_messages(self.conn, n=25)
        calls: list[int] = []

        def failing(**_):
            calls.append(1)
            raise ConnectionRefusedError("down")

        outcome = self.drain(max_windows=3, handler=failing)
        self.assertEqual(len(calls), 1, "a dead provider was retried per window")
        self.assertIsNotNone(outcome.error)

    def test_cancellation_is_honoured_between_windows(self) -> None:
        add_messages(self.conn, n=25)
        outcome = self.drain(max_windows=3, cancelled=lambda: True)
        self.assertEqual(outcome.windows, 0)
        self.assertEqual(self.unprocessed(), 25)

    def test_a_leased_window_does_not_spin(self) -> None:
        """Unclaimable work must end the loop rather than repeat forever.

        A window held by another job's live lease yields no rows and no
        progress, which is indistinguishable from an empty session unless the
        loop stops on `claimed == 0`.
        """
        add_messages(self.conn, n=10)
        self.conn.execute(
            "UPDATE messages SET claim_token='other-job', claim_expires_at=%s",
            (utcnow() + timedelta(minutes=5),),
        )
        outcome = self.drain(max_windows=5)
        self.assertEqual(outcome.claimed, 0)
        self.assertEqual(outcome.windows, 0)


class WindowClaimConcurrencyTest(PipelineCase):
    """Two workers must never process the same messages.

    The lease exists so a provider call is never paid for twice. Real threads on
    pooled connections, because that is what the worker does: a claim proved
    safe only against sequential calls proves nothing about the case it exists
    for.
    """

    WORKERS = 8

    def test_only_one_of_many_racing_claims_wins(self) -> None:
        add_messages(self.conn, n=10)
        pool = ConnectionPool(os.environ["MEMKIT_DATABASE_URL"], max_size=self.WORKERS)
        self.addCleanup(pool.close_all)
        results: list[int] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(self.WORKERS)
        guard = threading.Lock()

        def claim(index: int) -> None:
            try:
                with pool.borrow() as worker:
                    barrier.wait(timeout=10)
                    window = extract.claim_window(worker, session_id="s-1", job_id=f"job-{index}")
                with guard:
                    results.append(len(window))
            except BaseException as exc:  # a thread must not fail silently
                with guard:
                    errors.append(exc)

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(self.WORKERS)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertEqual(errors, [])
        self.assertEqual([count for count in results if count], [10], "a window was claimed twice")
        self.assertEqual(len(results), self.WORKERS)

    def test_an_expired_lease_can_be_reclaimed(self) -> None:
        """A worker that dies mid-window must not strand its messages."""
        add_messages(self.conn, n=10)
        self.conn.execute(
            "UPDATE messages SET claim_token='dead-job', claim_expires_at=%s",
            (utcnow() - timedelta(hours=1),),
        )
        window = extract.claim_window(self.conn, session_id="s-1", job_id="fresh")
        self.assertEqual(len(window), 10)

    def test_racing_workers_preserve_contiguous_window_boundaries(self) -> None:
        """SKIP LOCKED alone must not interleave portions of the ordered windows."""
        add_messages(self.conn, n=25)
        ordered = [
            int(r["id"])
            for r in self.conn.execute(
                "SELECT id FROM messages WHERE session_id='s-1' ORDER BY id"
            ).fetchall()
        ]
        expected = [ordered[start : start + 10] for start in range(0, len(ordered), 10)]
        pool = ConnectionPool(os.environ["MEMKIT_DATABASE_URL"], max_size=self.WORKERS)
        self.addCleanup(pool.close_all)
        # Several independent races exercise scheduling variation without a provider.
        for iteration in range(12):
            self.conn.execute("UPDATE messages SET claim_token=NULL,claim_expires_at=NULL")
            barrier = threading.Barrier(self.WORKERS)
            windows: list[list[int]] = []
            errors: list[BaseException] = []
            guard = threading.Lock()

            def claim(index: int, barrier, guard, windows, errors) -> None:
                try:
                    with pool.borrow() as worker:
                        barrier.wait(timeout=10)
                        rows = extract.claim_window(worker, session_id="s-1", job_id=f"job-{index}")
                    with guard:
                        windows.append([int(row["id"]) for row in rows])
                except BaseException as exc:
                    with guard:
                        errors.append(exc)

            threads = [
                threading.Thread(target=claim, args=(i, barrier, guard, windows, errors))
                for i in range(self.WORKERS)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=20)
            self.assertEqual(errors, [])
            self.assertEqual(len(windows), self.WORKERS)
            self.assertEqual(sorted(w for w in windows if w), expected, f"race {iteration}")

    def test_one_session_claim_does_not_wait_for_another_sessions_expired_rows(self) -> None:
        add_messages(self.conn, n=1)
        make_session(self.conn, self.team, session_id="s-2")
        add_messages(self.conn, n=2, session="s-2")
        self.conn.execute(
            "UPDATE messages SET claim_token='expired',claim_expires_at=%s WHERE session_id='s-1'",
            (utcnow() - timedelta(hours=1),),
        )
        with connect(os.environ["MEMKIT_DATABASE_URL"]) as other, self.conn.transaction():
            advisory_lock(self.conn, "extraction-window:s-1")
            self.conn.execute("SELECT id FROM messages WHERE session_id='s-1' FOR UPDATE")
            other.execute("SET lock_timeout='100ms'")
            claimed = extract.claim_window(other, session_id="s-2", job_id="second-session")
        self.assertEqual(len(claimed), 2)
        self.assertEqual({row["session_id"] for row in claimed}, {"s-2"})


if __name__ == "__main__":
    unittest.main()
