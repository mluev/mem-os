"""Protected, opt-in retrieval scale benchmark."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import retrieval, vectors
from .config import Settings
from .db import connect, ensure_owner, init_db, utcnow
from .embed import get_embedder


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def run_100k(
    settings: Settings, *, memories: int = 100_000, query_count: int = 50
) -> dict[str, Any]:
    if memories < 1 or query_count < 5:
        raise ValueError("benchmark requires memories >= 1 and query_count >= 5")
    client = vectors.get_client(settings.qdrant_url)
    embedder = get_embedder()
    collection = f"{vectors.MEMORIES}__gbenchmark{time.time_ns()}"
    with tempfile.TemporaryDirectory(prefix="memkit-100k-") as directory:
        path = Path(directory) / "benchmark.db"
        init_db(path)
        conn = connect(path)
        ensure_owner(conn, settings.owner_id, "benchmark")
        now = utcnow()
        ids = [
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"memkit-benchmark-{index}"))
            for index in range(memories)
        ]
        rows = [
            (
                memory_id,
                settings.owner_id,
                "benchmark",
                "fact",
                f"Synthetic benchmark record ticket-{index:06d}",
                0.5,
                0.9,
                "active",
                now,
                now,
                now,
                "benchmark-v1",
                "manual",
            )
            for index, memory_id in enumerate(ids)
        ]
        conn.executemany(
            """INSERT INTO memories
               (id,owner_id,agent_id,kind,text,importance,confidence,status,
                valid_from,created_at,updated_at,extraction_version,source_role)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        conn.commit()
        vectors.create_empty_collection(client, collection)
        vector = embedder.encode_one("synthetic benchmark record")
        try:
            for offset in range(0, memories, 256):
                chunk = rows[offset : offset + 256]
                vectors.upsert(
                    client,
                    collection,
                    [
                        (
                            row[0],
                            vector,
                            {
                                "owner_id": settings.owner_id,
                                "agent_id": "benchmark",
                                "kind": "fact",
                                "text": row[4],
                                "importance": 0.5,
                                "confidence": 0.9,
                                "status": "active",
                                "source_role": "manual",
                                "context": {},
                                "tags": [],
                                "valid_until": None,
                                "created_at": now,
                                "updated_at": now,
                                "revision": 1,
                                "redacted": False,
                            },
                        )
                        for row in chunk
                    ],
                )
            if len(vectors.exact_ids(client, collection)) != memories:
                raise RuntimeError("benchmark collection failed exact-ID validation")
            sample_numbers = [
                int(i * (memories - 1) / (query_count - 1)) for i in range(query_count)
            ]
            # Production setup warms the embedder and long-lived Qdrant process.
            # Exercise the complete path before sampling so one-time graph,
            # tokenizer, SQLite page-cache, and HNSW initialization are excluded.
            for number in sample_numbers[:5]:
                retrieval.explain(
                    conn,
                    client,
                    embedder,
                    query=f"ticket-{number:06d}",
                    owner_id=settings.owner_id,
                    limit=10,
                    budget_tokens=1000,
                    memory_collection=collection,
                )
            latencies = []
            component_timings: dict[str, list[float]] = {}
            exact_hits = 0
            for number in sample_numbers:
                result = retrieval.explain(
                    conn,
                    client,
                    embedder,
                    query=f"ticket-{number:06d}",
                    owner_id=settings.owner_id,
                    limit=10,
                    budget_tokens=1000,
                    memory_collection=collection,
                )
                latencies.append(float(result.timings["total_ms"]))
                for name, value in result.timings.items():
                    component_timings.setdefault(name, []).append(float(value))
                exact_hits += int(any(f"ticket-{number:06d}" in row.text for row in result.chosen))
        finally:
            vectors.drop_collection(client, collection)
            conn.close()
    payload = {
        "kind": "retrieval-100k",
        "memories": memories,
        "queries": query_count,
        "p50_ms": round(_percentile(latencies, 0.50), 1),
        "p95_ms": round(_percentile(latencies, 0.95), 1),
        "p99_ms": round(_percentile(latencies, 0.99), 1),
        "component_p95_ms": {
            name: round(_percentile(values, 0.95), 1)
            for name, values in sorted(component_timings.items())
        },
        "exact_identifier_recall": exact_hits / query_count,
        "passed": _percentile(latencies, 0.95) < 200 and exact_hits == query_count,
        "embed_model": settings.embed_model,
        "embed_revision": settings.embed_revision,
        "qdrant_version": settings.qdrant_version,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    checksum = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    artifact = {"sha256": checksum, **payload}
    output_dir = settings.export_dir / "release-artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    output = output_dir / f"retrieval-100k-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(output)
    return {**artifact, "path": str(output)}
