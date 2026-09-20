"""Compare cosine duplicate proposals with Jev on frozen context scenario pairs.

Tests a second lifecycle stage without mutating any memories. Equivalence labels
come from the authored corpus: paraphrases are duplicates, sources add details,
and similarly named projects are different. The scenario set is already opened.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from memkit.config import get_settings
from memkit.embed import Embedder
from memkit.semantic import JevClient
from memkit.semantic_runtime import SemanticBlocks

from .context_cases import corpus
from .context_experiments import Recorded, usage
from .reports import archive, code_identity, sha
from .semantic import binary_metrics


def main():
    data, settings = corpus(), get_settings()
    pairs = []
    by_id = {i["id"]: i for i in data["items"]}
    for item in data["items"]:
        if not item["id"].endswith("-m0"):
            continue
        for suffix in ("m1", "m2", "e0", "e1", "e2", "d"):
            incoming = by_id[f"{item['family']}-{suffix}"]
            pairs.append(
                {
                    "id": incoming["id"],
                    "split": item["split"],
                    "existing": item["text"],
                    "incoming": incoming["text"],
                    "expected": suffix in {"m1", "m2"},
                }
            )
    provenance = code_identity()
    embedder = Embedder(
        settings.embed_model, settings.embed_device, settings.embed_revision, settings.embed_backend
    )
    texts = list(dict.fromkeys(t for p in pairs for t in (p["existing"], p["incoming"])))
    embeddings = dict(zip(texts, embedder.encode(texts), strict=True))
    cache = Path("data/jev/context-cache")
    cache.mkdir(parents=True, exist_ok=True)
    with JevClient(settings.jev_api_key, model=settings.jev_model) as provider:
        client = Recorded(provider, cache)
        allowed = SemanticBlocks(client, dedup="verify").verify_duplicates(
            {i: {"existing": p["existing"], "incoming": p["incoming"]} for i, p in enumerate(pairs)}
        )
    records = []
    for i, p in enumerate(pairs):
        cosine = float(np.dot(embeddings[p["existing"]], embeddings[p["incoming"]]))
        records.append(
            p
            | {
                "cosine": cosine,
                "cosine_only": cosine >= 0.9,
                "narrow_verified": cosine >= 0.9 and i in allowed,
                "broad_verified": cosine >= 0.75 and i in allowed,
                "judgment_only": i in allowed,
            }
        )
    metrics = {
        split: {
            key: binary_metrics([(r["expected"], r[key]) for r in records if r["split"] == split])
            for key in ("cosine_only", "narrow_verified", "broad_verified", "judgment_only")
        }
        for split in ("dev", "confirmation")
    }
    folder = archive(
        {
            "corpus_sha256": sha(pairs),
            "split": "opened-context-relation-diagnostic",
            "provenance": provenance,
            "metrics": metrics,
            "records": records,
            "calls": client.calls,
            "usage": usage(client.calls),
            "thresholds": {"cosine": 0.9, "broad_cosine": 0.75, "equivalent_probability": 0.9},
        },
        root=Path("data/experiments"),
        name="context-relation-candidate-width",
        hypothesis="Broader duplicate proposals verified by Jev recover paraphrases without absorbing new details.",
        decision="inconclusive",
        data_class="synthetic",
        label_source="author-labeled; not independently reviewed",
        limitations=[
            "Opened synthetic scenario families, not independent heldout relation evidence.",
            "All pairs judged for paired ablation; estimates are not production candidate-search costs.",
            "Measures pair decisions, not actual extraction writes or database races.",
        ],
    )
    print(json.dumps(metrics, indent=2))
    print(f"Archived: {folder}")
    return int(usage(client.calls)["errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
