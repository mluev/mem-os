from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from memkit import (
    benchmark,
    evaluations,
    jobs,
    operations,
    policy_sweep,
    reextract,
    release,
    replay,
    retrieval,
    store,
    telemetry,
    vectors,
    worker,
)
from memkit.config import Settings
from memkit.db import connect, ensure_owner, ensure_session, init_db, transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant


@pytest.fixture
def program(tmp_path: Path):
    path = tmp_path / "memkit.db"
    settings = Settings(
        api_key="x" * 48,
        telemetry_hmac_key="h" * 48,
        db_path=path,
        backup_dir=tmp_path / "backups",
        export_dir=tmp_path / "exports",
        owner_id=OWNER,
        owner_name="Test",
        embed_device="cpu",
    )
    init_db(path)
    conn = connect(path)
    ensure_owner(conn, OWNER, "Test")
    ensure_session(conn, "s-1", OWNER, "chat")
    conn.commit()
    yield settings, conn
    conn.close()


def add_evidenced_memory(conn: sqlite3.Connection, text: str = "Prefers careful migrations") -> str:
    content = f"Please remember: {text}"
    message_id, _, _ = store.add_message(
        conn,
        session_id="s-1",
        owner_id=OWNER,
        agent_id="chat",
        role="user",
        content=content,
    )
    memory_id = store.add_memory(
        conn,
        owner_id=OWNER,
        text=text,
        kind="preference",
        source_role="user",
    )
    start = content.index(text)
    excerpt = content[start : start + len(text)]
    conn.execute(
        "INSERT INTO memory_sources(memory_id,message_id) VALUES (?,?)",
        (memory_id, message_id),
    )
    conn.execute(
        """INSERT INTO memory_evidence
           (memory_id,message_id,start_char,end_char,excerpt_sha256) VALUES (?,?,?,?,?)""",
        (
            memory_id,
            message_id,
            start,
            start + len(text),
            hashlib.sha256(excerpt.encode()).hexdigest(),
        ),
    )
    conn.commit()
    return memory_id


def test_retrieval_telemetry_never_stores_query_and_feedback_is_scoped(program) -> None:
    settings, conn = program
    memory_id = add_evidenced_memory(conn)
    query = "my unique raw query"
    digest = telemetry.hash_query(settings.telemetry_hmac_key, query)
    with transaction(conn):
        run_id = telemetry.record_retrieval_run(
            conn,
            owner_id=OWNER,
            query_hash=digest,
            policy_id="neutral-v1",
            results=[{"id": memory_id, "score": 0.8, "similarity": 0.7, "lexical": 1, "entity": 0}],
            timings={"total_ms": 12.5},
            used_tokens=5,
        )
        telemetry.record_run_feedback(
            conn,
            retrieval_id=run_id,
            owner_id=OWNER,
            memory_id=memory_id,
            useful=True,
            correct=True,
        )
    row = conn.execute("SELECT * FROM retrieval_runs WHERE id=?", (run_id,)).fetchone()
    assert row["query_hash"] == digest
    assert query not in json.dumps(dict(row))
    assert telemetry.metrics(conn)["feedback_labels"] == 1
    recent = telemetry.recent_runs(conn, owner_id=OWNER)
    assert recent[0]["results"][0]["feedback"]["correct"] == 1
    with pytest.raises(ValueError):
        telemetry.record_run_feedback(
            conn,
            retrieval_id=run_id,
            owner_id=OWNER,
            memory_id="not-returned",
            useful=True,
            correct=None,
        )
    with pytest.raises(LookupError):
        telemetry.record_run_feedback(
            conn,
            retrieval_id="missing",
            owner_id=OWNER,
            memory_id=memory_id,
            useful=True,
            correct=None,
        )
    old = (datetime.now(UTC) - timedelta(days=91)).isoformat().replace("+00:00", "Z")
    conn.execute("UPDATE retrieval_runs SET created_at=? WHERE id=?", (old, run_id))
    conn.commit()
    assert telemetry.prune(conn) == 1


def test_exact_identifier_candidates_use_bounded_fts(program) -> None:
    _, conn = program
    memory_id = store.add_memory(
        conn,
        owner_id=OWNER,
        text="Synthetic incident ticket-042771 is resolved",
        kind="fact",
        source_role="user",
    )
    conn.commit()
    assert retrieval._entity_candidates(conn, query="ticket-042771", owner_id=OWNER, limit=10) == {
        memory_id: 1.0
    }


def test_verified_backup_retention_and_restore_rollback(program, monkeypatch) -> None:
    settings, conn = program
    add_evidenced_memory(conn)
    daily = operations.create_backup(settings, kind="daily")
    weekly = operations.create_backup(settings, kind="weekly")
    protected = operations.create_backup(settings, kind="pre-promotion", protected=True)
    assert (
        operations.verify_backup(Path(daily["path"]), expected_sha256=daily["sha256"])[
            "schema_version"
        ]
        == 6
    )
    assert len(operations.list_backups(settings)) == 3
    removed = operations.prune_backups(settings, keep_daily=0, keep_weekly=0)["removed"]
    assert daily["path"] in removed and weekly["path"] in removed
    assert Path(protected["path"]).exists()

    # Restore failure atomically puts the emergency copy back.
    before_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    monkeypatch.setattr(operations.vectors, "ensure_collections", lambda client: None)
    monkeypatch.setattr(operations.vectors, "get_client", lambda url: StubQdrant())
    monkeypatch.setattr(operations, "get_embedder", lambda: StubEmbedder())
    monkeypatch.setattr(
        operations.reindex,
        "rebuild",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        operations.restore_backup(settings, artifact_id=protected["id"], confirm="RESTORE")
    restored = connect(settings.db_path)
    assert restored.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == before_count
    assert restored.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    restored.close()
    with pytest.raises(ValueError):
        operations.restore_backup(settings, artifact_id=protected["id"], confirm="no")
    with pytest.raises(LookupError):
        operations.restore_backup(settings, artifact_id="missing", confirm="RESTORE")


def test_doctor_reports_each_dependency_without_leaking_secrets(program, monkeypatch) -> None:
    settings, conn = program
    add_evidenced_memory(conn)
    operations.create_backup(settings, kind="daily")
    hermes_home = settings.db_path.parent / "hermes"
    (hermes_home / "plugins" / "memkit").mkdir(parents=True)
    key_file = hermes_home / "api-key"
    key_file.write_text(settings.api_key)
    key_file.chmod(0o600)
    (hermes_home / "config.yaml").write_text(
        "memory:\n  provider: memkit\nplugins:\n  memkit:\n"
        f"    api_key_file: {key_file}\n    base_url: http://127.0.0.1:8077\n"
    )
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    qdrant = StubQdrant()
    qdrant.points.update(
        {row["id"]: {} for row in conn.execute("SELECT id FROM memories WHERE status='active'")}
    )
    conn.execute("UPDATE index_outbox SET status='done'")
    conn.commit()
    monkeypatch.setattr(operations.vectors, "get_client", lambda url: qdrant)
    monkeypatch.setattr(operations.vectors, "ensure_collections", lambda client: None)
    monkeypatch.setattr(operations, "get_embedder", lambda: StubEmbedder())
    monkeypatch.setattr(operations, "_authenticated_http_check", lambda base_url, key: 200)
    result = operations.doctor(settings, load_model=True)
    checks = {item["name"]: item for item in result["checks"]}
    assert checks["database"]["ok"] and checks["fts5"]["ok"]
    assert checks["backups"]["ok"] and checks["index_parity"]["ok"]
    assert checks["hermes"]["ok"] and checks["hermes"]["detail"]["authenticated"]
    assert settings.api_key not in json.dumps(result)


def test_review_manifest_requires_every_decision_and_preserves_immutables(program) -> None:
    settings, conn = program
    memory_id = add_evidenced_memory(conn)
    source_checksum = replay._source_checksum(conn, owner_id=OWNER)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    batch_id = "batch-1"
    conn.execute(
        """INSERT INTO replay_batches
           (id,owner_id,status,model,prompt_version,source_checksum,stats_json,created_at,updated_at)
           VALUES (?,?,'review','gemini-3.5-flash-lite','v7',?,'{}',?,?)""",
        (batch_id, OWNER, source_checksum, now, now),
    )
    row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    before = (
        release._memory_for_test(row)
        if hasattr(release, "_memory_for_test")
        else replay._memory(row)
    )
    proposed = {
        **before,
        "text": "Prefers carefully reviewed migrations",
        "extraction_version": "v7",
    }
    evidence = replay._evidence(conn, memory_id)
    conn.execute(
        """INSERT INTO replay_items
           (id,batch_id,sequence,action,target_memory_id,source_revision,before_json,
            proposed_json,evidence_json,source_role,created_at)
           VALUES ('item-1',?,0,'UPDATE',?,?,?,?,?,'user',?)""",
        (
            batch_id,
            memory_id,
            before["revision"],
            json.dumps(before),
            json.dumps(proposed),
            json.dumps(evidence),
            now,
        ),
    )
    conn.commit()
    with pytest.raises(RuntimeError, match="pending"):
        replay.validate_batch(conn, batch_id=batch_id, owner_id=OWNER)
    with pytest.raises(ValueError, match="immutable"):
        replay.review_item(
            conn,
            batch_id=batch_id,
            item_id="item-1",
            decision="edited",
            edits={"source_role": "assistant"},
        )
    reviewed = replay.review_item(
        conn,
        batch_id=batch_id,
        item_id="item-1",
        decision="edited",
        edits={"text": "Prefers reviewed migrations"},
    )
    assert reviewed["reviewed"]["text"] == "Prefers reviewed migrations"
    validated = replay.validate_batch(conn, batch_id=batch_id, owner_id=OWNER)
    assert len(validated["checksum"]) == 64
    exported = replay.export_batch(
        conn, batch_id=batch_id, owner_id=OWNER, output_dir=settings.export_dir
    )
    artifact = json.loads(Path(exported["path"]).read_text())
    assert artifact["sha256"] == exported["sha256"]
    with pytest.raises(RuntimeError, match="deterministic"):
        replay.approve_batch(
            conn, batch_id=batch_id, owner_id=OWNER, checksum=validated["checksum"]
        )


def test_blinded_human_evaluation_release_threshold(program) -> None:
    _, conn = program
    cases = [
        {
            "case_key": f"case-{index:02d}",
            "prompt": f"Prompt {index}",
            "arms": {
                "no_memory": "none",
                "current_memory": "current",
                "reviewed_v7": "v7",
                "oracle_memory": "oracle",
            },
        }
        for index in range(32)
    ]
    run = evaluations.create(conn, model="gpt-5.6-sol", cases=cases)
    assert evaluations.get_run(conn, run["id"])["total_cases"] == 32
    for index, case in enumerate(evaluations.list_cases(conn, evaluation_id=run["id"])):
        mapping_row = conn.execute(
            "SELECT order_json FROM evaluation_cases WHERE id=?", (case["id"],)
        ).fetchone()
        mapping = json.loads(mapping_row["order_json"])
        labels = {arm: label for label, arm in mapping.items()}
        if index < 7:
            ranking = [
                labels["reviewed_v7"],
                labels["current_memory"],
                labels["oracle_memory"],
                labels["no_memory"],
            ]
        else:
            ranking = [
                labels["current_memory"],
                labels["reviewed_v7"],
                labels["oracle_memory"],
                labels["no_memory"],
            ]
        # Non-wins are intentionally ties by equal rank semantics unavailable;
        # put both orders equal would be invalid, so use current wins only once.
        if index >= 7:
            ranking = [
                labels["oracle_memory"],
                labels["current_memory"],
                labels["reviewed_v7"],
                labels["no_memory"],
            ]
        evaluations.review_case(
            conn,
            evaluation_id=run["id"],
            case_id=case["id"],
            ranking=ranking,
            harmful=[],
            notes="human review",
            current_vs_v7="v7_win" if index < 7 else "tie",
        )
    result = evaluations.finalize(conn, evaluation_id=run["id"])
    assert result["reviewed_v7_wins"] == 7
    assert result["reviewed_v7_losses"] == 0
    assert result["release_gate_passed"]
    assert evaluations.list_cases(conn, evaluation_id=run["id"])[0]["mapping"]


def test_small_scale_benchmark_emits_checksummed_artifact(program, monkeypatch) -> None:
    settings, _ = program
    qdrant = StubQdrant()
    monkeypatch.setattr(benchmark.vectors, "get_client", lambda url: qdrant)
    monkeypatch.setattr(benchmark, "get_embedder", lambda: StubEmbedder())
    result = benchmark.run_100k(settings, memories=25, query_count=5)
    artifact = json.loads(Path(result["path"]).read_text())
    assert artifact["memories"] == 25
    assert artifact["exact_identifier_recall"] == 1.0
    body = {key: value for key, value in artifact.items() if key != "sha256"}
    assert (
        artifact["sha256"]
        == hashlib.sha256(
            json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest()
    )


def test_replay_estimate_rounds_windows_per_session(program) -> None:
    settings, conn = program
    ensure_session(conn, "s-2", OWNER, "chat")
    for session_id in ("s-1", "s-2"):
        for index in range(6):
            store.add_message(
                conn,
                session_id=session_id,
                owner_id=OWNER,
                agent_id="chat",
                role="user",
                content=f"durable message {session_id} {index}",
            )
    conn.commit()
    report = reextract.dry_run_report(
        conn,
        owner_id=OWNER,
        model=settings.judge_model,
        output_dir=settings.export_dir,
    )
    assert report["messages"] == 12
    assert report["estimated_windows"] == 2


def test_shadow_replay_runs_only_on_copy_and_builds_net_diff(program, monkeypatch) -> None:
    settings, conn = program
    source_memory = add_evidenced_memory(conn)
    created = replay.create_batch(conn, settings=settings)
    jobs.claim(conn, created["job_id"])

    def fake_apply(shadow, **kwargs):
        source = shadow.execute(
            """SELECT e.message_id,e.start_char,e.end_char,e.excerpt_sha256
                 FROM memory_evidence e WHERE e.memory_id=?""",
            (source_memory,),
        ).fetchone()
        new_id = store.add_memory(
            shadow,
            owner_id=OWNER,
            text="Uses protected replay batches",
            kind="preference",
            source_role="user",
            extraction_version="v7",
        )
        shadow.execute(
            "INSERT INTO memory_sources(memory_id,message_id) VALUES (?,?)",
            (new_id, source["message_id"]),
        )
        shadow.execute(
            """INSERT INTO memory_evidence
               (memory_id,message_id,start_char,end_char,excerpt_sha256) VALUES (?,?,?,?,?)""",
            (
                new_id,
                source["message_id"],
                source["start_char"],
                source["end_char"],
                source["excerpt_sha256"],
            ),
        )
        shadow.execute(
            """INSERT INTO judge_runs
               (owner_id,job_id,kind,model,prompt_version,input_json,cost_usd,created_at)
               VALUES (?,?,'replay','gemini-3.5-flash-lite','v7','{}',0.01,?)""",
            (OWNER, kwargs["job_id"], datetime.now(UTC).isoformat().replace("+00:00", "Z")),
        )
        shadow.execute("UPDATE jobs SET calls_completed=1 WHERE id=?", (kwargs["job_id"],))
        shadow.commit()
        return {
            "windows": 1,
            "added": 1,
            "updated": 0,
            "deleted": 0,
            "rejected": 0,
            "cancelled": False,
            "prompt_version": "v7",
        }

    monkeypatch.setattr(replay.reextract, "apply_replay", fake_apply)
    result = replay.run_shadow_replay(
        conn,
        settings=settings,
        batch_id=created["batch_id"],
        job_id=created["job_id"],
        cancelled=lambda: False,
    )
    assert result["adds"] == 1 and result["cost_usd"] == pytest.approx(0.01)
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 1
    assert (
        replay.get_batch(conn, batch_id=created["batch_id"], owner_id=OWNER)["status"] == "review"
    )

    # A worker crash after committing the batch but before completing the outer job
    # must not rerun the provider or duplicate its spend record.
    rerun = replay.run_shadow_replay(
        conn,
        settings=settings,
        batch_id=created["batch_id"],
        job_id=created["job_id"],
        cancelled=lambda: False,
    )
    assert rerun["cost_usd"] == pytest.approx(0.01)
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM judge_runs WHERE kind='improvement-shadow-replay'"
        ).fetchone()[0]
        == 1
    )


def _review_batch_with_update(settings: Settings, conn: sqlite3.Connection) -> tuple[str, str]:
    memory_id = add_evidenced_memory(conn)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    batch_id = "release-batch"
    before = replay._memory(
        conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
    )
    evidence = replay._evidence(conn, memory_id)
    conn.execute(
        """INSERT INTO replay_batches
           (id,owner_id,status,model,prompt_version,source_checksum,stats_json,created_at,updated_at)
           VALUES (?,?,'review','gemini-3.5-flash-lite','v7',?,'{}',?,?)""",
        (batch_id, OWNER, replay._source_checksum(conn, owner_id=OWNER), now, now),
    )
    conn.execute(
        """INSERT INTO replay_items
           (id,batch_id,sequence,action,target_memory_id,source_revision,before_json,
            proposed_json,evidence_json,source_role,decision,reviewed_json,reviewed_at,created_at)
           VALUES ('release-item',?,0,'UPDATE',?,?,?,?,?,'user','accepted',?,?,?)""",
        (
            batch_id,
            memory_id,
            before["revision"],
            json.dumps(before),
            json.dumps(before),
            json.dumps(evidence),
            json.dumps(before),
            now,
            now,
        ),
    )
    conn.commit()
    return batch_id, memory_id


def test_candidate_validation_gate_and_promotion(program, monkeypatch) -> None:
    settings, conn = program
    batch_id, memory_id = _review_batch_with_update(settings, conn)
    artifact_body = {"kind": "retrieval-100k", "memories": 100_000, "p95_ms": 120.0}
    artifact = {
        "sha256": hashlib.sha256(
            json.dumps(artifact_body, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        **artifact_body,
    }
    artifact_dir = settings.export_dir / "release-artifacts"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "retrieval-100k-test.json").write_text(json.dumps(artifact))
    qdrant = StubQdrant()
    qdrant.points[memory_id] = {}
    gates = release.validate_candidate(
        conn,
        qdrant,
        StubEmbedder(),
        settings=settings,
        batch_id=batch_id,
    )
    assert gates["passed"] and gates["safety"]["invalid_citations"] == 0
    approval = replay.approve_batch(
        conn, batch_id=batch_id, owner_id=OWNER, checksum=gates["manifest_checksum"]
    )

    # Insert a completed human gate without invoking any model judge.
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    conn.execute(
        """INSERT INTO evaluation_runs
           (id,status,model,rubric_json,summary_json,created_at,updated_at)
           VALUES ('human-gate','complete','gpt-5.6-sol','{}',?, ?, ?)""",
        (json.dumps({"release_gate_passed": True}), now, now),
    )
    conn.commit()
    status = release.release_gate_status(
        conn, settings=settings, batch_id=batch_id, checksum=approval["checksum"]
    )
    assert status["passed"]
    monkeypatch.setattr(
        release.reindex,
        "rebuild",
        lambda *args, **kwargs: {
            "memories": 1,
            "raw": 1,
            "generation": {},
            "activated": True,
        },
    )
    result = release.promote(
        conn,
        qdrant,
        StubEmbedder(),
        settings=settings,
        batch_id=batch_id,
        checksum=approval["checksum"],
    )
    assert result["status"] == "promoted"
    assert conn.execute("SELECT revision FROM memories WHERE id=?", (memory_id,)).fetchone()[0] == 2


def test_generated_services_qdrant_setup_and_worker_recovery(
    program, monkeypatch, tmp_path
) -> None:
    settings, conn = program
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "appdata"
    agents = tmp_path / "LaunchAgents"
    monkeypatch.setattr(operations, "DEFAULT_CONFIG_DIR", config_dir)
    monkeypatch.setattr(operations, "DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr(operations, "service_plist_path", lambda: agents / "service.plist")
    monkeypatch.setattr(operations, "backup_service_plist_path", lambda: agents / "backup.plist")
    monkeypatch.setattr(operations.sys, "platform", "darwin")
    service = operations.install_service(settings)
    backup = operations.install_backup_service()
    assert service.exists() and backup.exists()
    assert b"ThrottleInterval" in service.read_bytes()
    assert b"WorkingDirectory" in service.read_bytes()
    completed = SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(operations, "_run", lambda *args, **kwargs: completed)
    monkeypatch.setattr(operations.time, "sleep", lambda seconds: None)
    for action in ("install", "start", "stop", "restart", "status", "uninstall"):
        assert operations.service_action(action, settings)["ok"]
    with pytest.raises(ValueError):
        operations.service_action("invalid", settings)

    monkeypatch.setattr(operations, "ensure_qdrant", lambda settings: {"ready": True})
    monkeypatch.setattr(operations, "get_embedder", lambda: StubEmbedder())
    monkeypatch.setattr(operations, "create_backup", lambda *args, **kwargs: {"id": "backup"})
    monkeypatch.setattr(operations, "service_action", lambda *args, **kwargs: {"ok": True})
    monkeypatch.setattr(operations, "doctor", lambda *args, **kwargs: {"ok": True})
    result = operations.setup(settings, install_hermes=lambda force, settings: tmp_path / "hermes")
    assert Path(result["key_file"]).stat().st_mode & 0o777 == 0o600
    assert result["doctor"]["ok"]

    states: list[bool] = []
    calls = {"n": 0}

    def ensure(client):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("offline")

    monkeypatch.setattr(worker.vectors, "ensure_collections", ensure)
    monkeypatch.setattr(worker.outbox, "drain", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(worker.jobs, "recover_stale", lambda conn: {})
    durable = worker.Worker(
        lambda: conn,
        StubQdrant(),
        StubEmbedder(),
        lambda job_id, kind: None,
        poll_seconds=0.01,
        dependency_status=lambda ready, error: states.append(ready),
    )
    durable.start()
    assert durable._wake.wait(0.03) is False
    durable.stop()
    assert False in states and True in states


def test_job_failure_limits_heartbeat_and_leases(program) -> None:
    _, conn = program
    with pytest.raises(KeyError):
        jobs.get(conn, "missing")
    job_id = jobs.create(conn, kind="test", call_limit=1)
    jobs.claim(conn, job_id, holder="holder", lease_seconds=1)
    with pytest.raises(RuntimeError):
        jobs.claim(conn, job_id)
    assert jobs.renew(conn, job_id, holder="holder")
    assert not jobs.renew(conn, job_id, holder="other")
    with jobs.heartbeat(conn, job_id, holder="holder", interval_seconds=0.01):
        assert jobs.consume_call(conn, job_id) == 1
    with pytest.raises(jobs.CallLimitExceeded):
        jobs.consume_call(conn, job_id)
    jobs.request_cancel(conn, job_id)
    assert jobs.cancel_requested(conn, job_id)
    jobs.finish(conn, job_id, status="cancelled")
    with pytest.raises(RuntimeError):
        jobs.request_cancel(conn, job_id)
    with pytest.raises(ValueError):
        jobs.finish(conn, job_id, status="invalid")
    with pytest.raises(jobs.CallLimitExceeded):
        jobs.consume_call(conn, job_id)

    with pytest.raises(ValueError):
        jobs.reserve_budget(conn, period="2026-08", amount_usd=-1, limit_usd=1)
    with pytest.raises(jobs.BudgetExceeded):
        jobs.reserve_budget(conn, period="2026-08", amount_usd=2, limit_usd=1)
    with pytest.raises(RuntimeError):
        jobs.reconcile_budget(conn, "missing", actual_usd=0)
    with pytest.raises(RuntimeError):
        jobs.release_budget(conn, "missing")
    assert jobs.acquire_lease(conn, name="promotion", holder="one", ttl_seconds=60)
    assert not jobs.acquire_lease(conn, name="promotion", holder="two", ttl_seconds=60)
    assert jobs.acquire_lease(conn, name="promotion", holder="one", ttl_seconds=60)
    jobs.release_lease(conn, name="promotion", holder="one")


def test_qdrant_pin_validation_and_launch_paths(program, monkeypatch, tmp_path) -> None:
    settings, _ = program
    monkeypatch.setattr(operations.shutil, "which", lambda name: "/usr/local/bin/docker")
    monkeypatch.setattr(operations, "DEFAULT_DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(operations.vectors, "get_client", lambda url: StubQdrant())
    monkeypatch.setattr(operations.vectors, "ensure_collections", lambda client: None)

    def existing(command, check=True):
        if command[1] == "inspect":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"Config": {"Image": "qdrant/qdrant:v1.18.2"}}]),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(operations, "_run", existing)
    assert operations.ensure_qdrant(settings, wait_seconds=1)["ready"]

    def missing_container(command, check=True):
        code = 1 if command[1] == "inspect" else 0
        return SimpleNamespace(returncode=code, stdout="", stderr="")

    monkeypatch.setattr(operations, "_run", missing_container)
    assert operations.ensure_qdrant(settings, wait_seconds=1)["ready"]

    def wrong_image(command, check=True):
        if command[1] == "inspect":
            return SimpleNamespace(
                returncode=0,
                stdout=json.dumps([{"Config": {"Image": "qdrant/qdrant:latest"}}]),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(operations, "_run", wrong_image)
    with pytest.raises(RuntimeError, match="expected pinned"):
        operations.ensure_qdrant(settings, wait_seconds=1)
    monkeypatch.setattr(operations.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Docker is required"):
        operations.ensure_qdrant(settings, wait_seconds=1)

    monkeypatch.setattr(operations.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="macOS only"):
        operations.install_service(settings)
    with pytest.raises(RuntimeError, match="macOS only"):
        operations.install_backup_service()
    with pytest.raises(RuntimeError, match="manual startup"):
        operations.service_action("status", settings)


def test_qdrant_generations_are_retained_for_seven_days() -> None:
    client = StubQdrant()
    now_ns = 2_000_000_000_000_000_000
    old = f"memories__g{now_ns - 8 * 86_400 * 1_000_000_000}"
    recent = f"raw__g{now_ns - 6 * 86_400 * 1_000_000_000}"
    client._store[old] = {"old": {}}
    client._store[recent] = {"recent": {}}
    removed = vectors.prune_retired_generations(client, retention_days=7, now_ns=now_ns)
    assert removed == [old]
    assert client._store[old] == {}
    assert client._store[recent] == {"recent": {}}


def test_offline_policy_sweep_requires_labels_and_manual_activation(program) -> None:
    settings, conn = program
    relevant = store.add_memory(
        conn, owner_id=OWNER, text="Relevant", kind="fact", source_role="user"
    )
    wrong = store.add_memory(conn, owner_id=OWNER, text="Wrong", kind="fact", source_role="user")
    conn.commit()
    with pytest.raises(RuntimeError, match="50 labels"):
        policy_sweep.sweep(conn, owner_id=OWNER, output_dir=settings.export_dir)
    for _ in range(25):
        with transaction(conn):
            run_id = telemetry.record_retrieval_run(
                conn,
                owner_id=OWNER,
                query_hash="hash",
                policy_id="neutral-v1",
                results=[
                    {"id": wrong, "score": 0.2, "similarity": 0.2, "lexical": 0, "entity": 0},
                    {"id": relevant, "score": 0.1, "similarity": 0, "lexical": 0, "entity": 1},
                ],
                timings={"total_ms": 10},
                used_tokens=2,
            )
            telemetry.record_run_feedback(
                conn,
                retrieval_id=run_id,
                owner_id=OWNER,
                memory_id=wrong,
                useful=False,
                correct=False,
            )
            telemetry.record_run_feedback(
                conn,
                retrieval_id=run_id,
                owner_id=OWNER,
                memory_id=relevant,
                useful=True,
                correct=True,
            )
    result = policy_sweep.sweep(conn, owner_id=OWNER, output_dir=settings.export_dir)
    assert result["passed"] and result["validation_improvement"] >= 0.05
    with pytest.raises(ValueError):
        policy_sweep.activate(
            conn,
            artifact_path=Path(result["path"]),
            checksum=result["sha256"],
            confirm="no",
        )
    activated = policy_sweep.activate(
        conn,
        artifact_path=Path(result["path"]),
        checksum=result["sha256"],
        confirm="ACTIVATE",
    )
    assert activated["manual"] and activated["id"].startswith("learned-")
