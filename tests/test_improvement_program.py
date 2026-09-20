"""What survives of the improvement program: backups, doctor, and the plan.

Most of this file used to be about `replay.py`, `release.py`, `evaluations.py`,
`policy_sweep.py` and `benchmark.py` -- a promotion pipeline that only worked
because the database was one file with one owner. On Postgres, "run the new
prompt on a copy" is a shadow database rather than a file copy, and there is
nothing waiting to be promoted, so the modules went and their tests with them.
See the notes at the bottom of this docstring for what was dropped and why.

Three pieces still exist and still gate operations:

* **Backups.** Real `pg_dump`/`pg_restore` here, not stubs: the whole point of
  a verified backup is that the archive was read back, and a stubbed verifier
  proves nothing. Restore is the interesting case -- it always refuses.
* **Doctor.** Every dependency named, once, with no secret in the output.
* **The re-extraction report.** The one part of the replay program that was
  actually used: what a prompt change would cost before anyone spends it.

Dropped with their modules: the shadow-replay job and its review manifest, the
blinded human evaluation and its release gate, the candidate-validation and
promotion gates, the 100k retrieval benchmark artefact, the offline policy
sweep, and the launchd/Docker service management (`install_service`,
`service_action`, `setup`, `ensure_qdrant`) that belonged to a single-machine
deployment. Job leases, budgets and worker recovery moved to
`test_durable_primitives.py`; the exact-identifier retrieval arm moved to
`test_fulltext.py`; generation pruning is covered by `test_reindex_v4.py`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from memkit import db, operations, reextract, store, telemetry
from tests.fixtures import StubEmbedder, StubQdrant, make_db, make_session, seed_team
from tests.httpharness import test_settings as _base_settings


class OperationsCase(unittest.TestCase):
    """Settings pointed at the test database and a throwaway backup directory."""

    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = _base_settings().model_copy(
            update={"backup_dir": self.tmp / "backups", "export_dir": self.tmp / "exports"}
        )
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _memory(self, text: str = "Prefers careful migrations") -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("alice"),
                author_id=self.team.alice_id,
                text=text,
                kind="preference",
                source_role="user",
                review_status="confirmed",
            )


class BackupTest(OperationsCase):
    def test_a_backup_is_verified_by_reading_it_back(self) -> None:
        """`pg_restore --list` parses every object header, so a truncated
        archive fails here rather than half-way through a restore."""
        self._memory()
        created = operations.create_backup(self.settings, kind="daily")
        self.assertEqual(created["kind"], "daily")
        verified = operations.verify_backup(
            Path(created["path"]), expected_sha256=created["sha256"]
        )
        self.assertGreater(verified["bytes"], 0)
        self.assertGreater(verified["entries"], 0)

    def test_the_archive_is_not_world_readable(self) -> None:
        created = operations.create_backup(self.settings, kind="daily")
        self.assertEqual(Path(created["path"]).stat().st_mode & 0o077, 0)

    def test_a_tampered_archive_fails_its_checksum(self) -> None:
        created = operations.create_backup(self.settings, kind="daily")
        path = Path(created["path"])
        path.write_bytes(path.read_bytes() + b"junk")
        with self.assertRaises(RuntimeError):
            operations.verify_backup(path, expected_sha256=created["sha256"])

    def test_a_file_that_is_not_an_archive_is_rejected(self) -> None:
        path = self.tmp / "not-a-dump.dump"
        path.write_bytes(b"this is not a custom-format dump")
        with self.assertRaises(Exception):
            operations.verify_backup(path)

    def test_a_missing_archive_is_a_file_error_not_a_silent_pass(self) -> None:
        with self.assertRaises(FileNotFoundError):
            operations.verify_backup(self.tmp / "absent.dump")

    def test_retention_keeps_the_newest_and_never_a_protected_one(self) -> None:
        """A pre-migration copy is the only thing standing between a bad
        migration and the data, so retention is not allowed to reach it."""
        daily = operations.create_backup(self.settings, kind="daily")
        weekly = operations.create_backup(self.settings, kind="weekly")
        protected = operations.create_backup(self.settings, kind="pre-migration")
        self.assertTrue(protected["protected"])
        self.assertEqual(len(operations.list_backups(self.settings)), 3)

        removed = operations.prune_backups(self.settings, keep_daily=0, keep_weekly=0)["removed"]
        self.assertIn(daily["path"], removed)
        self.assertIn(weekly["path"], removed)
        self.assertTrue(Path(protected["path"]).exists())
        self.assertFalse(Path(daily["path"]).exists())
        remaining = operations.list_backups(self.settings)
        self.assertEqual([str(row["id"]) for row in remaining], [protected["id"]])

    def test_retention_keeps_the_requested_number_of_dailies(self) -> None:
        first = operations.create_backup(self.settings, kind="daily")
        second = operations.create_backup(self.settings, kind="daily")
        operations.prune_backups(self.settings, keep_daily=1, keep_weekly=0)
        kept = {str(row["id"]) for row in operations.list_backups(self.settings)}
        self.assertEqual(kept, {second["id"]})
        self.assertFalse(Path(first["path"]).exists())

    def test_restore_hands_over_the_command_instead_of_running_it(self) -> None:
        """`pg_restore --clean` drops and recreates every object the archive
        holds, and this service cannot promise nothing else is connected --
        its own pool reconnects on demand. A half-replaced schema has no way
        back, so the archive is verified and the command is printed.
        """
        created = operations.create_backup(self.settings, kind="daily")
        with self.assertRaises(NotImplementedError) as raised:
            operations.restore_backup(self.settings, artifact_id=created["id"], confirm="RESTORE")
        message = str(raised.exception)
        self.assertIn("pg_restore --clean --if-exists", message)
        self.assertIn(created["path"], message)
        self.assertIn("memkit reindex", message)

    def test_restore_never_prints_a_password(self) -> None:
        created = operations.create_backup(self.settings, kind="daily")
        secret = self.settings.model_copy(
            update={
                "database_url": self.settings.database_url.replace("memkit@", "memkit:hunter2@")
            }
        )
        with self.assertRaises(NotImplementedError) as raised:
            operations.restore_backup(secret, artifact_id=created["id"], confirm="")
        self.assertNotIn("hunter2", str(raised.exception))

    def test_restoring_an_unknown_artifact_is_a_lookup_error(self) -> None:
        with self.assertRaises(LookupError):
            operations.restore_backup(self.settings, artifact_id="missing", confirm="RESTORE")


class DoctorTest(OperationsCase):
    def _report(self, **patches):
        qdrant = patches.pop("qdrant", None) or StubQdrant()
        self.enterContext(patch.object(operations.vectors, "get_client", lambda url: qdrant))
        self.enterContext(patch.object(operations.vectors, "ensure_collections", lambda c: None))
        self.enterContext(patch.object(operations, "get_embedder", StubEmbedder))
        report = operations.doctor(self.settings, **patches)
        return report, {item["name"]: item for item in report["checks"]}

    def test_every_dependency_is_named_exactly_once(self) -> None:
        """A check that quietly disappears turns doctor into false comfort."""
        _, checks = self._report()
        self.assertEqual(
            set(checks),
            {
                "configuration",
                "client_config",
                "database",
                "fulltext",
                "backups",
                "qdrant",
                "embedder",
                "provider",
                "index_parity",
                "worker",
                "users",
            },
        )

    def test_the_database_check_reports_the_schema_it_found(self) -> None:
        _, checks = self._report()
        self.assertTrue(checks["database"]["ok"], checks["database"])
        self.assertEqual(checks["database"]["detail"]["schema"], db.SCHEMA_VERSION)

    def test_the_fulltext_check_proves_cyrillic_stemming_is_available(self) -> None:
        """The lexical arm is a generated column over `to_tsvector('russian',
        …)`. On a server without that configuration, every search silently
        loses its lexical half."""
        _, checks = self._report()
        self.assertTrue(checks["fulltext"]["ok"], checks["fulltext"])
        self.assertIn("предпочита", checks["fulltext"]["detail"]["lexemes"])

    def test_the_users_check_wants_an_admin_and_a_team(self) -> None:
        _, checks = self._report()
        self.assertTrue(checks["users"]["ok"], checks["users"])
        self.assertEqual(checks["users"]["detail"]["admins"], 1)

    def test_an_instance_with_no_administrator_fails_the_users_check(self) -> None:
        """Nobody could create the next user, and nothing says so at startup."""
        with self.conn.transaction():
            self.conn.execute("UPDATE users SET role='member'")
        report, checks = self._report()
        self.assertFalse(checks["users"]["ok"])
        self.assertIn("admin", checks["users"]["detail"])
        self.assertFalse(report["ok"])

    def test_index_parity_fails_when_postgres_and_qdrant_disagree(self) -> None:
        self._memory()
        _, checks = self._report()
        self.assertFalse(checks["index_parity"]["ok"])
        self.assertIn("postgres=1", checks["index_parity"]["detail"])

    def test_index_parity_passes_once_the_outbox_has_drained(self) -> None:
        memory_id = self._memory()
        qdrant = StubQdrant()
        qdrant.points[memory_id] = {}
        with self.conn.transaction():
            self.conn.execute("UPDATE index_outbox SET status='done'")
        _, checks = self._report(qdrant=qdrant)
        self.assertTrue(checks["index_parity"]["ok"], checks["index_parity"])

    def test_the_backups_check_fails_until_one_has_been_verified(self) -> None:
        _, checks = self._report()
        self.assertFalse(checks["backups"]["ok"])
        operations.create_backup(self.settings, kind="daily")
        _, checks = self._report()
        self.assertTrue(checks["backups"]["ok"], checks["backups"])
        self.assertEqual(checks["backups"]["detail"]["count"], 1)

    def test_the_provider_check_fails_without_credentials(self) -> None:
        """The test settings are deliberately offline, so this is the state a
        misconfigured instance is in: everything else green, no extraction."""
        _, checks = self._report()
        self.assertFalse(checks["provider"]["ok"])
        self.assertIn("credentials", checks["provider"]["detail"])

    def test_the_report_carries_no_secret(self) -> None:
        """Doctor output is pasted into bug reports, so the DSN is redacted and
        the HMAC key never appears at all."""
        secret = self.settings.model_copy(
            update={
                "database_url": self.settings.database_url.replace("memkit@", "memkit:hunter2@")
            }
        )
        self.enterContext(patch.object(operations.vectors, "get_client", lambda url: StubQdrant()))
        self.enterContext(patch.object(operations.vectors, "ensure_collections", lambda c: None))
        self.enterContext(patch.object(operations, "get_embedder", StubEmbedder))
        rendered = json.dumps(operations.doctor(secret), default=str)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn(self.settings.telemetry_hmac_key, rendered)
        self.assertIn("memkit:***@", rendered)


class ReextractReportTest(OperationsCase):
    def test_windows_are_rounded_per_session_not_over_the_corpus(self) -> None:
        """Windows never cross a session boundary. Summing first and dividing
        later under-counts, and a job's call limit would then stop a valid
        replay midway through."""
        make_session(self.conn, self.team, session_id="s-1")
        make_session(self.conn, self.team, session_id="s-2")
        with self.conn.transaction():
            for session_id in ("s-1", "s-2"):
                for index in range(6):
                    store.add_message(
                        self.conn,
                        session_id=session_id,
                        user_id=self.team.alice_id,
                        scope_id=self.team.scope_of("alice"),
                        agent_id="chat",
                        role="user",
                        content=f"durable message {session_id} {index}",
                    )
        caller = self.team.principal("alice")
        report = reextract.dry_run_report(self.conn, scope_ids=caller.scopes())
        self.assertEqual(report["messages"], 12)
        self.assertEqual(report["sessions"], 2)
        self.assertEqual(report["windows"], 2)
        self.assertGreater(report["estimated_cost_usd"], 0)

    def test_the_report_writes_nothing(self) -> None:
        self._memory()
        caller = self.team.principal("alice")
        before = self.conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"]
        report = reextract.dry_run_report(self.conn, scope_ids=caller.scopes())
        self.assertEqual(report["memories"], 1)
        self.assertEqual(report["review_status"], {"confirmed": 1})
        self.assertEqual(
            self.conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"], before
        )

    def test_a_caller_with_no_scopes_is_quoted_nothing(self) -> None:
        self.assertEqual(reextract.dry_run_report(self.conn, scope_ids=[])["windows"], 0)

    def test_the_report_states_the_prompt_a_replay_would_use(self) -> None:
        """Without it the number is unattributable: a cost estimate for an
        unnamed prompt version cannot be compared with the next one."""
        from memkit import judge

        report = reextract.dry_run_report(
            self.conn, scope_ids=self.team.principal("alice").scopes()
        )
        self.assertEqual(report["active_prompt_version"], judge.PROMPT_VERSION)


class RetrievalTelemetryTest(OperationsCase):
    """Kept from the old program: the only privacy claim about search itself."""

    def _run(self, memory_id: str, query: str = "my unique raw query") -> str:
        digest = telemetry.hash_query(self.settings.telemetry_hmac_key, query)
        with self.conn.transaction():
            return telemetry.record_retrieval_run(
                self.conn,
                user_id=self.team.alice_id,
                query_hash=digest,
                policy_id="core-retrieval-neutral-v1",
                results=[
                    {"id": memory_id, "score": 0.8, "similarity": 0.7, "lexical": 1, "entity": 0}
                ],
                timings={"total_ms": 12.5},
                used_tokens=5,
            )

    def test_a_query_is_stored_only_as_an_hmac(self) -> None:
        """Search text is the most sensitive thing the system sees and the
        least useful to keep. Rotating the key retires old telemetry."""
        memory_id = self._memory()
        query = "my unique raw query"
        run_id = self._run(memory_id, query)
        row = self.conn.execute("SELECT * FROM retrieval_runs WHERE id=%s", (run_id,)).fetchone()
        self.assertEqual(
            row["query_hash"], telemetry.hash_query(self.settings.telemetry_hmac_key, query)
        )
        self.assertNotIn(query, json.dumps(dict(row), default=str))

    def test_hashing_without_a_configured_secret_refuses(self) -> None:
        with self.assertRaises(ValueError):
            telemetry.hash_query("", "anything")

    def test_feedback_must_name_a_result_the_run_returned(self) -> None:
        """Otherwise a label is an oracle: it would confirm the existence of a
        memory the caller never saw."""
        memory_id = self._memory()
        run_id = self._run(memory_id)
        with self.conn.transaction():
            telemetry.record_run_feedback(
                self.conn,
                retrieval_id=run_id,
                user_id=self.team.alice_id,
                memory_id=memory_id,
                useful=True,
                correct=True,
            )
        self.assertEqual(telemetry.metrics(self.conn)["feedback_labels"], 1)
        recent = telemetry.recent_runs(
            self.conn,
            user_id=self.team.alice_id,
            allowed_scope_ids=self.team.principal("alice").scopes(),
        )
        self.assertTrue(recent[0]["results"][0]["feedback"]["correct"])
        with self.assertRaises(ValueError), self.conn.transaction():
            telemetry.record_run_feedback(
                self.conn,
                retrieval_id=run_id,
                user_id=self.team.alice_id,
                memory_id="00000000-0000-0000-0000-000000000000",
                useful=True,
                correct=None,
            )

    def test_feedback_on_an_unknown_run_is_a_lookup_error(self) -> None:
        memory_id = self._memory()
        with self.assertRaises(LookupError), self.conn.transaction():
            telemetry.record_run_feedback(
                self.conn,
                retrieval_id="00000000-0000-0000-0000-000000000000",
                user_id=self.team.alice_id,
                memory_id=memory_id,
                useful=True,
                correct=None,
            )

    def test_runs_past_the_retention_window_are_pruned(self) -> None:
        run_id = self._run(self._memory())
        old = datetime.now(UTC) - timedelta(days=91)
        with self.conn.transaction():
            self.conn.execute("UPDATE retrieval_runs SET created_at=%s WHERE id=%s", (old, run_id))
        self.assertEqual(telemetry.prune(self.conn), 1)

    def test_metrics_narrow_to_one_user(self) -> None:
        self._run(self._memory())
        self.assertEqual(telemetry.metrics(self.conn, self.team.alice_id)["retrieval_runs"], 1)
        self.assertEqual(telemetry.metrics(self.conn, self.team.bob_id)["retrieval_runs"], 0)


if __name__ == "__main__":
    unittest.main()
