"""Live diagnostic of the shipped two-collection context assembly path.

Uses already-opened fictional scenarios; this is an integration diagnostic, not
another heldout study. Facts and actual user messages occupy their real separate
tables and Qdrant collections. All SQL runs in a throwaway PostgreSQL cluster.
"""

from __future__ import annotations

import argparse
import json
import secrets
import time
import warnings
from contextlib import closing
from functools import partial
from pathlib import Path

from qdrant_client import QdrantClient

from memkit import context_assembly, entities, outbox, retrieval, store, users, vectors
from memkit.config import get_settings
from memkit.embed import Embedder
from memkit.semantic import JevClient
from memkit.semantic_runtime import SemanticBlocks

from .context_cases import corpus
from .context_experiments import Recorded, metrics, pack, percentile, usage
from .reports import archive, code_identity, sha
from .semantic_hybrid import disposable_postgres


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "confirmation"], required=True)
    parser.add_argument("--budget", type=int, default=160)
    args = parser.parse_args()
    data, settings = corpus(), get_settings()
    items = [i for i in data["items"] if i["split"] == args.split]
    queries = [q for q in data["queries"] if q["split"] == args.split]
    provenance = code_identity()
    embedder = Embedder(
        settings.embed_model, settings.embed_device, settings.embed_revision, settings.embed_backend
    )
    records = []
    variants = ("facts_hybrid", "raw_hybrid", "raw_select", "raw_compact")
    cache = Path("data/jev/context-cache")
    cache.mkdir(parents=True, exist_ok=True)
    with (
        disposable_postgres() as conn,
        closing(QdrantClient(":memory:")) as index,
        JevClient(
            settings.jev_api_key, model=settings.jev_model, timeout=3, attempts=1
        ) as provider,
    ):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Payload indexes have no effect.*")
            vectors.ensure_collections(index)
        memory_ids, message_ids = {}, {}
        with conn.transaction():
            entities.ensure_team(conn, name="Fictional context diagnostic")
            user = users.create(
                conn,
                handle="fictional-context",
                display_name="Fictional speaker",
                password=secrets.token_urlsafe(32),
            )
            scope = str(entities.own_entity(conn, str(user["id"]))["id"])
            for item in items:
                if item["kind"] == "evidence":
                    mid, _, _ = store.add_message(
                        conn,
                        session_id=item["family"],
                        user_id=str(user["id"]),
                        scope_id=scope,
                        agent_id="fictional",
                        role="user",
                        content=item["text"],
                    )
                    message_ids[mid] = item["id"]
                else:
                    key = store.add_memory(
                        conn,
                        scope_id=scope,
                        author_id=str(user["id"]),
                        text=item["text"],
                        kind="fact",
                        source_role="user",
                    )
                    memory_ids[key] = item["id"]
        outbox.drain(conn, index, embedder, limit=200)
        for q in queries:
            started = time.perf_counter()
            baseline = retrieval.explain(
                conn,
                index,
                embedder,
                query=q["query"],
                scope_ids=[scope],
                limit=60,
                budget_tokens=120_000,
            )
            retrieval_ms = (time.perf_counter() - started) * 1000
            record = {"query": q, "variants": {}}
            for name in variants:
                client = Recorded(provider, cache)
                began = time.perf_counter()
                if name == "facts_hybrid":
                    facts, tokens = pack(baseline.chosen, args.budget)
                    ids = [memory_ids[r.id] for r in facts]
                    raw = []
                else:
                    blocks = SemanticBlocks(
                        client, context="compact" if name == "raw_compact" else "select"
                    )
                    result, raw = context_assembly.assemble(
                        conn,
                        index,
                        baseline,
                        query=q["query"],
                        scope_ids=[scope],
                        budget_tokens=args.budget,
                        limit=30,
                        select=(lambda _q, rows: rows)
                        if name == "raw_hybrid"
                        else partial(
                            blocks.select_context, budget_tokens=args.budget, max_results=30
                        ),
                    )
                    tokens = result.used_tokens
                    ids = [memory_ids[r.id] for r in result.chosen]
                    ids.extend(message_ids[r["message_id"]] for r in raw)
                record["variants"][name] = {
                    "ids": ids,
                    "tokens": tokens,
                    "raw": raw,
                    "wall_ms": retrieval_ms + (time.perf_counter() - began) * 1000,
                    "usage": usage(client.calls),
                    "calls": client.calls,
                }
            records.append(record)
            print(f"Runtime {len(records)}/{len(queries)}", flush=True)
    summary = {v: metrics(records, data, v) for v in variants}
    for name in variants:
        times = [r["variants"][name]["wall_ms"] for r in records]
        summary[name].update(
            wall_ms_p50=percentile(times, 0.5), wall_ms_p95=percentile(times, 0.95)
        )
    artifact = {
        "corpus_sha256": sha(data),
        "split": f"runtime-diagnostic-{args.split}",
        "provenance": provenance,
        "model": settings.jev_model,
        "thresholds": {
            "contribution": 0.7,
            "redundancy": 0.7,
            "budget": args.budget,
            "candidates": 60,
            "batch_size": 30,
            "deadline_seconds": 5,
        },
        "metrics": summary,
        "records": records,
    }
    folder = archive(
        artifact,
        root=Path("data/experiments"),
        name=f"context-runtime-{args.split}",
        hypothesis="The real facts-plus-user-passages path retains the offline context-selection gain.",
        decision="inconclusive",
        data_class="synthetic",
        label_source="author-labeled; not independently reviewed",
        limitations=[
            "Already opened synthetic scenarios; this is an integration diagnostic.",
            "Real separate memory/raw collections with local exact Qdrant; no server ANN/load claim.",
            "Reported wall time includes lookup and selection but excludes service startup.",
            "Cached judgments, if present, reduce observed wall time; cache hits are recorded.",
        ],
    )
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Archived: {folder}", flush=True)
    return int(any(m["errors"] for m in summary.values()))


if __name__ == "__main__":
    raise SystemExit(main())
