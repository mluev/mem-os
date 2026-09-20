"""Reproducible HTTP readiness diagnostic with real embeddings and disposable storage.

The default never calls a paid provider. It launches only its own Qdrant container,
uses a socket-only temporary PostgreSQL cluster, and serves the real application
through Uvicorn. It never connects to configured production storage. Corpus labels
are synthetic, author-written diagnostics; results never promote a policy.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .reports import archive, code_identity, sha

CORPUS = Path(__file__).parent / "corpora" / "readiness-v1.json"
IMAGE = "qdrant/qdrant:v1.18.2"
MODEL = "BAAI/bge-m3"
REVISION = "5617a9f61b028005a4858fdac845db406aefb181"


def score_case(case: dict, response: dict, memories: dict, messages: dict) -> dict:
    items: list[tuple[str, str]] = []
    for row in response.get("memories", []):
        items.append((memories.get(row["id"], "unknown"), row["text"]))
        for source in row.get("sources", []):
            items.append((messages.get(int(source["message_id"]), "unknown"), source["excerpt"]))
    for row in response.get("raw", []):
        items.append((messages.get(int(row["message_id"]), "unknown"), row["text"]))
    details = case["details"]
    found = [
        pattern
        for pattern in details
        if any(
            key in case["relevant"] and re.search(pattern, text, re.IGNORECASE)
            for key, text in items
        )
    ]
    return {
        "case_id": case["id"],
        "details_found": len(found),
        "details_expected": len(details),
        "missing_details": [pattern for pattern in details if pattern not in found],
        "irrelevant_items": [key for key, _ in items if key not in case["relevant"]],
        "returned_items": [key for key, _ in items],
        "correct_abstention": not items if not details else None,
        "used_tokens": response.get("used_tokens", 0),
    }


def _percentile(values: list[float], fraction: float) -> float:
    values = sorted(values)
    return round(values[max(0, math.ceil(len(values) * fraction) - 1)], 2) if values else 0.0


def summarize(records: list[dict]) -> dict:
    negatives = [record for record in records if record.get("correct_abstention") is not None]
    return {
        "requests": len(records),
        "http_errors": sum(r["status"] != 200 for r in records),
        "details_found": sum(r["details_found"] for r in records),
        "details_expected": sum(r["details_expected"] for r in records),
        "irrelevant_items": sum(len(r["irrelevant_items"]) for r in records),
        "unanswerable_queries": len(negatives),
        "correct_abstentions": sum(r["correct_abstention"] is True for r in negatives),
        "budget_violations": sum(bool(r.get("budget_violation")) for r in records),
        "limit_violations": sum(bool(r.get("limit_violation")) for r in records),
        "wall_ms_p50": _percentile([r["wall_ms"] for r in records], 0.5),
        "wall_ms_p95": _percentile([r["wall_ms"] for r in records], 0.95),
    }


@contextmanager
def disposable_qdrant():
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker is required for the real-Qdrant HTTP benchmark")
    name = "memkit-readiness-" + secrets.token_hex(6)

    def command(*args):
        return subprocess.run(  # noqa: S603
            [docker, *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    command(
        "run",
        "--detach",
        "--rm",
        "--name",
        name,
        "--label",
        "memkit.purpose=disposable-readiness",
        "--publish",
        "127.0.0.1::6333",
        IMAGE,
    )
    try:
        address = command("port", name, "6333/tcp").splitlines()[0]
        url = "http://" + address
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                response = httpx.get(url + "/healthz", timeout=1)
                if response.is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("disposable Qdrant did not become ready")
        yield (
            url,
            {
                "image": IMAGE,
                "image_id": command("inspect", name, "--format", "{{.Image}}"),
                "engine": "Qdrant server",
                "temporary_storage": True,
            },
        )
    finally:
        subprocess.run([docker, "rm", "--force", name], capture_output=True, check=False)  # noqa: S603


@contextmanager
def http_server():
    import uvicorn

    from memkit.api import app

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 180
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not server.started:
            server.should_exit = True
            thread.join(timeout=10)
            raise RuntimeError("benchmark HTTP service failed to start")
        try:
            yield f"http://127.0.0.1:{listener.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(timeout=30)
            if thread.is_alive():
                raise RuntimeError("benchmark HTTP service did not shut down")


def seed(client: httpx.Client, conn, corpus: dict, distractors: int) -> tuple[dict, dict]:
    from memkit import extract, outbox, store
    from memkit.api import app

    memory_ids, message_ids = {}, {}
    by_key = {}
    for item in corpus["memories"]:
        body = {
            "text": item.get("initial_text", item["text"]),
            "kind": item.get("kind", "fact"),
            "source_role": item.get("source_role", "user"),
            "context": {"scenario": item["family"]},
        }
        response = client.post("/v1/memories", json=body)
        response.raise_for_status()
        memory_id = response.json()["id"]
        memory_ids[memory_id] = item["id"]
        by_key[item["id"]] = memory_id
        if "initial_text" in item:
            response = client.patch(
                f"/v1/memories/{memory_id}", json={"expected_revision": 1, "text": item["text"]}
            )
            response.raise_for_status()
    for item in corpus["evidence"]:
        response = client.post(
            "/v1/evidence/events",
            json={
                "session_id": "readiness-" + item["family"],
                "agent_id": "readiness-fixture",
                "role": item.get("role", "user"),
                "content": item["text"],
                "created_at": item["created_at"],
                "context": {"scenario": item["family"]},
            },
        )
        response.raise_for_status()
        message_id = response.json()["message_id"]
        message_ids[message_id] = item["id"]
        if item.get("supports"):
            import hashlib

            # Fixture provenance is linked directly because no paid extractor runs.
            with conn.transaction():
                extract._link_evidence(
                    conn,
                    by_key[item["supports"]],
                    [
                        {
                            "message_id": message_id,
                            "start_char": 0,
                            "end_char": len(item["text"]),
                            "excerpt_sha256": hashlib.sha256(item["text"].encode()).hexdigest(),
                        }
                    ],
                )
    caller = conn.execute("SELECT id FROM users WHERE handle='readiness'").fetchone()["id"]
    scope = conn.execute("SELECT id FROM entities WHERE user_id=%s", (caller,)).fetchone()["id"]
    with conn.transaction():
        for index in range(distractors):
            memory_id = store.add_memory(
                conn,
                scope_id=str(scope),
                author_id=str(caller),
                source_role="user",
                kind="fact",
                text=f"Archive project Cobalt-{index}: routine package builds completed on lane {index % 13}.",
                context={"scenario": "distractor"},
            )
            memory_ids[memory_id] = "distractor"
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        outbox.drain(conn, app.state.qdrant, app.state.embedder, limit=200)
        pending = conn.execute(
            "SELECT count(*) AS n FROM index_outbox WHERE status<>'done'"
        ).fetchone()["n"]
        if not pending:
            return memory_ids, message_ids
        time.sleep(0.1)
    raise RuntimeError("fixture index delivery did not finish")


def run_requests(
    client,
    queries,
    memory_ids,
    message_ids,
    *,
    policy_id,
    options,
    budget,
    limit,
    concurrency,
    repeats,
):
    from memkit.retrieval import _token_count

    def request(case):
        started = time.perf_counter()
        try:
            response = client.post(
                "/v1/memories/search",
                json={
                    "query": case["query"],
                    "budget_tokens": budget,
                    "limit": limit,
                    "policy_id": policy_id,
                    **options,
                },
            )
            payload = response.json()
            if response.status_code != 200:
                raise RuntimeError(f"HTTP {response.status_code}: {payload}")
            result = score_case(case, payload, memory_ids, message_ids)
            texts = [row["text"] for row in payload["memories"] + payload.get("raw", [])]
            texts += [s["excerpt"] for row in payload["memories"] for s in row.get("sources", [])]
            actual = sum(_token_count(text) + 6 for text in texts)
            result.update(
                status=200,
                actual_content_tokens=actual,
                budget_violation=actual > budget or actual != payload["used_tokens"],
                limit_violation=len(payload["memories"]) + len(payload.get("raw", [])) > limit,
            )
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            result = {
                "case_id": case["id"],
                "status": 503,
                "error": str(exc),
                "details_found": 0,
                "details_expected": len(case["details"]),
                "irrelevant_items": [],
                "correct_abstention": False if not case["details"] else None,
            }
        return result | {"wall_ms": round((time.perf_counter() - started) * 1000, 2)}

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        records = list(pool.map(request, queries * repeats))
    elapsed = time.perf_counter() - started
    metrics = summarize(records) | {"requests_per_second": round(len(records) / elapsed, 2)}
    return records, metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "heldout"], default="dev")
    parser.add_argument("--distractors", type=int, default=256)
    parser.add_argument("--concurrency", default="1,4,8")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--budget", type=int, default=160)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--semantic", choices=["off", "contribution", "compact"], default="off")
    parser.add_argument("--candidate-policy", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/experiments"))
    args = parser.parse_args()
    concurrency = [int(value) for value in args.concurrency.split(",")]
    if not concurrency or not all(1 <= n <= 32 for n in concurrency) or not 1 <= args.repeats <= 20:
        parser.error("concurrency must be 1–32 and repeats 1–20")
    if (
        not 0 <= args.distractors <= 10000
        or not 1 <= args.budget <= 20000
        or not 1 <= args.limit <= 200
    ):
        parser.error("distractors must be 0–10000, budget 1–20000, and limit 1–200")
    corpus = json.loads(CORPUS.read_text())
    execution_provenance = code_identity()
    queries = [query for query in corpus["queries"] if query["split"] == args.split]
    semantic_key = (
        (os.environ.get("JEV") or os.environ.get("TYPESAFE_API_KEY"))
        if args.semantic != "off"
        else ""
    )
    if args.semantic != "off" and not semantic_key:
        parser.error("explicit semantic modes require JEV or TYPESAFE_API_KEY in the environment")
    from memkit import config

    with tempfile.TemporaryDirectory(prefix="memkit-readiness-") as directory:
        credentials = {
            name: ""
            for name in (
                "ANTHROPIC_API_KEY",
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                "GOOGLE_VERTEX_API_KEY",
                "VERTEX_PROJECT",
                "GOOGLE_CLOUD_PROJECT",
                "VERTEX_LOCATION",
                "TYPESAFE_API_KEY",
            )
        }
        settings = config.Settings(
            _env_file=None,
            _env_prefix="MEMKIT_READINESS_UNUSED_",
            database_url="postgresql://unused.invalid/readiness",
            database_pool_max=10,
            telemetry_hmac_key=secrets.token_hex(32),
            export_dir=Path(directory) / "exports",
            backup_dir=Path(directory) / "backups",
            cookie_secure=False,
            embed_model=MODEL,
            embed_revision=REVISION,
            embed_backend="local",
            embed_dim=1024,
            JEV=semantic_key,
            semantic_dedup="off",
            semantic_support="off",
            semantic_retrieval="contribution" if args.semantic != "off" else "off",
            semantic_context=("compact" if args.semantic == "compact" else "select")
            if args.semantic != "off"
            else "off",
            **credentials,
        )
        config._settings = settings
        from memkit import auth, entities, policies, retrieval, users

        from .semantic_hybrid import disposable_postgres

        with disposable_postgres(durable=True) as conn, disposable_qdrant() as (qdrant_url, index):
            settings.database_url = conn.info.dsn
            settings.qdrant_url = qdrant_url
            with conn.transaction():
                entities.ensure_team(conn, name="Readiness fictional team")
                user = users.create(
                    conn,
                    handle="readiness",
                    display_name="Readiness fixture",
                    password=secrets.token_urlsafe(32),
                    role="admin",
                )
                key = auth.mint_api_key(conn, user_id=str(user["id"]), name="disposable-benchmark")
            policy_ids = {"current": "neutral-v1"}
            candidate = (
                json.loads(args.candidate_policy.read_text()) if args.candidate_policy else None
            )
            if candidate is not None:
                with conn.transaction():
                    policy_ids["candidate"] = policies.put_policy(
                        conn,
                        scope_id=None,
                        kind="retrieval",
                        name="readiness-candidate",
                        version=1,
                        config=candidate,
                    )
            policy_snapshots = {}
            for label, policy_id in policy_ids.items():
                snapshot = asdict(retrieval.load_policy(conn, policy_id))
                snapshot["allowed_source_roles"] = sorted(snapshot["allowed_source_roles"])
                policy_snapshots[label] = snapshot
            frozen_policy = {
                "captured_before_requests_at": datetime.now(UTC).isoformat(),
                "policies": policy_snapshots,
                "sha256": sha(policy_snapshots),
                "promotion": "none; diagnostic only",
            }
            startup = time.perf_counter()
            with (
                http_server() as url,
                httpx.Client(base_url=url, headers={"X-API-Key": key.token}, timeout=90) as client,
            ):
                startup_ms = (time.perf_counter() - startup) * 1000
                memory_ids, message_ids = seed(client, conn, corpus, args.distractors)
                from memkit.api import app

                if (
                    app.state.embedder._model_name != MODEL
                    or app.state.embedder._revision != REVISION
                ):
                    raise RuntimeError("benchmark model identity drifted")
                # One warm-up request; no warm-up observations enter the report.
                client.post(
                    "/v1/memories/search", json={"query": queries[0]["query"]}
                ).raise_for_status()
                records, metrics = {}, {}
                variants = {
                    "facts": {},
                    "sources": {"include_sources": True},
                    "raw": {"include_raw": True},
                    "context": {"include_raw": True, "include_sources": True},
                    "semantic_outage": {"include_raw": True, "include_sources": True},
                }
                from memkit.semantic import SemanticError
                from memkit.semantic_runtime import SemanticBlocks

                class UnavailableProvider:
                    def ask(self, *args, **kwargs):
                        raise SemanticError("deterministic injected outage; no provider called")

                    def close(self):
                        pass

                normal_semantic = app.state.semantic
                for label, policy_id in policy_ids.items():
                    for representation, options in variants.items():
                        app.state.semantic = (
                            SemanticBlocks(
                                UnavailableProvider(), retrieval="contribution", context="compact"
                            )
                            if representation == "semantic_outage"
                            else normal_semantic
                        )
                        app.state.reranker = app.state.semantic
                        for workers in concurrency:
                            name = f"{label}/{representation}/concurrency-{workers}"
                            observations, summary = run_requests(
                                client,
                                queries,
                                memory_ids,
                                message_ids,
                                policy_id=policy_id,
                                options=options,
                                budget=args.budget,
                                limit=args.limit,
                                concurrency=workers,
                                repeats=args.repeats,
                            )
                            records[name], metrics[name] = observations, summary
                            print(json.dumps({"variant": name, **summary}), flush=True)
                app.state.semantic = normal_semantic
                app.state.reranker = normal_semantic
                artifact = {
                    "corpus_sha256": sha(corpus),
                    "split": args.split,
                    "repeat": args.repeats,
                    "provenance": execution_provenance,
                    "code_changed_during_run": code_identity()["source_sha256"]
                    != execution_provenance["source_sha256"],
                    "model": MODEL,
                    "model_revision": REVISION,
                    "device": app.state.embedder.device,
                    "index": index,
                    "metrics": metrics,
                    "records": records,
                    "candidate_policy": candidate,
                    "frozen_policy": frozen_policy,
                    "database_pool_max": settings.database_pool_max,
                    "postgres_fsync": conn.execute("SHOW fsync").fetchone()["fsync"],
                    "thresholds": {
                        "budget_tokens": args.budget,
                        "limit": args.limit,
                        "distractors": args.distractors,
                        "concurrency": concurrency,
                        "semantic_mode": args.semantic,
                    },
                    "startup_ms": round(startup_ms, 2),
                    "paid_provider_enabled": args.semantic != "off",
                }
    folder = archive(
        artifact,
        root=args.output,
        name=f"http-readiness-{args.split}",
        hypothesis="The shipping HTTP context path preserves facts and bounds context under concurrent load.",
        decision="observe",
        data_class="synthetic",
        technology="BGE-M3 + PostgreSQL + Qdrant HTTP",
        label_source="frozen author-labeled synthetic scenarios; no independent review",
        compress=True,
        limitations=[
            "Synthetic diagnostic; repeated requests do not create independent quality samples.",
            "Fixture memories are authored and corrected through HTTP; extraction model quality is excluded.",
            "Source links are seeded directly because the default does not call a paid extractor.",
            "Single-process local service and a disposable Qdrant server; production topology and long histories differ.",
            "A Qdrant server run does not establish ANN recall without a separate exact-neighbor comparison.",
            "The semantic_outage variant injects deterministic provider failure and makes no provider request.",
            "This report never promotes a candidate policy; tuning after opening heldout requires a fresh heldout corpus.",
        ],
    )
    print(f"Archived: {folder}", flush=True)
    return int(
        any(
            m["http_errors"] or m["budget_violations"] or m["limit_violations"]
            for m in artifact["metrics"].values()
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
