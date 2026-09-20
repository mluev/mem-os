"""Explicit live Jev experiment, separate from offline pytest and production data.

Run development first, freeze questions/thresholds, then run heldout. Artifacts
record exact outcomes, corpus/request hashes, resolved models, and service errors.
The optional BGE baseline is dense-only: it is not the full production fusion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memkit.config import get_settings
from memkit.semantic import JevClient, SemanticError
from memkit.semantic_questions import QUESTIONS, question

from .reports import archive, code_identity
from .semantic_cases import cases


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def validate(corpus: list[dict[str, Any]]) -> None:
    if not corpus:
        raise ValueError("empty corpus")
    ids = [c["id"] for c in corpus]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case id")
    for case in corpus:
        if not isinstance(case["language"], str) or not case["language"]:
            raise ValueError("language is required")
        if case["split"] not in {"dev", "heldout"} or case["stage"] not in QUESTIONS["v1"]:
            raise ValueError("unknown split or stage")
        if case["stage"] == "relevance" and not set(case["expected"]) <= set(
            range(len(case["state"]["memories"]))
        ):
            raise ValueError("invalid expected candidate")
        if case["stage"] == "support" and type(case["expected"]) is not bool:
            raise ValueError("support label must be boolean")
        if (
            case["stage"] == "relation"
            and case["expected"] not in QUESTIONS["v2"]["relation"]["criteria"]
        ):
            raise ValueError("invalid relation label")


def embed_baselines(corpus: list[dict[str, Any]], cache_path: Path) -> dict[str, Any]:
    """Actual configured BGE embeddings; cache never contains credentials or private data."""
    settings = get_settings()
    specification = {
        "model": settings.embed_model,
        "revision": settings.embed_revision,
        "corpus": digest(corpus),
    }
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        if cached.get("specification") == specification:
            return cached["baselines"]
    from memkit.embed import Embedder

    texts = []
    for case in corpus:
        state = case["state"]
        if case["stage"] == "relation":
            texts.extend([state["existing"], state["incoming"]])
        elif case["stage"] == "relevance":
            texts.extend([state["query"], *state["memories"]])
    texts = list(dict.fromkeys(texts))
    embedder = Embedder(
        settings.embed_model, settings.embed_device, settings.embed_revision, settings.embed_backend
    )
    vectors = dict(zip(texts, embedder.encode(texts), strict=True))

    def cosine(a: str, b: str) -> float:
        return sum(x * y for x, y in zip(vectors[a], vectors[b], strict=True))

    baselines = {}
    for case in corpus:
        state = case["state"]
        if case["stage"] == "relation":
            baselines[case["id"]] = {"cosine": cosine(state["existing"], state["incoming"])}
        elif case["stage"] == "relevance":
            baselines[case["id"]] = {
                "scores": [cosine(state["query"], t) for t in state["memories"]]
            }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps({"specification": specification, "baselines": baselines}, indent=2)
    )
    return baselines


def evaluate(client: JevClient, case: dict[str, Any], version: str, run: int) -> dict[str, Any]:
    stage = case["stage"]
    record = {
        "id": case["id"],
        "run": run,
        "stage": stage,
        "language": case["language"],
        "expected": case["expected"],
        "scenario": case.get("scenario", "unspecified"),
        "cohort": case.get("cohort", "unspecified"),
    }
    try:
        if stage == "relevance":
            questions = {}
            for i in range(len(case["state"]["memories"])):
                q = question(stage, version)
                q["instructions"] = q["instructions"].replace("`memory`", f"`memories[{i}]`")
                questions[str(i)] = q
            result = client.ask(case["state"], questions, version=version)
        else:
            result = client.judge(stage, case["state"], version=version)
        record["judgment"] = asdict(result)
    except SemanticError as exc:
        record["error"] = str(exc)
    return record


def binary_metrics(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    tp = sum(want and got for want, got in pairs)
    fp = sum(not want and got for want, got in pairs)
    fn = sum(want and not got for want, got in pairs)
    return {
        "n": len(pairs),
        "accuracy": (len(pairs) - fp - fn) / len(pairs) if pairs else None,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def ranking_metrics(rows: list[tuple[list[int], list[float]]], floor: float) -> dict[str, Any]:
    ranks, top1, empty_ok, answerable, retained, total_relevant = [], 0, 0, 0, 0, 0
    false_empty = 0
    for expected, scores in rows:
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        selected = [i for i in order if scores[i] >= floor]
        if expected:
            answerable += 1
            first = next(i + 1 for i, index in enumerate(order) if index in expected)
            ranks.append(1 / first)
            top1 += order[0] in expected
            false_empty += not selected
            retained += len(set(selected) & set(expected))
            total_relevant += len(expected)
        else:
            empty_ok += not selected
    negatives = len(rows) - answerable
    return {
        "n": len(rows),
        "answerable": answerable,
        "top1": top1 / answerable if answerable else None,
        "mrr": statistics.mean(ranks) if ranks else None,
        "unanswerable": negatives,
        "correct_abstentions": empty_ok,
        "false_empty": false_empty,
        "relevant_retained": retained,
        "relevant_total": total_relevant,
    }


def summarize(
    records: list[dict[str, Any]],
    baselines: dict[str, Any],
    *,
    support_floor: float,
    duplicate_floor: float,
    relevance_floor: float,
) -> dict[str, Any]:
    usable = [r for r in records if "judgment" in r]
    support = [r for r in usable if r["stage"] == "support"]
    relations = [r for r in usable if r["stage"] == "relation"]
    retrieval = [r for r in usable if r["stage"] == "relevance"]

    def probability(r: dict, label: str) -> float:
        answer = r["judgment"]["answers"][r["stage"]]
        return answer["value"] if answer["kind"] == "noul" else answer["probabilities"][label]

    ranking_rows = [
        (
            r["expected"],
            [
                r["judgment"]["answers"][str(i)]["value"]
                for i in range(len(r["judgment"]["answers"]))
            ],
        )
        for r in retrieval
    ]
    metrics: dict[str, Any] = {
        "cases": len(records),
        "service_errors": len(records) - len(usable),
        "support": binary_metrics(
            [(r["expected"], probability(r, "supported") >= support_floor) for r in support]
        ),
        "citation_only_acceptance": binary_metrics([(r["expected"], True) for r in support]),
        "relation": {
            "n": len(relations),
            "correct": sum(
                r["expected"] == r["judgment"]["answers"]["relation"]["choice"] for r in relations
            ),
        },
        "duplicate": binary_metrics(
            [
                (r["expected"] == "equivalent", probability(r, "equivalent") >= duplicate_floor)
                for r in relations
            ]
        ),
        "retrieval": ranking_metrics(ranking_rows, relevance_floor),
    }
    if baselines:
        metrics["verified_cosine_duplicate_at_0.90"] = binary_metrics(
            [
                (
                    r["expected"] == "equivalent",
                    baselines[r["id"]]["cosine"] >= 0.90
                    and probability(r, "equivalent") >= duplicate_floor,
                )
                for r in relations
            ]
        )
        metrics["cosine_duplicate_at_0.90"] = binary_metrics(
            [
                (r["expected"] == "equivalent", baselines[r["id"]]["cosine"] >= 0.90)
                for r in relations
            ]
        )
        metrics["dense_only_retrieval"] = ranking_metrics(
            [(r["expected"], baselines[r["id"]]["scores"]) for r in retrieval], -math.inf
        )
    metrics["input_tokens"] = sum(r["judgment"]["input_tokens"] for r in usable)
    metrics["output_tokens"] = sum(r["judgment"]["output_tokens"] for r in usable)
    metrics["median_request_ms"] = (
        statistics.median([r["judgment"]["latency_ms"] for r in usable]) if usable else None
    )
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--version", choices=list(QUESTIONS), default="v1")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--embeddings", action="store_true")
    parser.add_argument("--schema-only", action="store_true")
    parser.add_argument("--support-floor", type=float, default=0.9)
    parser.add_argument("--duplicate-floor", type=float, default=0.9)
    parser.add_argument("--relevance-floor", type=float, default=2.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--corpus", type=Path, help="External labeled JSON corpus using the same case schema"
    )
    parser.add_argument("--model", help="Explicit provider model pin to compare")
    parser.add_argument("--data-class", choices=["synthetic", "private"], default="private")
    parser.add_argument("--label-source", default="author-labeled; not independently reviewed")
    parser.add_argument(
        "--hypothesis", default="Measure semantic blocks against frozen labels and thresholds."
    )
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text()) if args.corpus else cases()
    validate(corpus)
    if args.schema_only:
        print(json.dumps(dict(Counter((c["split"] + "/" + c["stage"]) for c in corpus)), indent=2))
        return 0
    if not 1 <= args.repeat <= 10 or not 1 <= args.workers <= 8:
        parser.error("repeat must be 1..10 and workers 1..8")
    if not (
        0 <= args.support_floor <= 1
        and 0 <= args.duplicate_floor <= 1
        and 0 <= args.relevance_floor <= 3
    ):
        parser.error("thresholds are outside their valid ranges")
    selected = [c for c in corpus if c["split"] == args.split]
    if not selected:
        parser.error("selected split is empty")
    provenance = code_identity()
    # Only embed the selected split; heldout content is not evaluated during tuning.
    baselines = (
        embed_baselines(selected, Path(f"data/jev/embeddings-{digest(selected)[:16]}.json"))
        if args.embeddings
        else {}
    )
    settings = get_settings()
    records = []
    started = time.perf_counter()
    with (
        JevClient(settings.jev_api_key, model=args.model or settings.jev_model) as client,
        ThreadPoolExecutor(max_workers=args.workers) as pool,
    ):
        futures = [
            pool.submit(evaluate, client, c, args.version, run)
            for run in range(args.repeat)
            for c in selected
        ]
        for future in as_completed(futures):
            records.append(future.result())
            if len(records) % 10 == 0:
                print(f"Evaluated {len(records)}/{len(futures)}", flush=True)
    records.sort(key=lambda r: (r["run"], r["id"]))
    thresholds = {
        "support_floor": args.support_floor,
        "duplicate_floor": args.duplicate_floor,
        "relevance_floor": args.relevance_floor,
    }
    metrics = summarize(records, baselines, **thresholds)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path(f"data/jev/{stamp}-{args.version}-{args.split}.json")
    artifact = {
        "created_at": stamp,
        "provenance": provenance,
        "version": args.version,
        "split": args.split,
        "corpus_sha256": digest(corpus),
        "questions_sha256": digest(QUESTIONS[args.version]),
        "thresholds": thresholds,
        "repeat": args.repeat,
        "metrics": metrics,
        "by_language": {
            lang: summarize([r for r in records if r["language"] == lang], baselines, **thresholds)
            for lang in sorted({r["language"] for r in records})
        },
        "by_scenario": {
            value: summarize(
                [r for r in records if r["scenario"] == value], baselines, **thresholds
            )
            for value in sorted({r["scenario"] for r in records})
        },
        "by_cohort": {
            value: summarize([r for r in records if r["cohort"] == value], baselines, **thresholds)
            for value in sorted({r["cohort"] for r in records})
        },
        "wall_seconds": time.perf_counter() - started,
        "baselines": baselines,
        "records": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    saved = archive(
        artifact,
        root=Path("data/experiments"),
        name=f"semantic-{args.version}-{args.split}",
        hypothesis=args.hypothesis,
        decision="inconclusive",
        label_source=args.label_source,
        data_class=args.data_class if args.corpus else "synthetic",
        limitations=[
            "No automatic promotion; inspect regressions and slices before deciding.",
            "Repeated calls are not independent examples; labels may require review.",
        ],
        source_name=output.name,
    )
    print(json.dumps(metrics, indent=2))
    print(f"Artifact: {output}")
    print(f"Archived: {saved}")
    return int(metrics["service_errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
