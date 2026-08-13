from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from memkit import cli
from memkit.config import Settings
from memkit.db import connect, ensure_owner, init_db
from tests.fixtures import OWNER, StubEmbedder, StubQdrant


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    value = Settings(
        api_key="x" * 48,
        db_path=tmp_path / "memkit.db",
        backup_dir=tmp_path / "backups",
        export_dir=tmp_path / "exports",
        owner_id=OWNER,
        embed_device="cpu",
    )
    init_db(value.db_path)
    conn = connect(value.db_path)
    ensure_owner(conn, OWNER, "Test")
    conn.commit()
    conn.close()
    return value


def ns(**values):
    return argparse.Namespace(**values)


def test_simple_cli_commands(settings, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(
        cli,
        "get_embedder",
        lambda: SimpleNamespace(benchmark=lambda: {"dim": 1024, "median_ms": 20}),
    )
    assert cli.cmd_bench(ns()) == 0
    assert "1024" in capsys.readouterr().out

    assert cli.cmd_import(ns(root=str(tmp_path / "missing"), limit=0, dry_run=False)) == 1
    root = tmp_path / "transcripts"
    root.mkdir()
    monkeypatch.setattr(cli, "iter_turns", lambda root, stats: [])
    assert cli.cmd_import(ns(root=str(root), limit=0, dry_run=True)) == 0

    result = SimpleNamespace(applied=2, failed=0)
    monkeypatch.setattr(cli, "_ready", lambda: (connect(settings.db_path), StubQdrant()))
    monkeypatch.setattr(cli.outbox, "drain", lambda *args, **kwargs: result)
    monkeypatch.setattr(cli.outbox, "pending_count", lambda conn: 0)
    assert cli.cmd_drain(ns(limit=10, retry_now=True)) == 0

    monkeypatch.setattr(cli.reindex, "rebuild", lambda *args: {"memories": 0})
    assert cli.cmd_reindex(ns()) == 0
    monkeypatch.setattr(
        cli.consolidate,
        "run",
        lambda *args, **kwargs: SimpleNamespace(as_dict=lambda: {"archived": 0}),
    )
    assert cli.cmd_consolidate(ns(apply=False)) == 0

    export = tmp_path / "export.json"
    export.write_text("{}")
    monkeypatch.setattr(cli.privacy, "export_owner", lambda *args, **kwargs: export)
    assert cli.cmd_export(ns()) == 0
    assert cli.cmd_erase(ns(confirm="wrong")) == 2
    monkeypatch.setattr(cli.privacy, "erase_owner", lambda *args, **kwargs: {"erased": True})
    assert cli.cmd_erase(ns(confirm="ERASE")) == 0


def test_import_write_replay_and_hermes_install(settings, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    root = tmp_path / "transcripts"
    root.mkdir()
    turn = SimpleNamespace(
        project="project",
        git_branch="main",
        session_id="s-import",
        role="user",
        text="Remember this durable fact",
        created_at="2026-08-12T00:00:00Z",
        external_id="turn-1",
    )
    monkeypatch.setattr(cli, "iter_turns", lambda root, stats: [turn])
    monkeypatch.setattr(cli.vectors, "get_client", lambda url: StubQdrant())
    monkeypatch.setattr(cli, "get_embedder", lambda: StubEmbedder())
    monkeypatch.setattr(
        cli.outbox, "drain", lambda *args, **kwargs: SimpleNamespace(applied=1, failed=0)
    )
    assert cli.cmd_import(ns(root=str(root), limit=0, dry_run=False)) == 0

    monkeypatch.setattr(
        cli.reextract,
        "dry_run_report",
        lambda *args, **kwargs: {"apply_allowed": False, "report_path": "report.json"},
    )
    assert cli.cmd_replay_report(ns(output=str(tmp_path / "reports"))) == 0

    source = tmp_path / "provider"
    source.mkdir()
    (source / "plugin.yaml").write_text("name: memkit\n")
    monkeypatch.setattr(cli, "_hermes_source", lambda: source)
    home = tmp_path / "hermes"
    target = cli._install_hermes(hermes_home=str(home), force=False)
    assert (target / "plugin.yaml").exists()
    with pytest.raises(FileExistsError):
        cli._install_hermes(hermes_home=str(home), force=False)
    assert cli.cmd_install_hermes(ns(hermes_home=str(home), force=True)) == 0
    configured = cli.yaml.safe_load((home / "config.yaml").read_text())
    assert configured["memory"]["provider"] == "memkit"
    assert configured["plugins"]["memkit"]["db_path"] == str(settings.db_path.resolve())
    assert (home / "config.yaml").stat().st_mode & 0o777 == 0o600


def test_operational_cli_dispatch(settings, monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    report = {"ok": True, "checks": [{"name": "database", "ok": True, "detail": "ok"}]}
    monkeypatch.setattr(cli.operations, "doctor", lambda *args, **kwargs: report)
    assert cli.cmd_doctor(ns(json=False, load_model=False)) == 0
    assert cli.cmd_doctor(ns(json=True, load_model=False)) == 0
    monkeypatch.setattr(
        cli.operations, "service_action", lambda *args, **kwargs: {"ok": True, "action": "status"}
    )
    assert cli.cmd_service(ns(action="status")) == 0

    artifact = {
        "id": "b1",
        "path": str(tmp_path / "b.db"),
        "sha256": "a",
        "kind": "daily",
    }
    Path(artifact["path"]).write_bytes(b"backup")
    monkeypatch.setattr(cli.operations, "create_backup", lambda *args, **kwargs: artifact)
    monkeypatch.setattr(cli.operations, "prune_backups", lambda *args, **kwargs: {"removed": []})
    monkeypatch.setattr(cli.operations, "list_backups", lambda settings: [artifact])
    monkeypatch.setattr(cli.operations, "verify_backup", lambda *args, **kwargs: {"verified": True})
    monkeypatch.setattr(
        cli.operations, "restore_backup", lambda *args, **kwargs: {"restored": True}
    )
    assert cli.cmd_backup(ns(backup_action="create", kind="daily", protected=False)) == 0
    assert cli.cmd_backup(ns(backup_action="list")) == 0
    assert cli.cmd_backup(ns(backup_action="verify", id="b1")) == 0
    assert cli.cmd_backup(ns(backup_action="verify", id="missing")) == 1
    assert cli.cmd_backup(ns(backup_action="prune")) == 0
    assert cli.cmd_backup(ns(backup_action="restore", id="b1", confirm="RESTORE")) == 0

    monkeypatch.setattr(cli.operations, "setup", lambda *args, **kwargs: {"doctor": {"ok": True}})
    assert cli.cmd_setup(ns()) == 0
    monkeypatch.setattr(cli.benchmark, "run_100k", lambda *args, **kwargs: {"passed": True})
    assert cli.cmd_benchmark_retrieval(ns(memories=10, queries=5)) == 0
    assert capsys.readouterr().out


def test_main_builds_every_command_group(monkeypatch) -> None:
    monkeypatch.setattr(cli, "cmd_serve", lambda args: 0)
    monkeypatch.setattr(sys, "argv", ["memkit", "serve"])
    assert cli.main() == 0
