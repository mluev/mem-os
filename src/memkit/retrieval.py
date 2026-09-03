"""Trust-aware hybrid retrieval with an explicit abstention policy."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from qdrant_client import QdrantClient

from . import filters, vectors
from .embed import Embedder
from .store import memory_active

WORD_RE = re.compile(r"[\w./:@#-]+", re.UNICODE)
DEFAULT_TRUST = frozenset({"user", "manual", "tool"})


@dataclass(frozen=True)
class RetrievalPolicy:
    id: str = "neutral-v1"
    dense_weight: float = 0.60
    lexical_weight: float = 0.30
    entity_weight: float = 0.10
    importance_weight: float = 0.10
    recency_weight: float = 0.05
    min_relevance: float = 0.18
    allowed_source_roles: frozenset[str] = DEFAULT_TRUST
    default_half_life_days: float = 180.0


def load_policy(conn: sqlite3.Connection, policy_id: str) -> RetrievalPolicy:
    aliases = {"neutral-v1": "core-retrieval-neutral-v1"}
    resolved = aliases.get(policy_id, policy_id)
    row = conn.execute(
        "SELECT id,config_json FROM policies WHERE id=? AND kind='retrieval'", (resolved,)
    ).fetchone()
    if row is None:
        raise ValueError("unknown retrieval policy")
    config = json.loads(row["config_json"])
    return RetrievalPolicy(
        id=row["id"],
        dense_weight=float(config.get("dense_weight", 0.60)),
        lexical_weight=float(config.get("lexical_weight", 0.30)),
        entity_weight=float(config.get("entity_weight", 0.10)),
        importance_weight=float(config.get("importance_weight", 0.10)),
        recency_weight=float(config.get("recency_weight", 0.05)),
        min_relevance=float(config.get("min_relevance", 0.18)),
        allowed_source_roles=frozenset(config.get("allowed_source_roles", DEFAULT_TRUST)),
        default_half_life_days=float(config.get("default_half_life_days", 180.0)),
    )


@dataclass
class Scored:
    id: str
    text: str
    kind: str
    context: dict[str, Any]
    tags: list[str]
    source_role: str
    similarity: float
    lexical: float
    entity: float
    importance: float
    recency: float
    score: float
    updated_at: str
    revision: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "kind": self.kind,
            "context": self.context,
            "tags": self.tags,
            "source_role": self.source_role,
            # A correction is a PATCH with `expected_revision`; without this an
            # agent that found a wrong fact by searching cannot fix it.
            "revision": self.revision,
            "score": round(self.score, 4),
            "similarity": round(self.similarity, 4),
            "lexical": round(self.lexical, 4),
            "entity": round(self.entity, 4),
            "importance": round(self.importance, 3),
            "recency": round(self.recency, 4),
            "updated_at": self.updated_at,
        }


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[Scored]) -> list[Scored]: ...


class IdentityReranker:
    def rerank(self, query: str, candidates: list[Scored]) -> list[Scored]:
        return candidates


@dataclass
class Explain:
    chosen: list[Scored]
    used_tokens: int
    dropped_trust: list[str] = field(default_factory=list)
    dropped_validity: list[str] = field(default_factory=list)
    dropped_filter: list[str] = field(default_factory=list)
    dropped_relevance: list[str] = field(default_factory=list)
    policy_id: str = "neutral-v1"
    embed_ms: float = 0.0
    timings: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "memories": [memory.as_dict() for memory in self.chosen],
            "used_tokens": self.used_tokens,
            "dropped_trust": self.dropped_trust,
            "dropped_validity": self.dropped_validity,
            "dropped_filter": self.dropped_filter,
            "dropped_relevance": self.dropped_relevance,
            "policy_id": self.policy_id,
            "embed_ms": round(self.embed_ms, 1),
            "timings": {key: round(value, 1) for key, value in self.timings.items()},
        }


def _terms(text: str) -> list[str]:
    return [term.casefold() for term in WORD_RE.findall(text)]


def _bm25(query: str, rows: list[sqlite3.Row]) -> dict[str, float]:
    query_terms = list(dict.fromkeys(_terms(query)))
    if not query_terms or not rows:
        return {}
    documents = {row["id"]: _terms(row["text"]) for row in rows}
    avg_length = sum(len(doc) for doc in documents.values()) / max(1, len(documents))
    doc_frequency = {
        term: sum(term in set(doc) for doc in documents.values()) for term in query_terms
    }
    scores: dict[str, float] = {}
    for memory_id, document in documents.items():
        frequencies = Counter(document)
        score = 0.0
        for term in query_terms:
            frequency = frequencies[term]
            if not frequency:
                continue
            df = doc_frequency[term]
            inverse = math.log(1 + (len(rows) - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.2 * (1 - 0.75 + 0.75 * len(document) / max(1.0, avg_length))
            score += inverse * frequency * 2.2 / denominator
        if score > 0:
            scores[memory_id] = score
    maximum = max(scores.values(), default=1.0)
    return {memory_id: score / maximum for memory_id, score in scores.items()}


def _entity_matches(query: str, rows: list[sqlite3.Row]) -> dict[str, float]:
    """Find identifier-like exact terms as a separate candidate arm."""
    entities = {
        token.casefold()
        for token in WORD_RE.findall(query)
        if any(char.isdigit() or char in "./:@#_-" for char in token)
        or (len(token) > 1 and token.isupper())
    }
    if not entities:
        return {}
    return {
        row["id"]: 1.0
        for row in rows
        if any(entity in row["text"].casefold() for entity in entities)
    }


def _fts_candidates(
    conn: sqlite3.Connection, *, query: str, owner_id: str, limit: int
) -> dict[str, float]:
    """Return a bounded, normalized FTS5 candidate set.

    Tokens come from ``WORD_RE`` and are quoted individually, so user input is
    never interpreted as FTS syntax. SQLite's BM25 is lower-is-better; ranking
    by reciprocal position keeps the lexical component stable and bounded.
    """
    terms = list(dict.fromkeys(_terms(query)))
    if not terms:
        return {}
    match = " OR ".join(f'"{term}"' for term in terms[:32])
    rows = conn.execute(
        """SELECT memory_id,bm25(memories_fts,0.0,0.0,1.0,0.35,0.2) AS rank
           FROM memories_fts
           WHERE memories_fts MATCH ? AND owner_id=?
           ORDER BY rank,memory_id LIMIT ?""",
        (match, owner_id, limit),
    ).fetchall()
    if not rows:
        return {}
    # FTS5's BM25 is negative/lower-is-better. Normalize the bounded result
    # scores by the strongest magnitude; unlike reciprocal rank this does not
    # arbitrarily push the second equally relevant document below abstention.
    magnitudes = [abs(float(row["rank"])) for row in rows]
    maximum = max(magnitudes, default=1.0) or 1.0
    return {
        str(row["memory_id"]): magnitude / maximum
        for row, magnitude in zip(rows, magnitudes, strict=True)
    }


def _entity_candidates(
    conn: sqlite3.Connection, *, query: str, owner_id: str, limit: int
) -> dict[str, float]:
    entities = list(
        dict.fromkeys(
            token.casefold()
            for token in WORD_RE.findall(query)
            if any(char.isdigit() or char in "./:@#_-" for char in token)
            or (len(token) > 1 and token.isupper())
        )
    )[:16]
    if not entities:
        return {}
    # Use the transactional FTS projection instead of scanning every memory
    # with ``instr(lowerx(text), ...)``. Quoted entity phrases preserve exact
    # identifier matching while the LIMIT keeps this arm bounded at 100k+ rows.
    match = " OR ".join(f'"{entity}"' for entity in entities)
    rows = conn.execute(
        """SELECT memory_id FROM memories_fts
            WHERE memories_fts MATCH ? AND owner_id=?
            ORDER BY bm25(memories_fts),memory_id LIMIT ?""",
        (match, owner_id, limit),
    ).fetchall()
    return {str(row["memory_id"]): 1.0 for row in rows}


def _candidate_rows(
    conn: sqlite3.Connection, *, owner_id: str, candidate_ids: set[str]
) -> dict[str, sqlite3.Row]:
    if not candidate_ids:
        return {}
    ordered = sorted(candidate_ids)
    placeholders = ",".join("?" for _ in ordered)
    rows = conn.execute(
        f"SELECT * FROM memories WHERE owner_id=? AND id IN ({placeholders})",
        (owner_id, *ordered),
    ).fetchall()
    return {str(row["id"]): row for row in rows}


def _age_days(value: str, now: datetime) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (now - parsed).total_seconds() / 86_400)


def _token_count(text: str) -> int:
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except (ImportError, ValueError):
        # Conservative Unicode-aware fallback; unlike len/3 it counts words,
        # punctuation and non-Latin text independently.
        return max(1, len(re.findall(r"\w+|[^\w\s]", text, re.UNICODE)))


def _fill_budget(rows: list[Scored], budget_tokens: int) -> tuple[list[Scored], int]:
    chosen: list[Scored] = []
    used = 0
    for row in rows:
        cost = _token_count(row.text)
        if used + cost > budget_tokens:
            continue
        chosen.append(row)
        used += cost
    return chosen, used


def explain(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    owner_id: str,
    expression: dict[str, Any] | None = None,
    kinds: list[str] | None = None,
    limit: int = 30,
    budget_tokens: int = 800,
    policy: RetrievalPolicy | None = None,
    include_untrusted: bool = False,
    reranker: Reranker | None = None,
    now: datetime | None = None,
    memory_collection: str = vectors.MEMORIES,
) -> Explain:
    total_started = time.perf_counter()
    filters.validate(expression)
    policy = policy or RetrievalPolicy()
    now = now or datetime.now(UTC)
    embed_started = time.perf_counter()
    dense_vector = embedder.encode_one(query)
    embed_ms = (time.perf_counter() - embed_started) * 1000
    dense_started = time.perf_counter()
    dense_hits = vectors.search(
        client,
        memory_collection,
        dense_vector,
        limit=max(50, limit * 3),
        must=[vectors.keyword("owner_id", owner_id), vectors.keyword("status", "active")],
    )
    dense_ms = (time.perf_counter() - dense_started) * 1000
    dense = {str(hit.id): max(0.0, float(hit.score)) for hit in dense_hits}
    candidate_limit = max(50, limit * 3)
    lexical_started = time.perf_counter()
    lexical = _fts_candidates(conn, query=query, owner_id=owner_id, limit=candidate_limit)
    lexical_ms = (time.perf_counter() - lexical_started) * 1000
    entity_started = time.perf_counter()
    entity = _entity_candidates(conn, query=query, owner_id=owner_id, limit=candidate_limit)
    entity_ms = (time.perf_counter() - entity_started) * 1000
    candidate_ids = set(dense) | set(lexical) | set(entity)
    fetch_started = time.perf_counter()
    row_by_id = _candidate_rows(conn, owner_id=owner_id, candidate_ids=candidate_ids)
    fetch_ms = (time.perf_counter() - fetch_started) * 1000

    dropped_trust: list[str] = []
    dropped_validity: list[str] = []
    dropped_filter: list[str] = []
    dropped_relevance: list[str] = []
    scored: list[Scored] = []
    scoring_started = time.perf_counter()
    for memory_id in sorted(candidate_ids):
        row = row_by_id.get(memory_id)
        if row is None:
            continue
        if not memory_active(row, now=now):
            dropped_validity.append(memory_id)
            continue
        if not include_untrusted and row["source_role"] not in policy.allowed_source_roles:
            dropped_trust.append(memory_id)
            continue
        if kinds and row["kind"] not in kinds:
            dropped_filter.append(memory_id)
            continue
        context = json.loads(row["context_json"] or "{}")
        tags = json.loads(row["tags_json"] or "[]")
        document = {
            "kind": row["kind"],
            "agent_id": row["agent_id"],
            "context": context,
            "tags": tags,
        }
        if not filters.matches(document, expression):
            dropped_filter.append(memory_id)
            continue
        similarity = dense.get(memory_id, 0.0)
        lexical_score = lexical.get(memory_id, 0.0)
        entity_score = entity.get(memory_id, 0.0)
        relevance = (
            policy.dense_weight * similarity
            + policy.lexical_weight * lexical_score
            + policy.entity_weight * entity_score
        )
        if relevance < policy.min_relevance:
            dropped_relevance.append(memory_id)
            continue
        recency = math.exp(-_age_days(row["updated_at"], now) / policy.default_half_life_days)
        score = (
            relevance
            + policy.importance_weight * float(row["importance"])
            + policy.recency_weight * recency
        )
        scored.append(
            Scored(
                id=memory_id,
                text=row["text"],
                kind=row["kind"],
                context=context,
                tags=tags,
                source_role=row["source_role"],
                similarity=similarity,
                lexical=lexical_score,
                entity=entity_score,
                importance=float(row["importance"]),
                recency=recency,
                score=score,
                updated_at=row["updated_at"],
                revision=int(row["revision"]),
            )
        )
    scored.sort(key=lambda item: (-item.score, item.id))
    scored = (reranker or IdentityReranker()).rerank(query, scored)
    chosen, used = _fill_budget(scored[:limit], budget_tokens)
    scoring_ms = (time.perf_counter() - scoring_started) * 1000
    total_ms = (time.perf_counter() - total_started) * 1000
    return Explain(
        chosen=chosen,
        used_tokens=used,
        dropped_trust=dropped_trust,
        dropped_validity=dropped_validity,
        dropped_filter=dropped_filter,
        dropped_relevance=dropped_relevance,
        policy_id=policy.id,
        embed_ms=embed_ms,
        timings={
            "embed_ms": embed_ms,
            "dense_ms": dense_ms,
            "lexical_ms": lexical_ms,
            "entity_ms": entity_ms,
            "fetch_ms": fetch_ms,
            "scoring_ms": scoring_ms,
            "total_ms": total_ms,
        },
    )


def search(*args: Any, **kwargs: Any) -> tuple[list[Scored], int]:
    result = explain(*args, **kwargs)
    return result.chosen, result.used_tokens
