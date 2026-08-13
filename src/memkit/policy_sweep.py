"""Offline retrieval-policy sweep over privacy-safe labelled result scores."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from itertools import product
from pathlib import Path
from typing import Any

from . import retrieval, telemetry
from .db import transaction, utcnow


def _mrr(runs: list[dict[str, Any]], weights: tuple[float, float, float]) -> tuple[float, int]:
    reciprocal: list[float] = []
    unsafe_top1 = 0
    for run in runs:
        ranked = sorted(
            run["results"],
            key=lambda item: (
                -(
                    weights[0] * float(item.get("similarity", 0))
                    + weights[1] * float(item.get("lexical", 0))
                    + weights[2] * float(item.get("entity", 0))
                )
            ),
        )
        rank = next(
            (
                index
                for index, item in enumerate(ranked, start=1)
                if item["feedback"]
                and item["feedback"].get("useful") == 1
                and item["feedback"].get("correct") != 0
            ),
            None,
        )
        reciprocal.append(1.0 / rank if rank else 0.0)
        if ranked and ranked[0]["feedback"] and ranked[0]["feedback"].get("correct") == 0:
            unsafe_top1 += 1
    return sum(reciprocal) / (len(reciprocal) or 1), unsafe_top1


def sweep(conn: sqlite3.Connection, *, owner_id: str, output_dir: Path) -> dict[str, Any]:
    runs = telemetry.recent_runs(conn, owner_id=owner_id, limit=10_000)
    labelled = [run for run in runs if any(item["feedback"] for item in run["results"])]
    labels = sum(sum(item["feedback"] is not None for item in run["results"]) for run in labelled)
    if labels < 50 or len(labelled) < 20:
        raise RuntimeError("policy sweep requires at least 50 labels across 20 retrieval runs")
    training = [
        run for run in labelled if int(hashlib.sha256(run["id"].encode()).hexdigest(), 16) % 5
    ]
    validation = [run for run in labelled if run not in training]
    if len(validation) < 4:
        validation = labelled[-max(4, len(labelled) // 5) :]
        training = labelled[: -len(validation)]
    baseline_weights = (0.60, 0.30, 0.10)
    baseline_mrr, baseline_unsafe = _mrr(validation, baseline_weights)
    candidates = []
    for dense, lexical in product((0.4, 0.5, 0.6, 0.7), (0.2, 0.3, 0.4, 0.5)):
        entity = round(1.0 - dense - lexical, 2)
        if entity < 0 or entity > 0.2:
            continue
        train_mrr, _ = _mrr(training, (dense, lexical, entity))
        validation_mrr, unsafe = _mrr(validation, (dense, lexical, entity))
        candidates.append(
            {
                "dense_weight": dense,
                "lexical_weight": lexical,
                "entity_weight": entity,
                "train_mrr": train_mrr,
                "validation_mrr": validation_mrr,
                "unsafe_top1": unsafe,
            }
        )
    best = max(candidates, key=lambda item: (item["validation_mrr"], item["train_mrr"]))
    latency = telemetry.metrics(conn)["search_latency_ms"]["p95"]
    improvement = float(best["validation_mrr"]) - baseline_mrr
    passed = (
        improvement >= 0.05
        and best["unsafe_top1"] <= baseline_unsafe
        and latency is not None
        and latency < 200
    )
    payload = {
        "kind": "offline-policy-sweep",
        "labels": labels,
        "runs": len(labelled),
        "training_runs": len(training),
        "validation_runs": len(validation),
        "baseline_validation_mrr": baseline_mrr,
        "baseline_unsafe_top1": baseline_unsafe,
        "candidate": best,
        "validation_improvement": improvement,
        "search_p95_ms": latency,
        "passed": passed,
        "created_at": utcnow(),
    }
    checksum = hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    artifact = {"sha256": checksum, **payload}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"policy-sweep-{checksum}.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return {**artifact, "path": str(path)}


def activate(
    conn: sqlite3.Connection,
    *,
    artifact_path: Path,
    checksum: str,
    confirm: str,
) -> dict[str, Any]:
    if confirm != "ACTIVATE":
        raise ValueError('policy activation requires confirm="ACTIVATE"')
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    expected = artifact.pop("sha256", None)
    actual = hashlib.sha256(
        json.dumps(artifact, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    if expected != checksum or actual != checksum:
        raise RuntimeError("policy sweep checksum mismatch")
    if not artifact.get("passed"):
        raise RuntimeError("policy sweep did not pass activation gates")
    base = retrieval.load_policy(conn, "neutral-v1")
    candidate = artifact["candidate"]
    config = {
        "dense_weight": candidate["dense_weight"],
        "lexical_weight": candidate["lexical_weight"],
        "entity_weight": candidate["entity_weight"],
        "importance_weight": base.importance_weight,
        "recency_weight": base.recency_weight,
        "min_relevance": base.min_relevance,
        "allowed_source_roles": sorted(base.allowed_source_roles),
        "default_half_life_days": base.default_half_life_days,
        "activation_artifact": checksum,
    }
    policy_id = f"learned-{checksum[:12]}"
    with transaction(conn):
        conn.execute(
            """INSERT INTO policies
               (id,namespace_id,kind,name,version,config_json,created_at)
               VALUES (?,NULL,'retrieval',?,1,?,?)""",
            (policy_id, policy_id, json.dumps(config, sort_keys=True), utcnow()),
        )
    return {"id": policy_id, "activated": True, "manual": True, "checksum": checksum}
