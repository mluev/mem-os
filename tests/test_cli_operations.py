"""The operator command line, exercised against a real database.

Half of this CLI exists to repair an instance whose HTTP layer will not start,
so it talks to Postgres directly and cannot be tested through the API. The
other half -- `users create`, `api-keys create` -- is how an instance gets its
first credential at all: if either regressed, a fresh deployment would have no
way in and no error message saying so.

Everything expensive is stubbed (the embedder, Qdrant, `pg_dump`); everything
that decides who a command acts on is real, because that is the part that
changed when the service stopped having one owner.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import patch

from memkit import auth, cli, db, entities, users
from tests.fixtures import PASSWORD, StubEmbedder, StubQdrant, seed_team
from tests.httpharness import test_settings as _base_settings


def ns(**values) -> argparse.Namespace:
    return argparse.Namespace(**values)


class CliCase(unittest.TestCase):
    """One temp directory, one seeded team, and `get_settings` redirected."""

    def setUp(self) -> None:
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.settings = _base_settings().model_copy(
            update={"backup_dir": self.tmp / "backups", "export_dir": self.tmp / "exports"}
        )
        self.enterContext(patch.object(cli, "get_settings", lambda: self.settings))
        self.conn = db.connect(self.settings.database_url)
        db.truncate_all(self.conn)
        self.team = seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def run_cli(self, command, **arguments) -> tuple[int, str]:
        """Run one command, returning its exit code and everything it printed."""
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = command(ns(**arguments))
        return code, buffer.getvalue()

    def payload(self, command, **arguments):
        """The JSON document a command ends with.

        Several commands print a human summary first -- the importer's file
        counts, for instance -- so the machine-readable half is the trailing
        document, not the whole of stdout.
        """
        code, out = self.run_cli(command, **arguments)
        self.assertEqual(code, 0, out)
        start = min((index for index in (out.find("{"), out.find("[")) if index >= 0), default=-1)
        self.assertGreaterEqual(start, 0, out)
        return json.loads(out[start:])


class DiagnosticsTest(CliCase):
    def test_bench_passes_within_the_prefetch_budget(self) -> None:
        self.enterContext(
            patch.object(
                cli,
                "get_embedder",
                lambda: SimpleNamespace(benchmark=lambda: {"dim": 1024, "median_ms": 20}),
            )
        )
        code, out = self.run_cli(cli.cmd_bench)
        self.assertEqual(code, 0)
        self.assertIn("1024", out)

    def test_bench_fails_when_an_embedding_would_be_perceptible(self) -> None:
        """Session-start injection waits on this call, so the gate is latency,
        not correctness."""
        self.enterContext(
            patch.object(
                cli,
                "get_embedder",
                lambda: SimpleNamespace(benchmark=lambda: {"dim": 1024, "median_ms": 900}),
            )
        )
        self.assertEqual(self.run_cli(cli.cmd_bench)[0], 1)

    def test_doctor_prints_one_line_per_check(self) -> None:
        report = {
            "ok": True,
            "checks": [
                {"name": "database", "ok": True, "detail": {"schema": 1}},
                {"name": "qdrant", "ok": True, "detail": {"memories": 0}},
            ],
        }
        self.enterContext(patch.object(cli.operations, "doctor", lambda *a, **k: report))
        code, out = self.run_cli(cli.cmd_doctor, json=False, load_model=False)
        self.assertEqual(code, 0)
        self.assertIn("ok   database", out)
        self.assertIn("ok   qdrant", out)

    def test_doctor_exits_nonzero_when_a_dependency_is_down(self) -> None:
        report = {"ok": False, "checks": [{"name": "qdrant", "ok": False, "detail": "refused"}]}
        self.enterContext(patch.object(cli.operations, "doctor", lambda *a, **k: report))
        code, out = self.run_cli(cli.cmd_doctor, json=True, load_model=False)
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out)["ok"])


class PeopleTest(CliCase):
    def test_creating_a_user_gives_them_a_scope_to_write_into(self) -> None:
        created = self.payload(
            cli.cmd_users_create,
            handle="carol",
            name="Carol Nurmatova",
            email="carol@example.com",
            password=PASSWORD,
            admin=False,
        )
        self.assertEqual(created["role"], "member")
        own = entities.own_entity(self.conn, created["id"])
        self.assertIsNotNone(own)
        self.assertEqual(own["name"], "Carol Nurmatova")

    def test_a_duplicate_handle_is_refused_rather_than_shadowing(self) -> None:
        with self.assertRaises(Exception):
            self.run_cli(
                cli.cmd_users_create,
                handle="alice",
                name=None,
                email=None,
                password=PASSWORD,
                admin=False,
            )

    def test_users_list_reports_role_and_disabled_state(self) -> None:
        listed = {row["handle"]: row for row in self.payload(cli.cmd_users_list)}
        self.assertEqual(listed["alice"]["role"], "admin")
        self.assertFalse(listed["bob"]["disabled"])

    def test_the_last_administrator_cannot_be_disabled(self) -> None:
        """Otherwise a single command locks everyone out of their own instance."""
        with self.assertRaises(SystemExit):
            self.run_cli(cli.cmd_users_disable, handle="alice", enable=False)

    def test_disabling_and_re_enabling_a_member(self) -> None:
        self.assertTrue(self.payload(cli.cmd_users_disable, handle="bob", enable=False)["disabled"])
        self.assertIsNotNone(users.by_handle(self.conn, "bob")["disabled_at"])
        self.payload(cli.cmd_users_disable, handle="bob", enable=True)
        self.assertIsNone(users.by_handle(self.conn, "bob")["disabled_at"])

    def test_the_user_defaults_to_the_only_administrator(self) -> None:
        minted = self.payload(cli.cmd_keys_create, user=None, name="laptop")
        self.assertEqual(minted["user"], "alice")

    def test_a_second_administrator_makes_the_default_a_guess_and_it_refuses(self) -> None:
        # Written as SQL rather than through `users.update`, which cannot
        # currently change a role without also being told about `disabled`:
        # its `WHEN %s IS NULL` leaves Postgres no type to infer for the
        # untyped NULL, so `users.update(role=...)` raises before it updates.
        with self.conn.transaction():
            self.conn.execute("UPDATE users SET role='admin' WHERE id=%s", (self.team.bob_id,))
        with self.assertRaises(SystemExit):
            self.run_cli(cli.cmd_keys_create, user=None, name="laptop")

    def test_a_minted_key_authenticates_and_a_revoked_one_does_not(self) -> None:
        minted = self.payload(cli.cmd_keys_create, user="bob", name="agent")
        self.assertEqual(auth.resolve_api_key(self.conn, minted["key"]), self.team.bob_id)
        self.payload(cli.cmd_keys_revoke, key_id=minted["id"])
        self.assertIsNone(auth.resolve_api_key(self.conn, minted["key"]))

    def test_revoking_an_unknown_key_says_so(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli(cli.cmd_keys_revoke, key_id="00000000-0000-0000-0000-000000000000")


class EntitiesTest(CliCase):
    def test_creating_an_entity_registers_its_aliases(self) -> None:
        created = self.payload(
            cli.cmd_entities_create,
            name="Магазин",
            kind="project",
            slug=None,
            description="the shop",
            alias=["shop"],
            user="alice",
        )
        self.assertEqual(created["kind"], "project")
        for spelling in ("Магазин", "магазин", "shop"):
            resolved = entities.resolve_alias(self.conn, spelling)
            self.assertEqual(str(resolved["id"]), created["id"], spelling)

    def test_entities_list_shows_what_each_one_answers_to(self) -> None:
        listed = {row["slug"]: row for row in self.payload(cli.cmd_entities_list)}
        self.assertIn("memkit", listed["mem-os"]["aliases"])

    def test_membership_can_be_granted_and_taken_away(self) -> None:
        self.payload(
            cli.cmd_entities_member, slug="mem-os", user="bob", role="viewer", remove=False
        )
        roles = {
            row["handle"]: row["role"] for row in entities.members(self.conn, self.team.project_id)
        }
        self.assertEqual(roles["bob"], "viewer")
        self.payload(cli.cmd_entities_member, slug="mem-os", user="bob", role="member", remove=True)
        self.assertNotIn(
            "bob", {row["handle"] for row in entities.members(self.conn, self.team.project_id)}
        )

    def test_an_unknown_entity_is_named_in_the_error(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli(
                cli.cmd_entities_member, slug="nope", user="bob", role="member", remove=False
            )


class IngestTest(CliCase):
    def _turn(self, **changes):
        turn = {
            "project": "memkit",
            "git_branch": "main",
            "session_id": "s-import",
            "role": "user",
            "text": "Remember this durable fact",
            "created_at": "2026-08-12T00:00:00Z",
            "external_id": "turn-1",
        }
        turn.update(changes)
        return SimpleNamespace(**turn)

    def _stub_index(self) -> None:
        self.enterContext(patch.object(cli.vectors, "get_client", lambda url: StubQdrant()))
        self.enterContext(patch.object(cli, "get_embedder", StubEmbedder))
        self.enterContext(
            patch.object(cli.outbox, "drain", lambda *a, **k: SimpleNamespace(applied=1, failed=0))
        )

    def test_a_missing_transcript_directory_is_reported_not_created(self) -> None:
        code, _ = self.run_cli(
            cli.cmd_import, root=str(self.tmp / "missing"), limit=0, dry_run=False, user=None
        )
        self.assertEqual(code, 1)

    def test_a_dry_run_writes_nothing(self) -> None:
        root = self.tmp / "transcripts"
        root.mkdir()
        self.enterContext(patch.object(cli, "iter_turns", lambda root, stats: [self._turn()]))
        code, out = self.run_cli(cli.cmd_import, root=str(root), limit=0, dry_run=True, user=None)
        self.assertEqual(code, 0)
        self.assertIn("nothing written", out)
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM messages").fetchone()["n"], 0)

    def test_a_transcript_lands_in_the_project_its_workspace_names(self) -> None:
        """The repository a session ran in is the scope claim, when an entity
        answers to that name and the importer's user may write there."""
        root = self.tmp / "transcripts"
        root.mkdir()
        self.enterContext(patch.object(cli, "iter_turns", lambda root, stats: [self._turn()]))
        self._stub_index()
        report = self.payload(cli.cmd_import, root=str(root), limit=0, dry_run=False, user="alice")
        self.assertEqual(report["stored"], 1)
        # The scope lives on the session the turn opened, not on the row.
        row = self.conn.execute("SELECT * FROM sessions WHERE id='s-import'").fetchone()
        self.assertEqual(str(row["scope_id"]), self.team.project_id)

    def test_an_unknown_workspace_keeps_the_transcript_private(self) -> None:
        root = self.tmp / "transcripts"
        root.mkdir()
        self.enterContext(
            patch.object(cli, "iter_turns", lambda root, stats: [self._turn(project="unheard-of")])
        )
        self._stub_index()
        self.payload(cli.cmd_import, root=str(root), limit=0, dry_run=False, user="alice")
        row = self.conn.execute("SELECT * FROM sessions WHERE id='s-import'").fetchone()
        self.assertEqual(str(row["scope_id"]), self.team.scope_of("alice"))

    def test_importing_a_missing_legacy_database_fails_loudly(self) -> None:
        with self.assertRaises(SystemExit):
            self.run_cli(
                cli.cmd_import_sqlite,
                path=str(self.tmp / "nope.db"),
                user="alice",
                pending=False,
            )


class MaintenanceTest(CliCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = StubQdrant()
        self.enterContext(patch.object(cli, "_ready", lambda: (self.conn, self.client)))
        self.enterContext(patch.object(cli, "get_embedder", StubEmbedder))

    def test_drain_reports_what_it_delivered(self) -> None:
        self.enterContext(
            patch.object(cli.outbox, "drain", lambda *a, **k: SimpleNamespace(applied=2, failed=0))
        )
        self.assertEqual(
            self.payload(cli.cmd_drain, limit=10, retry_now=True), {"applied": 2, "failed": 0}
        )

    def test_drain_exits_nonzero_when_a_delivery_failed(self) -> None:
        self.enterContext(
            patch.object(cli.outbox, "drain", lambda *a, **k: SimpleNamespace(applied=0, failed=1))
        )
        self.assertEqual(self.run_cli(cli.cmd_drain, limit=10, retry_now=False)[0], 1)

    def test_reindex_reports_the_rebuilt_collections(self) -> None:
        self.enterContext(
            patch.object(cli.reindex, "rebuild", lambda *a, **k: {"memories": 0, "raw": 0})
        )
        self.assertEqual(self.payload(cli.cmd_reindex), {"memories": 0, "raw": 0})

    def test_consolidate_plans_over_every_scope(self) -> None:
        seen: dict[str, object] = {}

        def fake_run(conn, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(as_dict=lambda: {"archived": 0})

        self.enterContext(patch.object(cli.consolidate, "run", fake_run))
        self.payload(cli.cmd_consolidate, apply=False, merge=False)
        self.assertIn(self.team.project_id, seen["scope_ids"])
        self.assertTrue(seen["dry_run"])

    def test_reextract_report_costs_the_callers_scopes(self) -> None:
        seen: dict[str, object] = {}

        def fake_report(conn, **kwargs):
            seen.update(kwargs)
            return {"messages": 0, "estimated_windows": 0}

        self.enterContext(patch.object(cli.reextract, "dry_run_report", fake_report))
        self.payload(cli.cmd_reextract_report, user="alice")
        self.assertIn(self.team.scope_of("alice"), seen["scope_ids"])

    def test_export_writes_for_one_named_user(self) -> None:
        seen: dict[str, object] = {}

        def fake_export(conn, **kwargs):
            seen.update(kwargs)
            return {"path": str(self.tmp / "export.json")}

        self.enterContext(patch.object(cli.privacy, "export_user", fake_export))
        self.payload(cli.cmd_export, user="bob")
        self.assertEqual(seen["user_id"], self.team.bob_id)

    def test_erase_refuses_without_the_exact_confirmation(self) -> None:
        self.assertEqual(self.run_cli(cli.cmd_erase, user="bob", confirm="yes")[0], 1)

    def test_erase_runs_once_confirmed(self) -> None:
        self.enterContext(
            patch.object(cli.privacy, "erase_user", lambda *a, **k: {"memories_deleted": 0})
        )
        self.payload(cli.cmd_erase, user="bob", confirm="ERASE")


class BackupTest(CliCase):
    """Dispatch only. What a backup *is* is tested against pg_dump elsewhere."""

    def setUp(self) -> None:
        super().setUp()
        self.artifact = {"id": "b1", "path": str(self.tmp / "b.dump"), "sha256": "a", "bytes": 9}
        Path(self.artifact["path"]).write_bytes(b"archive")
        for name, value in (
            ("create_backup", self.artifact),
            ("prune_backups", {"removed": []}),
            ("verify_backup", {"verified": True}),
        ):
            self.enterContext(patch.object(cli.operations, name, lambda *a, _v=value, **k: _v))
        self.enterContext(
            patch.object(cli.operations, "list_backups", lambda settings: [self.artifact])
        )

    def test_create_list_verify_and_prune(self) -> None:
        self.payload(cli.cmd_backup, action="create", kind="daily", protected=False)
        self.assertEqual(self.payload(cli.cmd_backup, action="list"), [self.artifact])
        self.payload(cli.cmd_backup, action="verify", path=self.artifact["path"])
        self.payload(cli.cmd_backup, action="prune")

    def test_verifying_a_missing_archive_fails(self) -> None:
        def missing(path, **kwargs):
            raise FileNotFoundError(path)

        self.enterContext(patch.object(cli.operations, "verify_backup", missing))
        with self.assertRaises(SystemExit):
            self.run_cli(cli.cmd_backup, action="verify", path=str(self.tmp / "gone.dump"))

    def test_restore_prints_the_procedure_and_refuses_to_perform_it(self) -> None:
        """A `pg_restore --clean` from inside the service would drop the schema
        under its own pool. The command hands the operator the command instead.
        """

        def refuse(settings, **kwargs):
            raise NotImplementedError("restore is deliberately manual. ... pg_restore --clean ...")

        self.enterContext(patch.object(cli.operations, "restore_backup", refuse))
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = cli.cmd_backup(ns(action="restore", artifact_id="b1"))
        self.assertEqual(code, 1)
        self.assertIn("pg_restore --clean", buffer.getvalue())


class IntegrationsTest(CliCase):
    def test_installing_hermes_writes_a_private_config(self) -> None:
        source = self.tmp / "provider"
        source.mkdir()
        (source / "plugin.yaml").write_text("name: memkit\n")
        self.enterContext(patch.object(cli, "_hermes_source", lambda: source))
        home = self.tmp / "hermes"
        target = cli._install_hermes(hermes_home=str(home), force=False)
        self.assertTrue((target / "plugin.yaml").exists())
        with self.assertRaises(FileExistsError):
            cli._install_hermes(hermes_home=str(home), force=False)

        self.assertEqual(
            self.run_cli(cli.cmd_install_hermes, hermes_home=str(home), force=True)[0], 0
        )
        configured = cli.yaml.safe_load((home / "config.yaml").read_text())
        self.assertEqual(configured["memory"]["provider"], "memkit")
        plugin = configured["plugins"]["memkit"]
        self.assertEqual(plugin["base_url"], f"http://{self.settings.host}:{self.settings.port}")
        # The adapter talks HTTP now, so it must not be handed a database path.
        self.assertNotIn("db_path", plugin)
        self.assertFalse(plugin["send_tool_results"])
        self.assertEqual((home / "config.yaml").stat().st_mode & 0o777, 0o600)

    def test_a_missing_provider_is_reported_rather_than_half_installed(self) -> None:
        self.enterContext(patch.object(cli, "_hermes_source", lambda: self.tmp / "absent"))
        self.assertEqual(
            self.run_cli(cli.cmd_install_hermes, hermes_home=str(self.tmp / "h"), force=False)[0], 1
        )

    def test_installing_the_claude_code_surface_places_skill_and_hook(self) -> None:
        home = self.tmp / "claude"
        code, out = self.run_cli(
            cli.cmd_install_claude_code, claude_home=str(home), skills_home=None, force=False
        )
        self.assertEqual(code, 0, out)
        self.assertTrue((home / "skills" / "mem-os" / "SKILL.md").exists())
        self.assertTrue((home / "memkit" / "memkit_hooks.py").exists())
        # The printed snippet is the whole interface; a missing hook is silence.
        snippet = json.loads(out[out.index("{") : out.rindex("}") + 1])
        self.assertEqual(
            set(snippet["hooks"]), {"SessionStart", "PreCompact", "Stop", "SessionEnd"}
        )
        self.assertIn("api-keys create", out)

    def test_a_second_install_needs_force(self) -> None:
        home = self.tmp / "claude"
        self.run_cli(
            cli.cmd_install_claude_code, claude_home=str(home), skills_home=None, force=False
        )
        code, _ = self.run_cli(
            cli.cmd_install_claude_code, claude_home=str(home), skills_home=None, force=False
        )
        self.assertEqual(code, 1)


class EvalCommandTest(CliCase):
    def test_eval_delegates_to_the_repository_harness(self) -> None:
        """The harness ships with the checkout, not the wheel, so this only
        checks the wiring: `--compare` and `--target` reach different calls."""
        import eval.run as harness

        self.enterContext(
            patch.object(harness, "run_eval", lambda **kw: {"target": kw.get("target")})
        )
        self.enterContext(patch.object(harness, "run_compare", lambda **kw: {"compared": True}))
        self.assertEqual(
            self.payload(cli.cmd_eval, target="raw", compare=False, limit=5), {"target": "raw"}
        )
        self.assertEqual(
            self.payload(cli.cmd_eval, target="memories", compare=True, limit=None),
            {"compared": True},
        )


class ParserTest(unittest.TestCase):
    """Every command group still parses, and the retired ones are gone."""

    LIVE: ClassVar[list[list[str]]] = [
        ["serve"],
        ["bench"],
        ["doctor", "--json"],
        ["users", "create", "carol", "--admin"],
        ["users", "list"],
        ["users", "disable", "carol"],
        ["api-keys", "create", "--user", "carol"],
        ["api-keys", "revoke", "key-1"],
        ["entities", "create", "Shop", "--alias", "shop"],
        ["entities", "list"],
        ["entities", "member", "shop", "--user", "carol", "--role", "viewer"],
        ["import-claude-code", "--dry-run"],
        ["import-sqlite", "old.db", "--pending"],
        ["drain-index", "--retry-now"],
        ["reindex"],
        ["consolidate", "--apply", "--merge"],
        ["reextract-report"],
        ["export"],
        ["erase", "--confirm", "ERASE"],
        ["backup", "create", "--protected"],
        ["backup", "list"],
        ["backup", "verify", "/tmp/x.dump"],
        ["backup", "prune"],
        ["backup", "restore", "b1"],
        ["install-hermes", "--force"],
        ["install-claude-code", "--force"],
        ["eval", "--compare"],
    ]

    RETIRED: ClassVar[list[list[str]]] = [
        ["service", "status"],
        ["setup"],
        ["replay-report"],
        ["policy-sweep"],
        ["benchmark-retrieval"],
    ]

    def _parse(self, argv: list[str]) -> int:
        calls: list[argparse.Namespace] = []
        original = argparse.ArgumentParser.parse_args

        def capture(parser, *args, **kwargs):
            parsed = original(parser, *args, **kwargs)
            calls.append(parsed)
            parsed.func = lambda _args: 0
            return parsed

        with (
            patch.object(sys, "argv", ["memkit", *argv]),
            patch.object(argparse.ArgumentParser, "parse_args", capture),
        ):
            result = cli.main()
        self.assertTrue(calls, argv)
        return result

    def test_every_live_command_parses(self) -> None:
        for argv in self.LIVE:
            with self.subTest(command=argv):
                self.assertEqual(self._parse(argv), 0)

    def test_retired_commands_are_gone(self) -> None:
        """Each of these managed a launchd service, a Docker container, or the
        improvement program, none of which exist on a container deployment."""
        for argv in self.RETIRED:
            with (
                self.subTest(command=argv),
                self.assertRaises(SystemExit),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self._parse(argv)

    def test_serve_is_dispatched(self) -> None:
        with (
            patch.object(cli, "cmd_serve", lambda args: 0),
            patch.object(sys, "argv", ["memkit", "serve"]),
        ):
            self.assertEqual(cli.main(), 0)


if __name__ == "__main__":
    unittest.main()
