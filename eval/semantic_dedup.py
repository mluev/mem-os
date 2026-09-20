"""Measure the actual batched duplicate block on frozen synthetic pair proposals.

The comparison isolates cosine proposals plus semantic verification. Runtime
scope/subject/citation/revision constraints are covered by database tests.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from memkit.config import get_settings
from memkit.semantic import JevClient
from memkit.semantic_runtime import SemanticBlocks

from .reports import archive, code_identity
from .semantic import binary_metrics, digest, embed_baselines


def main() -> int:
    corpus = json.loads(Path("eval/corpora/multiscenario-v1.json").read_text())
    rows = [c for c in corpus if c["stage"] == "relation"]
    baselines = embed_baselines(corpus, Path(f"data/jev/embeddings-{digest(corpus)[:16]}.json"))
    settings = get_settings()
    provenance = code_identity()
    proposals = {i: c["state"] for i, c in enumerate(rows) if baselines[c["id"]]["cosine"] >= 0.9}
    judgments, events = [], []
    with JevClient(settings.jev_api_key, model=settings.jev_model) as client:

        class RecordedClient:
            def ask(self, state, questions, *, version):
                result = client.ask(state, questions, version=version)
                judgments.append(asdict(result))
                return result

        blocks = SemanticBlocks(
            RecordedClient(), version="v2", dedup="verify", observer=events.append
        )
        allowed = blocks.verify_duplicates(proposals)
    records = [
        {
            "id": c["id"],
            "language": c["language"],
            "cohort": c["cohort"],
            "expected": c["expected"] == "equivalent",
            "baseline": i in proposals,
            "verified": i in allowed,
        }
        for i, c in enumerate(rows)
    ]
    metrics = {
        key: binary_metrics([(r["expected"], r[key]) for r in records])
        for key in ("baseline", "verified")
    }
    metrics["service_errors"] = sum(e["errors"] for e in events)
    artifact = {
        "corpus_sha256": digest(corpus),
        "split": "diagnostic-runtime-dedup",
        "provenance": provenance,
        "metrics": metrics,
        "records": records,
        "judgments": judgments,
        "observations": events,
        "thresholds": {"cosine": 0.9, "equivalent_probability": 0.9},
        "by_cohort": {
            cohort: {
                key: binary_metrics(
                    [(r["expected"], r[key]) for r in records if r["cohort"] == cohort]
                )
                for key in ("baseline", "verified")
            }
            for cohort in sorted({r["cohort"] for r in records})
        },
    }
    output = Path("data/jev/runtime-dedup-v2.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    folder = archive(
        artifact,
        root=Path("data/experiments"),
        name="runtime-dedup-v2",
        hypothesis="The batched runtime verifier vetoes false cosine matches.",
        decision="inconclusive",
        data_class="synthetic",
        label_source="author-labeled; not independently reviewed",
        limitations=[
            "Pairs from the already opened multi-scenario diagnostic set.",
            "Measures semantic vetoes; database permission and race invariants are tested offline.",
        ],
        source_name=output.name,
    )
    print(json.dumps(metrics, indent=2))
    print(f"Archived: {folder}")
    return int(metrics["service_errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
