"""Extraction end to end, against a real database and a fake provider.

The pipeline was only ever exercised at its edges: `apply_ops` had thorough
unit coverage and `judge.extract` was tested with a patched provider, but
nothing drove `run_extraction` itself. The failures that hurt live there --
what a window costs when the provider is unreachable, whether a batch of
messages is ever finished, and whether a leased window can wedge a loop.
"""

from __future__ import annotations

import pathlib
import unittest
from datetime import UTC, datetime, timedelta

from memkit import extract, judge, providers
from tests.fixtures import OWNER, add_messages, fake_provider, make_db

MODEL = "fake-judge"


def _result(operations=None, **kw):
    return providers.ProviderResult(operations=operations or [], raw={"operations": []}, **kw)


def _future(minutes: int = 5) -> str:
    """A lease expiry in the store's own timestamp format.

    Timestamps are compared lexicographically as text, so the shape matters:
    `db.utcnow` writes a trailing Z, and an isoformat offset would sort wrong.
    """
    stamp = datetime.now(UTC) + timedelta(minutes=minutes)
    return stamp.isoformat(timespec="seconds").replace("+00:00", "Z")


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
    }


class ExtractionRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()

    def tearDown(self) -> None:
        self.conn.close()

    def _run(self, handler, **kw):
        with fake_provider(handler):
            return extract.run_extraction(
                self.conn,
                session_id="s-1",
                owner_id=OWNER,
                agent_id="chat",
                monthly_limit_usd=10.0,
                model=MODEL,
                api_key="",
                gemini_api_key="",
                project="",
                location="",
                **kw,
            )

    def test_a_cited_user_statement_becomes_a_memory(self) -> None:
        ids = add_messages(self.conn, n=10, content="I always use pnpm, never npm")
        outcome = self._run(
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
        self.assertTrue(
            self.conn.execute(
                "SELECT 1 FROM memory_evidence WHERE memory_id=?", (row["id"],)
            ).fetchone()
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM messages WHERE processed=1").fetchone()[0], 10
        )

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

        outcome = self._run(refuse, force=True)
        self.assertIsNotNone(outcome.error)
        run = self.conn.execute("SELECT cost_usd, error FROM judge_runs").fetchone()
        self.assertEqual(run["cost_usd"], 0.0)
        self.assertTrue(run["error"].startswith("unbilled:"))
        self.assertEqual(outcome.cost_usd, 0.0)

    def test_a_missing_key_costs_nothing(self) -> None:
        add_messages(self.conn, n=10)
        outcome = self._run(lambda **_: _result(error="no GEMINI_API_KEY set"), force=True)
        self.assertIsNotNone(outcome.error)
        self.assertEqual(
            self.conn.execute("SELECT cost_usd FROM judge_runs").fetchone()["cost_usd"], 0.0
        )

    def test_an_unclassified_failure_is_estimated_without_a_completion(self) -> None:
        """Unknown failures may have been billed for the prompt, never for output."""
        add_messages(self.conn, n=10)

        def explode(**_):
            raise RuntimeError("something unrecognised")

        self._run(explode, force=True)
        run = self.conn.execute("SELECT cost_usd, error FROM judge_runs").fetchone()
        self.assertGreater(run["cost_usd"], 0.0)
        self.assertTrue(run["error"].startswith("cost_unknown:"))
        prompt_only = judge.cost_of(10_000, 0, model=MODEL)
        with_completion = judge.cost_of(10_000, 4096, model=MODEL)
        self.assertLess(run["cost_usd"], with_completion)
        self.assertLess(run["cost_usd"] / max(prompt_only, 1e-9), 1e9)


class RememberGateTest(unittest.TestCase):
    """ "Remember this" anywhere in the window must trigger extraction.

    The gate read only the last message of the claimed window, so on the batch
    path an explicit request buried mid-window was invisible whenever the final
    claimed message was an assistant turn.
    """

    def setUp(self) -> None:
        self.conn = make_db()

    def tearDown(self) -> None:
        self.conn.close()

    def test_request_in_an_earlier_message_is_honoured(self) -> None:
        self.conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES ('s-1','user','запомни: мы используем pnpm везде','2026-07-01T00:00:00Z')"
        )
        self.conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES ('s-1','assistant','Готово.','2026-07-01T00:00:01Z')"
        )
        self.conn.commit()
        calls: list[str] = []

        def handler(**kwargs):
            calls.append(kwargs["prompt"])
            return _result()

        with fake_provider(handler):
            outcome = extract.run_extraction(
                self.conn,
                session_id="s-1",
                owner_id=OWNER,
                agent_id="chat",
                monthly_limit_usd=10.0,
                model=MODEL,
                api_key="",
                gemini_api_key="",
                project="",
                location="",
            )
        self.assertEqual(len(calls), 1, "an explicit remember request was ignored")
        self.assertFalse(outcome.declined)


class SessionDrainTest(unittest.TestCase):
    """A queued job must finish the session, not one window of it.

    `run_extraction` claims exactly one ten-message window; nothing re-queued it
    on success. The batch evidence endpoint queues one job per session per
    request and the Claude Code hook posts in hundred-event chunks, so a long
    session kept most of its messages unprocessed forever.
    """

    def setUp(self) -> None:
        self.conn = make_db()

    def tearDown(self) -> None:
        self.conn.close()

    def _drain(self, *, max_windows: int, handler=None, cancelled=None):
        handler = handler or (lambda **_: _result())
        with fake_provider(handler):
            return extract.run_session_extraction(
                self.conn,
                max_windows=max_windows,
                cancelled=cancelled,
                session_id="s-1",
                owner_id=OWNER,
                agent_id="chat",
                monthly_limit_usd=10.0,
                model=MODEL,
                api_key="",
                gemini_api_key="",
                project="",
                location="",
                force=True,
            )

    def _unprocessed(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM messages WHERE processed=0").fetchone()[0]

    def test_one_run_clears_a_multi_window_backlog(self) -> None:
        add_messages(self.conn, n=25)
        outcome = self._drain(max_windows=3)
        self.assertEqual(outcome.windows, 3)
        self.assertEqual(outcome.claimed, 25)
        self.assertEqual(self._unprocessed(), 0)

    def test_the_window_cap_is_respected(self) -> None:
        add_messages(self.conn, n=25)
        outcome = self._drain(max_windows=2)
        self.assertEqual(outcome.windows, 2)
        self.assertEqual(self._unprocessed(), 5)

    def test_a_provider_error_stops_the_loop(self) -> None:
        add_messages(self.conn, n=25)
        calls: list[int] = []

        def failing(**_):
            calls.append(1)
            raise ConnectionRefusedError("down")

        outcome = self._drain(max_windows=3, handler=failing)
        self.assertEqual(len(calls), 1, "a dead provider was retried per window")
        self.assertIsNotNone(outcome.error)

    def test_cancellation_is_honoured_between_windows(self) -> None:
        add_messages(self.conn, n=25)
        outcome = self._drain(max_windows=3, cancelled=lambda: True)
        self.assertEqual(outcome.windows, 0)
        self.assertEqual(self._unprocessed(), 25)

    def test_a_leased_window_does_not_spin(self) -> None:
        """Unclaimable work must end the loop rather than repeat forever."""
        add_messages(self.conn, n=10)
        self.conn.execute(
            "UPDATE messages SET claim_token='other-job', claim_expires_at=?",
            (_future(),),
        )
        self.conn.commit()
        outcome = self._drain(max_windows=5)
        self.assertEqual(outcome.claimed, 0)
        self.assertEqual(outcome.windows, 0)

    def test_replay_raises_instead_of_spinning_when_no_window_can_be_claimed(self) -> None:
        """Unprocessed messages that cannot be claimed must end replay, not spin.

        The loop was `while messages_since_last(...)`, and a window held by
        another job's live lease yields no rows and no progress, so it repeated
        at full speed forever with no iteration cap and no sleep. The lease is
        simulated here because apply_replay clears claims when it initializes,
        so the race can only start after that point.
        """
        from unittest.mock import patch

        from memkit import jobs, reextract

        job_id = jobs.create(self.conn, kind="legacy_replay_dry_run", input_data={"apply": True})
        add_messages(self.conn, n=10)

        def claims_nothing(connection, **_kwargs):
            return extract.ExtractionOutcome()

        with (
            patch("memkit.reextract.extract.run_session_extraction", claims_nothing),
            self.assertRaisesRegex(RuntimeError, "stalled"),
        ):
            reextract.apply_replay(
                self.conn,
                owner_id=OWNER,
                api_key="",
                gemini_api_key="",
                project="",
                location="",
                monthly_limit_usd=1.0,
                model=MODEL,
                job_id=job_id,
                cancelled=lambda: False,
            )


class WindowClaimConcurrencyTest(unittest.TestCase):
    """Two workers must never process the same messages.

    The lease exists so a provider call is never paid for twice, and the only
    existing test claimed sequentially. A window is claimed under BEGIN
    IMMEDIATE, so a race should leave exactly one winner.
    """

    def test_only_one_of_many_racing_claims_wins(self) -> None:
        import threading

        from memkit.db import connect

        conn = make_db()
        add_messages(conn, n=10)
        db_path = pathlib.Path(
            conn.execute("SELECT file FROM pragma_database_list WHERE name='main'").fetchone()[
                "file"
            ]
        )
        conn.close()

        results: list[int] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(8)

        def claim(index: int) -> None:
            worker = connect(db_path)
            try:
                barrier.wait(timeout=5)
                window = extract.claim_window(worker, session_id="s-1", job_id=f"job-{index}")
                results.append(len(window))
            except BaseException as exc:
                errors.append(exc)
            finally:
                worker.close()

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(results, reverse=True)[0], 10)
        self.assertEqual([count for count in results if count], [10], "a window was claimed twice")

    def test_an_expired_lease_can_be_reclaimed(self) -> None:
        conn = make_db()
        add_messages(conn, n=10)
        conn.execute(
            "UPDATE messages SET claim_token='dead-job', claim_expires_at='2020-01-01T00:00:00Z'"
        )
        conn.commit()
        window = extract.claim_window(conn, session_id="s-1", job_id="fresh")
        self.assertEqual(len(window), 10)
        conn.close()


if __name__ == "__main__":
    unittest.main()
