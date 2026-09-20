"""Live semantic filtering after the real hybrid retriever in disposable storage.

Uses real PostgreSQL lexical/identifier arms, configured BGE embeddings and
Qdrant's local exact-vector engine. Never opens the configured production DB.
The local vector engine is not a benchmark of Qdrant server ANN recall/latency.
"""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import subprocess
import tempfile
import warnings
from contextlib import closing, contextmanager
from pathlib import Path

from qdrant_client import QdrantClient

from memkit import db, entities, outbox, retrieval, store, users, vectors
from memkit.config import get_settings
from memkit.embed import Embedder
from memkit.semantic import JevClient
from memkit.semantic_runtime import SemanticBlocks

from .reports import archive, code_identity, sha
from .semantic import validate


@contextmanager
def disposable_postgres():
    candidates = [
        Path(shutil.which("initdb") or "/nonexistent").parent,
        Path("/opt/homebrew/opt/postgresql@16/bin"),
        Path("/opt/homebrew/opt/postgresql@17/bin"),
        Path("/usr/lib/postgresql/16/bin"),
    ]
    binaries = next((p for p in candidates if (p / "initdb").is_file()), None)
    if binaries is None:
        raise RuntimeError("a local PostgreSQL installation is required")
    # A unique socket directory and no TCP listener isolate this from every service.
    with tempfile.TemporaryDirectory(prefix="mkexp.", dir="/tmp") as folder:
        root = Path(folder)
        data = root / "db"

        def run(name, *args):
            subprocess.run(  # noqa: S603
                [str(binaries / name), *args], check=True, capture_output=True, text=True
            )

        run(
            "initdb",
            "-D",
            str(data),
            "-U",
            "memkit",
            "--auth=trust",
            "-E",
            "UTF8",
            "--locale=C.UTF-8",
        )
        run(
            "pg_ctl",
            "-D",
            str(data),
            "-o",
            f"-k {root} -c listen_addresses='' -c fsync=off",
            "-l",
            str(root / "server.log"),
            "-w",
            "start",
        )
        try:
            url = f"postgresql:///postgres?user=memkit&host={root}"
            db.init_db(url)
            with db.connect(url) as conn:
                yield conn
        finally:
            run("pg_ctl", "-D", str(data), "-m", "immediate", "-w", "stop")


def metrics(records, key):
    answerable = [r for r in records if r["expected"]]
    empty = [r for r in records if not r["expected"]]
    return {
        "queries": len(records),
        "answerable": len(answerable),
        "top1_correct": sum(bool(r[key]) and r[key][0] in r["expected"] for r in answerable),
        "relevant_retained": sum(len(set(r[key]) & set(r["expected"])) for r in records),
        "relevant_total": sum(len(r["expected"]) for r in records),
        "unanswerable": len(empty),
        "correct_abstentions": sum(not r[key] for r in empty),
        "irrelevant_returned": sum(len(set(r[key]) - set(r["expected"])) for r in records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/jev/hybrid-v2.json"))
    parser.add_argument("--mode", choices=["filter", "contribution"], default="filter")
    args = parser.parse_args()
    # This runner intentionally accepts only the repository's fictional fixture.
    corpus = json.loads(Path("eval/corpora/multiscenario-v1.json").read_text())
    validate(corpus)
    cases = [c for c in corpus if c["stage"] == "relevance"]
    provenance = code_identity()
    settings = get_settings()
    embedder = Embedder(
        settings.embed_model, settings.embed_device, settings.embed_revision, settings.embed_backend
    )
    texts = list(dict.fromkeys(t for c in cases for t in c["state"]["memories"]))
    events, records = [], []
    with (
        disposable_postgres() as conn,
        closing(QdrantClient(":memory:")) as index,
        JevClient(settings.jev_api_key, model=settings.jev_model) as provider,
    ):
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="Payload indexes have no effect.*")
            vectors.ensure_collections(index)
        with conn.transaction():
            entities.ensure_team(conn, name="Synthetic experiment")
            user = users.create(
                conn,
                handle="synthetic-evaluator",
                display_name="Fictional evaluator",
                password=secrets.token_urlsafe(32),
            )
            scope = str(entities.own_entity(conn, str(user["id"]))["id"])
            ids = {
                text: store.add_memory(
                    conn,
                    scope_id=scope,
                    author_id=str(user["id"]),
                    text=text,
                    kind="fact",
                    source_role="user",
                )
                for text in texts
            }
        outbox.drain(conn, index, embedder, limit=100)
        text_by_id = {value: key for key, value in ids.items()}
        blocks = SemanticBlocks(provider, version="v2", retrieval=args.mode, observer=events.append)
        for i, case in enumerate(cases):
            query = case["state"]["query"]
            kwargs = {"query": query, "scope_ids": [scope], "limit": 30, "budget_tokens": 800}
            before = retrieval.explain(conn, index, embedder, **kwargs)
            after = retrieval.explain(conn, index, embedder, reranker=blocks, **kwargs)
            records.append(
                {
                    "id": case["id"],
                    "language": case["language"],
                    "cohort": case["cohort"],
                    "expected": [case["state"]["memories"][j] for j in case["expected"]],
                    "baseline": [text_by_id[r.id] for r in before.chosen],
                    "filtered": [text_by_id[r.id] for r in after.chosen],
                    "observation": events[-1] if events else None,
                }
            )
            print(f"Hybrid queries {i + 1}/{len(cases)}", flush=True)
    result = {
        "baseline": metrics(records, "baseline"),
        "filtered": metrics(records, "filtered"),
        "service_errors": sum(e.get("errors", 0) for e in events),
    }
    artifact = {
        "corpus_sha256": sha(corpus),
        "split": "diagnostic-hybrid",
        "provenance": provenance,
        "retrieval_policy": "neutral-v1",
        "embedding": {"model": settings.embed_model, "revision": settings.embed_revision},
        "thresholds": {"mode": args.mode, "relevance_floor": 2.0 if args.mode == "filter" else 0.7},
        "metrics": result,
        "records": records,
        "by_cohort": {
            c: {
                key: metrics([r for r in records if r["cohort"] == c], key)
                for key in ("baseline", "filtered")
            }
            for c in sorted({r["cohort"] for r in records})
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    folder = archive(
        artifact,
        root=Path("data/experiments"),
        name=f"hybrid-{args.mode}-v2",
        hypothesis="Semantic filtering removes irrelevant hybrid results without losing useful context.",
        decision="inconclusive",
        data_class="synthetic",
        label_source="author-labeled; not independently reviewed",
        limitations=[
            "Synthetic reused diagnostic cases, not a new independent heldout set.",
            "Real PostgreSQL and BGE; local exact Qdrant, not server ANN or load behavior.",
        ],
        source_name=args.output.name,
    )
    print(json.dumps(result, indent=2))
    print(f"Archived: {folder}")
    return int(result["service_errors"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
