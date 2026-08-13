"""Deterministic candidate validation for replay promotion."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from . import evaluations, reindex, replay, retrieval, security, store, vectors
from .config import Settings
from .db import connect, transaction, utcnow
from .embed import Embedder


def _query_path() -> Path:
    packaged = resources.files("memkit").joinpath("release_queries.yaml")
    if packaged.is_file():
        return Path(str(packaged))
    return Path(__file__).resolve().parents[2] / "eval" / "queries.yaml"


def _link_evidence(
    conn: sqlite3.Connection, memory_id: str, evidence: list[dict[str, Any]]
) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO memory_sources(memory_id,message_id) VALUES (?,?)",
        [(memory_id, item["message_id"]) for item in evidence],
    )
    conn.executemany(
        """INSERT OR IGNORE INTO memory_evidence
           (memory_id,message_id,start_char,end_char,excerpt_sha256)
           VALUES (?,?,?,?,?)""",
        [
            (
                memory_id,
                item["message_id"],
                item["start_char"],
                item["end_char"],
                item["excerpt_sha256"],
            )
            for item in evidence
        ],
    )


def apply_manifest(
    conn: sqlite3.Connection, *, manifest: list[dict[str, Any]], owner_id: str
) -> dict[str, int]:
    counts = {"added": 0, "updated": 0, "deleted": 0, "rejected": 0}
    for item in manifest:
        if item["decision"] == "rejected":
            counts["rejected"] += 1
            continue
        data = item["reviewed"]
        if item["action"] == "ADD":
            memory_id = store.add_memory(
                conn,
                owner_id=owner_id,
                memory_id=str(data["id"]),
                text=str(data["text"]),
                kind=str(data["kind"]),
                context=dict(data["context"]),
                tags=list(data["tags"]),
                agent_id=data.get("agent_id"),
                importance=float(data["importance"]),
                confidence=float(data["confidence"]),
                valid_until=data.get("valid_until"),
                extraction_version=str(data["extraction_version"]),
                source_role=str(item["source_role"]),
            )
            _link_evidence(conn, memory_id, item["evidence"])
            counts["added"] += 1
        elif item["action"] == "UPDATE":
            memory_id = str(item["target_memory_id"])
            store.update_memory(
                conn,
                memory_id=memory_id,
                owner_id=owner_id,
                expected_revision=int(item["source_revision"]),
                text=str(data["text"]),
                kind=str(data["kind"]),
                context=dict(data["context"]),
                tags=list(data["tags"]),
                importance=float(data["importance"]),
                confidence=float(data["confidence"]),
                valid_until=data.get("valid_until"),
                extraction_version=str(data["extraction_version"]),
                source_role=str(item["source_role"]),
            )
            _link_evidence(conn, memory_id, item["evidence"])
            counts["updated"] += 1
        else:
            store.set_memory_status(
                conn,
                memory_id=str(item["target_memory_id"]),
                owner_id=owner_id,
                status="archived",
                expected_revision=int(item["source_revision"]),
            )
            counts["deleted"] += 1
    return counts


def _rank(patterns: list[str], texts: list[str]) -> int | None:
    expressions = [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    for rank, text in enumerate(texts, start=1):
        if any(expression.search(text) for expression in expressions):
            return rank
    return None


def _score(
    conn: sqlite3.Connection,
    client: Any,
    embedder: Embedder,
    *,
    owner_id: str,
    collection: str,
) -> dict[str, Any]:
    raw_cases = yaml.safe_load(_query_path().read_text(encoding="utf-8")) or []
    cases = [
        case for case in raw_cases if "memories" in case.get("answerable_by", ["raw", "memories"])
    ]
    hits = top1 = rejects = unsafe = 0
    reciprocal: list[float] = []
    for case in cases:
        context = case.get("context") or {}
        result = retrieval.explain(
            conn,
            client,
            embedder,
            query=str(case["query"]),
            owner_id=owner_id,
            expression={
                "all": [
                    {"field": f"context.{key}", "op": "eq", "value": value}
                    for key, value in context.items()
                ]
            }
            if context
            else None,
            limit=10,
            budget_tokens=20_000,
            memory_collection=collection,
        )
        texts = [item.text for item in result.chosen]
        patterns = [str(value) for value in case.get("expect_any", [])]
        rank = _rank(patterns, texts) if patterns else 1
        if rank is not None:
            hits += 1
            reciprocal.append(1.0 / rank)
            top1 += int(rank == 1)
        else:
            reciprocal.append(0.0)
        for pattern in case.get("expect_all", []):
            if _rank([str(pattern)], texts) is None:
                hits -= 1
        for pattern in case.get("reject", []):
            rejects += int(_rank([str(pattern)], texts) is not None)
        unsafe += sum(item.source_role not in retrieval.DEFAULT_TRUST for item in result.chosen)
        if context:
            unsafe += sum(
                any(item.context.get(key) != value for key, value in context.items())
                for item in result.chosen
            )
    total = len(cases) or 1
    return {
        "cases": len(cases),
        "recall": hits / total,
        "mrr": sum(reciprocal) / (len(reciprocal) or 1),
        "top1": top1,
        "rejects": rejects,
        "unsafe_results": unsafe,
    }


def _database_safety(conn: sqlite3.Connection) -> dict[str, Any]:
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]
    foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    active = int(conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0])
    fts = int(conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0])
    expired = int(
        conn.execute(
            """SELECT COUNT(*) FROM memories
                WHERE status='active' AND valid_until IS NOT NULL AND valid_until<=?""",
            (utcnow(),),
        ).fetchone()[0]
    )
    leaks = sum(
        security.redact(str(row[0])).redacted
        for row in conn.execute("SELECT text FROM memories WHERE status='active'")
    )
    evidence_errors = 0
    for row in conn.execute(
        """SELECT e.start_char,e.end_char,e.excerpt_sha256,m.content
             FROM memory_evidence e JOIN messages m ON m.id=e.message_id"""
    ):
        excerpt = str(row["content"])[int(row["start_char"]) : int(row["end_char"])]
        evidence_errors += int(
            hashlib.sha256(excerpt.encode()).hexdigest() != row["excerpt_sha256"]
        )
    return {
        "quick_check": quick,
        "foreign_key_errors": foreign_keys,
        "active_memories": active,
        "fts_memories": fts,
        "fts_parity": active == fts,
        "expired_active": expired,
        "credential_leaks": leaks,
        "invalid_citations": evidence_errors,
    }


def _benchmark_gate(settings: Settings) -> dict[str, Any] | None:
    directory = settings.export_dir / "release-artifacts"
    candidates = sorted(directory.glob("retrieval-100k-*.json"), reverse=True)
    if not candidates:
        return None
    artifact = json.loads(candidates[0].read_text(encoding="utf-8"))
    expected = artifact.pop("sha256", None)
    actual = hashlib.sha256(
        json.dumps(artifact, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if expected != actual:
        raise RuntimeError("100k benchmark artifact checksum mismatch")
    return {**artifact, "sha256": expected, "path": str(candidates[0])}


def validate_candidate(
    live: sqlite3.Connection,
    client: Any,
    embedder: Embedder,
    *,
    settings: Settings,
    batch_id: str,
) -> dict[str, Any]:
    local = replay.validate_batch(live, batch_id=batch_id, owner_id=settings.owner_id)
    manifest = replay.approved_manifest(live, batch_id)
    candidate_path = settings.export_dir / "candidates" / f"{batch_id}.db"
    replay.copy_database(settings.db_path, candidate_path)
    candidate = connect(candidate_path)
    generations: dict[str, Any] | None = None
    try:
        with transaction(candidate):
            applied = apply_manifest(candidate, manifest=manifest, owner_id=settings.owner_id)
        safety = _database_safety(candidate)
        generations = reindex.rebuild(candidate, client, embedder, activate=False)
        baseline = _score(
            live,
            client,
            embedder,
            owner_id=settings.owner_id,
            collection=vectors.MEMORIES,
        )
        proposed = _score(
            candidate,
            client,
            embedder,
            owner_id=settings.owner_id,
            collection=generations["generation"][vectors.MEMORIES],
        )
    finally:
        candidate.close()
        if generations is not None:
            vectors.drop_generations(client, generations["generation"])
    benchmark = _benchmark_gate(settings)
    quality_passed = (
        proposed["recall"] + 1e-12 >= baseline["recall"]
        and proposed["mrr"] + 1e-12 >= baseline["mrr"]
        and proposed["top1"] >= baseline["top1"]
        and proposed["rejects"] == 0
        and proposed["unsafe_results"] == 0
    )
    safety_passed = (
        safety["quick_check"] == "ok"
        and safety["foreign_key_errors"] == 0
        and safety["fts_parity"]
        and safety["expired_active"] == 0
        and safety["credential_leaks"] == 0
        and safety["invalid_citations"] == 0
    )
    latency_passed = bool(
        benchmark
        and benchmark.get("memories") == 100_000
        and float(benchmark.get("p95_ms", float("inf"))) < 200.0
    )
    result = {
        "manifest_checksum": local["checksum"],
        "candidate_path": str(candidate_path),
        "applied": applied,
        "safety": safety,
        "baseline": baseline,
        "proposed": proposed,
        "candidate_index": generations,
        "benchmark_100k": benchmark,
        "quality_passed": quality_passed,
        "safety_passed": safety_passed,
        "latency_passed": latency_passed,
        "passed": quality_passed and safety_passed and latency_passed,
        "validated_at": utcnow(),
    }
    batch = replay.get_batch(live, batch_id=batch_id, owner_id=settings.owner_id)
    stats = {**batch["stats"], "deterministic_gates": result}
    with transaction(live):
        live.execute(
            "UPDATE replay_batches SET stats_json=?,updated_at=? WHERE id=?",
            (json.dumps(stats, ensure_ascii=False, sort_keys=True), utcnow(), batch_id),
        )
    if not result["passed"]:
        raise RuntimeError("candidate failed one or more deterministic release gates")
    return result


def release_gate_status(
    conn: sqlite3.Connection,
    *,
    settings: Settings,
    batch_id: str,
    checksum: str,
) -> dict[str, Any]:
    batch = replay.get_batch(conn, batch_id=batch_id, owner_id=settings.owner_id)
    source = replay.validate_batch(
        conn,
        batch_id=batch_id,
        owner_id=settings.owner_id,
        update_status=False,
    )
    evaluation = evaluations.latest_release_gate(conn)
    period = utcnow()[:7]
    month_spend = float(
        conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs WHERE substr(created_at,1,7)=?",
            (period,),
        ).fetchone()[0]
    )
    month_reserved = float(
        conn.execute(
            """SELECT COALESCE(SUM(reserved_usd),0) FROM budget_reservations
                WHERE period=? AND status='active'""",
            (period,),
        ).fetchone()[0]
    )
    program_spend = float(
        conn.execute(
            """SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs
                WHERE kind LIKE 'improvement-%'"""
        ).fetchone()[0]
    )
    gates = batch["stats"].get("deterministic_gates") or {}
    checks = {
        "approved": batch["status"] == "approved",
        "approval_checksum": batch["approval_checksum"] == checksum == source["checksum"],
        "deterministic": bool(gates.get("passed")),
        "human_evaluation": bool(evaluation and evaluation["summary"].get("release_gate_passed")),
        "program_budget": program_spend <= settings.improvement_budget_usd + 1e-12,
        "monthly_budget": month_spend + month_reserved <= settings.monthly_cost_limit_usd + 1e-12,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "program_spend_usd": program_spend,
        "month_spend_usd": month_spend,
        "month_reserved_usd": month_reserved,
        "evaluation_id": evaluation["id"] if evaluation else None,
        "manifest_checksum": source["checksum"],
    }


def promote(
    conn: sqlite3.Connection,
    client: Any,
    embedder: Embedder,
    *,
    settings: Settings,
    batch_id: str,
    checksum: str,
    deadline: float | None = None,
) -> dict[str, Any]:
    def expired() -> bool:
        return deadline is not None and time.monotonic() >= deadline

    if expired():
        raise TimeoutError("promotion maintenance window expired")
    gate = release_gate_status(conn, settings=settings, batch_id=batch_id, checksum=checksum)
    if not gate["passed"]:
        failed = [name for name, passed in gate["checks"].items() if not passed]
        raise RuntimeError(f"promotion gates are incomplete: {', '.join(failed)}")
    manifest = replay.approved_manifest(conn, batch_id)
    with transaction(conn):
        conn.execute(
            "UPDATE replay_batches SET status='promoting',updated_at=? WHERE id=?",
            (utcnow(), batch_id),
        )
        applied = apply_manifest(conn, manifest=manifest, owner_id=settings.owner_id)
    generation = reindex.rebuild(conn, client, embedder, cancelled=expired)
    if expired():
        raise TimeoutError("promotion maintenance window expired")
    safety = _database_safety(conn)
    if (
        safety["quick_check"] != "ok"
        or safety["foreign_key_errors"]
        or not safety["fts_parity"]
        or safety["credential_leaks"]
        or safety["invalid_citations"]
        or generation["memories"] != safety["active_memories"]
    ):
        raise RuntimeError("post-promotion integrity or index parity check failed")
    # A no-result search is acceptable; an exception or unsafe result is not.
    smoke = retrieval.explain(
        conn,
        client,
        embedder,
        query="memkit readiness smoke test",
        owner_id=settings.owner_id,
        limit=3,
        budget_tokens=200,
    )
    if any(item.source_role not in retrieval.DEFAULT_TRUST for item in smoke.chosen):
        raise RuntimeError("Hermes retrieval smoke test returned untrusted memory")
    retired_generations = vectors.prune_retired_generations(client, retention_days=7)
    batch = replay.get_batch(conn, batch_id=batch_id, owner_id=settings.owner_id)
    stats = {
        **batch["stats"],
        "promotion": {
            "applied": applied,
            "generation": generation,
            "safety": safety,
            "smoke_results": len(smoke.chosen),
            "retired_generations_pruned": retired_generations,
            "promoted_at": utcnow(),
        },
    }
    with transaction(conn):
        conn.execute(
            """UPDATE replay_batches SET status='promoted',stats_json=?,updated_at=?
                 WHERE id=?""",
            (json.dumps(stats, ensure_ascii=False, sort_keys=True), utcnow(), batch_id),
        )
    return {"batch_id": batch_id, "status": "promoted", **stats["promotion"]}
