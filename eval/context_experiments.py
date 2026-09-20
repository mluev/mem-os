"""Paired live experiments for detail retention, relevance and context packing.

Only the bundled fictional corpus is accepted. PostgreSQL is disposable, and
Qdrant uses the local exact engine. Source passages are indexed as separate
experimental rows: this measures representation/selection, not a deployed raw
message endpoint. No production database or private transcript is opened.
"""

from __future__ import annotations

import argparse
import json
import math
import secrets
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path

from qdrant_client import QdrantClient

from memkit import entities, outbox, retrieval, store, users, vectors
from memkit.config import get_settings
from memkit.context_selection import CONTRIBUTION, COVERAGE, REDUNDANCY, VERSION, ContextSelector
from memkit.embed import Embedder
from memkit.semantic import Answer, JevClient, JevReranker, Judgment, SemanticError
from memkit.semantic_questions import question

from .context_cases import corpus
from .reports import archive, code_identity, sha
from .semantic_hybrid import disposable_postgres

PRICE_PER_MILLION_INPUT = 0.042  # docs.typesafe.ai/models, verified 2026-09-20.
VARIANTS = (
    "facts_hybrid",
    "facts_jev",
    "wide_facts_jev",
    "evidence_hybrid",
    "evidence_jev",
    "evidence_batches",
    "evidence_compact",
)


class Recorded:
    """Exact fictional requests and answers; cache identity includes model and question."""

    def __init__(self, provider, folder):
        self.provider, self.folder = provider, folder
        self.calls = []

    def close(self):
        pass

    def ask(self, state, questions, *, version):
        request = {
            "state": state,
            "questions": questions,
            "version": version,
            "model": self.provider.model,
        }
        path = self.folder / f"{sha(request)}.json"
        cached = path.exists()
        if cached:
            data = json.loads(path.read_text())
            payload = data["result"]
            result = Judgment(
                **(payload | {"answers": {k: Answer(**v) for k, v in payload["answers"].items()}})
            )
        else:
            try:
                result = self.provider.ask(state, questions, version=version)
            except SemanticError as exc:
                self.calls.append({"request": request, "error": str(exc), "cached": False})
                raise
            data = {"request": request, "result": asdict(result)}
            # Different query workers have different requests. Atomic replacement
            # also makes interruption safe if an identical request is repeated.
            temp = path.with_suffix(f".{threading.get_ident()}.tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            temp.replace(path)
        self.calls.append(data | {"cached": cached})
        return result


def pack(rows, budget):
    """Identical budget and wrapper allowance for every experimental representation."""
    chosen, used = [], 0
    for row in rows:
        cost = retrieval._token_count(row.text) + 6
        if used + cost <= budget:
            chosen.append(row)
            used += cost
    return chosen, used


def prepare(data, split):
    settings = get_settings()
    items = [i for i in data["items"] if i["split"] == split]
    queries = [q for q in data["queries"] if q["split"] == split]
    embedder = Embedder(
        settings.embed_model, settings.embed_device, settings.embed_revision, settings.embed_backend
    )
    snapshots = []
    with disposable_postgres() as conn, closing(QdrantClient(":memory:")) as index:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Payload indexes have no effect.*")
            vectors.ensure_collections(index)
        with conn.transaction():
            entities.ensure_team(conn, name="Fictional context evaluation")
            user = users.create(
                conn,
                handle="fictional-context",
                display_name="Fictional speaker",
                password=secrets.token_urlsafe(32),
            )
            scope = str(entities.own_entity(conn, str(user["id"]))["id"])
            mapping = {}
            for item in items:
                key = store.add_memory(
                    conn,
                    scope_id=scope,
                    author_id=str(user["id"]),
                    text=item["text"],
                    kind=item["kind"],
                    source_role="user",
                )
                mapping[key] = item["id"]
        outbox.drain(conn, index, embedder, limit=200)
        for q in queries:
            pools = {}
            for name, kinds, floor, count in [
                ("facts", ["memory", "distractor"], 0.18, 30),
                ("wide_facts", ["memory", "distractor"], 0, 60),
                ("evidence", None, 0.18, 60),
            ]:
                result = retrieval.explain(
                    conn,
                    index,
                    embedder,
                    query=q["query"],
                    scope_ids=[scope],
                    kinds=kinds,
                    policy=replace(retrieval.RetrievalPolicy(), min_relevance=floor),
                    budget_tokens=100_000,
                    limit=count,
                )
                # Remove generated UUIDs and timestamps from model/cache identities.
                pools[name] = [
                    replace(
                        r,
                        id=mapping[r.id],
                        scope="Fictional workspace",
                        scope_slug="fictional",
                        updated_at="2026-09-20T00:00:00Z",
                    )
                    for r in result.chosen
                ]
            snapshots.append((q, pools))
    return snapshots


def usage(calls):
    valid = [c["result"] for c in calls if "result" in c]
    billed = [c["result"] for c in calls if "result" in c and not c["cached"]]
    return {
        "calls": len(calls),
        "errors": sum("error" in c for c in calls),
        "cache_hits": sum(c["cached"] for c in calls),
        "input_tokens": sum(c["input_tokens"] for c in valid),
        "new_input_tokens": sum(c["input_tokens"] for c in billed),
        "estimated_usd": sum(c["input_tokens"] for c in valid) * PRICE_PER_MILLION_INPUT / 1e6,
        "new_estimated_usd": sum(c["input_tokens"] for c in billed) * PRICE_PER_MILLION_INPUT / 1e6,
        "provider_ms_sum": sum(c["latency_ms"] for c in valid),
    }


def evaluate(snapshot, provider, cache, budget, variants, selector_options=None):
    q, pools = snapshot
    output = {
        "query": q,
        "candidates": {k: [asdict(r) for r in v] for k, v in pools.items()},
        "variants": {},
    }
    for variant in variants:
        client = Recorded(provider, cache)
        rows = pools[
            "wide_facts"
            if variant == "wide_facts_jev"
            else "evidence"
            if variant.startswith("evidence")
            else "facts"
        ]
        started = time.perf_counter()
        if variant in {"facts_jev", "evidence_jev"}:
            rows = JevReranker(client, version="v2", min_score=2).rerank(q["query"], rows)
        elif variant in {"wide_facts_jev", "evidence_batches", "evidence_compact"}:
            rows = ContextSelector(
                client, compact=variant == "evidence_compact", **(selector_options or {})
            ).rerank(q["query"], rows)
        selected, tokens = pack(rows, budget)
        output["variants"][variant] = {
            "ids": [r.id for r in selected],
            "tokens": tokens,
            "wall_ms": (time.perf_counter() - started) * 1000,
            "usage": usage(client.calls),
            "calls": client.calls,
        }
    return output


def percentile(values, p):
    return sorted(values)[max(0, math.ceil(len(values) * p) - 1)] if values else 0


def metrics(records, data, variant):
    items = {i["id"]: i for i in data["items"]}
    expected = covered = irrelevant = redundant = empty_correct = empty_total = complete = 0
    tokens, latencies, input_tokens, new_tokens, errors = [], [], 0, 0, 0
    for record in records:
        q, result = record["query"], record["variants"][variant]
        wanted, seen = set(q["expected"]), set()
        expected += len(wanted)
        for key in result["ids"]:
            facets = set(items[key]["facets"])
            irrelevant += key not in q["relevant_ids"]
            if facets and facets <= seen:
                redundant += 1
            seen.update(facets)
        covered += len(wanted & seen)
        complete += bool(wanted) and wanted <= seen
        if not wanted:
            empty_total += 1
            empty_correct += not result["ids"]
        tokens.append(result["tokens"])
        latencies.append(result["usage"]["provider_ms_sum"])
        input_tokens += result["usage"]["input_tokens"]
        new_tokens += result["usage"]["new_input_tokens"]
        errors += result["usage"]["errors"]
    return {
        "queries": len(records),
        "details_retained": covered,
        "details_expected": expected,
        "fully_answerable_contexts": complete,
        "irrelevant_items": irrelevant,
        "redundant_items": redundant,
        "correct_empty": empty_correct,
        "unanswerable": empty_total,
        "mean_context_tokens": sum(tokens) / max(1, len(tokens)),
        "provider_ms_sum_p50": percentile(latencies, 0.5),
        "provider_ms_sum_p95": percentile(latencies, 0.95),
        "estimated_usd": input_tokens * PRICE_PER_MILLION_INPUT / 1e6,
        "new_estimated_usd": new_tokens * PRICE_PER_MILLION_INPUT / 1e6,
        "errors": errors,
    }


def check_coverage(case, provider, cache):
    client = Recorded(provider, cache)
    try:
        result = client.ask(
            {"source": case["source"], "memories": case["memories"]},
            {"missing": COVERAGE},
            version=VERSION,
        )
        probability = result.answers["missing"].value
    except SemanticError:
        probability = None
    return {"case": case, "probability": probability, "calls": client.calls}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "confirmation"], required=True)
    parser.add_argument("--budget", type=int, default=160)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--reuse-candidates", type=Path)
    parser.add_argument("--selection-policy", choices=["score", "contribution"], default="score")
    parser.add_argument("--relevance-floor", type=float)
    parser.add_argument("--redundancy-floor", type=float, default=0.95)
    parser.add_argument("--batch-size", type=int, default=10)
    args = parser.parse_args()
    data = corpus()
    frozen = Path("eval/corpora/context-details-v1.json")
    if json.loads(frozen.read_text()) != data:
        raise ValueError("corpus differs from frozen labels")
    provenance = code_identity()
    settings = get_settings()
    cache = Path("data/jev/context-cache")
    cache.mkdir(parents=True, exist_ok=True)
    if args.reuse_candidates:
        previous = json.loads(args.reuse_candidates.read_text())
        if previous["corpus_sha256"] != sha(data) or previous["split"] != args.split:
            raise ValueError("candidate snapshot is not the same corpus and split")
        snapshots = [
            (
                r["query"],
                {
                    k: [retrieval.Scored(**row) for row in rows]
                    for k, rows in r["candidates"].items()
                },
            )
            for r in previous["records"]
        ]
    else:
        snapshots = prepare(data, args.split)
    selector_options = {
        "relevance_mode": args.selection_policy,
        "relevance_floor": args.relevance_floor
        if args.relevance_floor is not None
        else (0.7 if args.selection_policy == "contribution" else 2),
        "redundancy_floor": args.redundancy_floor,
        "batch_size": args.batch_size,
    }
    print(f"Prepared {len(snapshots)} queries; corpus {sha(data)}", flush=True)
    records, coverage = [], []
    with (
        JevClient(settings.jev_api_key, model=settings.jev_model) as provider,
        ThreadPoolExecutor(max_workers=args.workers) as pool,
    ):
        futures = [
            pool.submit(evaluate, s, provider, cache, args.budget, args.variants, selector_options)
            for s in snapshots
        ]
        for future in as_completed(futures):
            records.append(future.result())
            print(f"Context {len(records)}/{len(snapshots)}", flush=True)
        if args.coverage:
            futures = [
                pool.submit(check_coverage, c, provider, cache)
                for c in data["coverage"]
                if c["split"] == args.split
            ]
            for future in as_completed(futures):
                coverage.append(future.result())
    records.sort(key=lambda r: r["query"]["id"])
    coverage.sort(key=lambda r: r["case"]["id"])
    summary = {v: metrics(records, data, v) for v in args.variants}
    if coverage:
        summary["coverage_signal"] = {
            "cases": len(coverage),
            "missing_detected": sum(
                r["case"]["expected"] and r["probability"] is not None and r["probability"] >= 0.8
                for r in coverage
            ),
            "missing_total": sum(r["case"]["expected"] for r in coverage),
            "false_alarms": sum(
                not r["case"]["expected"]
                and r["probability"] is not None
                and r["probability"] >= 0.8
                for r in coverage
            ),
            "covered_total": sum(not r["case"]["expected"] for r in coverage),
            "usage": usage([c for r in coverage for c in r["calls"]]),
        }
    artifact = {
        "corpus_sha256": sha(data),
        "split": args.split,
        "provenance": provenance,
        "questions_sha256": sha([question("relevance", "v2"), CONTRIBUTION, REDUNDANCY, COVERAGE]),
        "thresholds": selector_options | {"coverage": 0.8, "budget": args.budget},
        "candidate_snapshot": str(args.reuse_candidates) if args.reuse_candidates else None,
        "embedding": {"model": settings.embed_model, "revision": settings.embed_revision},
        "model": settings.jev_model,
        "price_per_million_input_usd": PRICE_PER_MILLION_INPUT,
        "metrics": summary,
        "records": records,
        "coverage": coverage,
        "by_language": {
            lang: {
                v: metrics([r for r in records if r["query"]["language"] == lang], data, v)
                for v in args.variants
            }
            for lang in sorted({r["query"]["language"] for r in records})
        },
    }
    folder = archive(
        artifact,
        root=Path("data/experiments"),
        name=f"context-{args.split}-{args.selection_policy}-{args.budget}",
        hypothesis="Evidence-aware selection preserves reasons and exceptions at a fixed context budget.",
        decision="inconclusive",
        data_class="synthetic",
        label_source="author-labeled; not independently reviewed",
        limitations=[
            "Eight authored scenario families per split; queries within a family are dependent.",
            "Separate experimental rows for evidence; not a production raw-message retrieval benchmark.",
            "Local exact Qdrant and disposable PostgreSQL; no production ANN/load claim.",
            "Cached calls reuse identical judgments. Summed provider latency is not end-to-end latency.",
        ],
    )
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Archived: {folder}", flush=True)
    return int(any(m.get("errors", 0) for m in summary.values()))


if __name__ == "__main__":
    raise SystemExit(main())
