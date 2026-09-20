"""A queued job cannot outlive its actor's current permissions."""

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from memkit import config, consolidate, entities, job_runner, jobs, providers, store
from memkit.db import ConnectionPool, utcnow
from tests.fixtures import StubEmbedder, StubQdrant, seed_team
from tests.httpharness import test_settings as offline_settings


@pytest.fixture
def queued_system(database_url, clean_database, monkeypatch, tmp_path):
    conn = clean_database
    team = seed_team(conn)
    settings = offline_settings().model_copy(update={"export_dir": tmp_path / "exports"})
    monkeypatch.setattr(config, "_settings", settings)
    pool = ConnectionPool(database_url, max_size=3)
    app = SimpleNamespace(
        state=SimpleNamespace(
            db=pool,
            qdrant=StubQdrant(),
            embedder=StubEmbedder(),
            worker=Mock(),
        )
    )
    try:
        yield conn, team, app, settings
    finally:
        pool.close_all()


@pytest.mark.parametrize("revocation", ["membership", "disabled", "admin_role"])
def test_consolidation_rechecks_permissions_before_work(queued_system, revocation):
    conn, team, app, _ = queued_system
    actor = team.alice_id if revocation == "admin_role" else team.bob_id
    scope = team.scope_of("bob") if revocation == "admin_role" else team.project_id
    memory_id = store.add_memory(
        conn,
        scope_id=scope,
        author_id=team.bob_id,
        text="An expiring project fact",
        kind="fact",
        valid_until=utcnow() - timedelta(days=1),
    )
    job_id = jobs.create(
        conn,
        kind="consolidation",
        user_id=actor,
        input_data={"scope_ids": [scope], "dry_run": False, "merge": False},
    )
    if revocation == "membership":
        entities.remove_member(conn, entity_id=scope, user_id=actor)
    elif revocation == "disabled":
        conn.execute("UPDATE users SET disabled_at=now() WHERE id=%s", (actor,))
    else:
        conn.execute("UPDATE users SET role='member' WHERE id=%s", (actor,))
    job_runner.run(app, job_id)
    assert jobs.get(conn, job_id)["status"] == "failed"
    assert (
        conn.execute("SELECT status FROM memories WHERE id=%s", (memory_id,)).fetchone()["status"]
        == "active"
    )


def test_export_intersects_queued_scopes_with_current_access(queued_system):
    conn, team, app, _ = queued_system
    own_scope = team.scope_of("bob")
    own = store.add_memory(
        conn, scope_id=own_scope, author_id=team.bob_id, text="My private fact", kind="fact"
    )
    store.add_memory(
        conn,
        scope_id=team.project_id,
        author_id=team.bob_id,
        text="My former project contribution",
        kind="fact",
    )
    job_id = jobs.create(
        conn,
        kind="export",
        user_id=team.bob_id,
        input_data={
            "user_id": team.bob_id,
            "private_scope_id": own_scope,
            "authored_scopes": [own_scope, team.project_id],
        },
    )
    entities.remove_member(conn, entity_id=team.project_id, user_id=team.bob_id)
    job_runner.run(app, job_id)
    job = jobs.get(conn, job_id)
    assert job["status"] == "complete"
    payload = json.loads(Path(job["result"]["path"]).read_text())
    assert [row["id"] for row in payload["memories"]] == [own]


def test_disabled_actor_cannot_receive_a_queued_export(queued_system):
    conn, team, app, settings = queued_system
    job_id = jobs.create(
        conn,
        kind="export",
        user_id=team.bob_id,
        input_data={
            "user_id": team.bob_id,
            "private_scope_id": team.scope_of("bob"),
            "authored_scopes": [team.scope_of("bob")],
        },
    )
    conn.execute("UPDATE users SET disabled_at=now() WHERE id=%s", (team.bob_id,))
    job_runner.run(app, job_id)
    assert jobs.get(conn, job_id)["status"] == "failed"
    assert not list(settings.export_dir.glob("*.json"))


@pytest.mark.parametrize("revocation", ["before_provider", "after_provider"])
def test_consolidation_rechecks_each_merge_boundary(queued_system, revocation):
    conn, team, app, _ = queued_system
    app.state.qdrant = None
    for text in ("The project prefers pnpm", "pnpm is the project's package manager"):
        store.add_memory(
            conn,
            scope_id=team.project_id,
            author_id=team.bob_id,
            text=text,
            kind="fact",
            source_role="user",
        )
    job_id = jobs.create(
        conn,
        kind="consolidation",
        user_id=team.bob_id,
        input_data={"scope_ids": [team.project_id], "dry_run": False, "merge": True},
    )
    original = consolidate._apply_merges

    def revoke():
        entities.remove_member(conn, entity_id=team.project_id, user_id=team.bob_id)

    def merge_boundary(*args, **kwargs):
        if revocation == "before_provider":
            revoke()
        return original(*args, **kwargs)

    def provider(**_):
        revoke()
        return providers.ProviderResult(
            raw={"text": "The project uses pnpm"}, input_tokens=100, output_tokens=10
        )

    with (
        patch.object(consolidate, "_apply_merges", side_effect=merge_boundary),
        patch.object(providers, "call_merge", side_effect=provider) as call,
    ):
        job_runner.run(app, job_id)
    assert jobs.get(conn, job_id)["status"] == "failed"
    assert call.call_count == (1 if revocation == "after_provider" else 0)
    assert [r["status"] for r in conn.execute("SELECT status FROM memories")] == [
        "active",
        "active",
    ]
