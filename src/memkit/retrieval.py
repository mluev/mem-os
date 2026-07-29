"""The read path: rank, filter, dedup, fill a token budget.

docs/05-retrieval.md calls this the hardest part, and it is right. Writing a fact
is easy; getting the right one out of ten thousand is not. Cosine similarity
alone cannot know that a fact is stale, that it is unimportant, or that it
belongs to a different project.

Three things here differ from the doc:

* `scope_key` and `task_key` are function arguments. The doc requires dropping
  facts whose project does not match the current one, but the request body it
  specifies carries nothing to compare against, so the rule was unimplementable.
* Non-matching project/task facts are excluded **in the Qdrant filter**, not
  given a large negative score. The doc says as much ("they should be filtered
  out at the Qdrant level, before any ranking") and it matters: a down-weighted
  fact still consumes one of the top-50 slots.
* Dedup asks Qdrant for vectors. The doc says "the vectors are already in memory
  after the search" — they are not, unless `with_vectors=True` is passed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient, models

from . import vectors
from .embed import Embedder

# Starting weights from docs/05-retrieval.md. Turn these only on the strength of
# the eval, never on how they feel.
W_SIMILARITY = 0.55
W_IMPORTANCE = 0.20
W_RECENCY = 0.15
W_SCOPE = 0.10

# Forgetting half-lives in days, per fact type. The spread is the point:
# "lives in Tashkent" is still true in a year; "fixing bug #14 today" is rubbish
# within two days.
TAU: dict[str, float] = {
    "preference": 540.0,
    "fact": 900.0,
    "skill": 270.0,
    "relation": 270.0,
    "project": 180.0,
    "decision": 180.0,
    "task": 2.0,
}
TAU_DEFAULT = 180.0

# Overfetch before reranking. Reranking is cheap, and the wider pool rescues the
# fact that placed fiftieth on cosine but first on importance.
OVERFETCH = 50

# Greedy read-path dedup threshold.
DEDUP_COSINE = 0.90

# Rough token estimate. char/3 rather than char/4 because Cyrillic tokenizes
# denser than English.
CHARS_PER_TOKEN = 3


@dataclass
class Scored:
    id: str
    text: str
    type: str | None
    scope: str
    scope_key: str | None
    similarity: float
    importance: float
    recency: float
    scope_boost: float
    score: float
    age_days: int
    updated_at: str
    task_status: str | None = None
    vector: list[float] | None = None

    def as_dict(self) -> dict[str, Any]:
        # similarity and score are both returned so the formula can be debugged
        # by eye, which is the only way the weights ever get tuned honestly.
        result = {
            "id": self.id,
            "text": self.text,
            "type": self.type,
            "scope": self.scope,
            "scope_key": self.scope_key,
            "score": round(self.score, 4),
            "similarity": round(self.similarity, 4),
            "importance": round(self.importance, 3),
            "recency": round(self.recency, 4),
            "scope_boost": self.scope_boost,
            "age_days": self.age_days,
            "updated_at": self.updated_at,
        }
        if self.type == "task":
            result["task_status"] = self.task_status or "unknown"
        return result


@dataclass
class Explain:
    chosen: list[Scored]
    used_tokens: int
    dropped_scope: list[dict[str, Any]]
    dropped_dedup: list[dict[str, Any]]
    dropped_budget: list[dict[str, Any]]
    embed_ms: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "memories": [item.as_dict() for item in self.chosen],
            "used_tokens": self.used_tokens,
            "dropped_scope": self.dropped_scope,
            "dropped_dedup": self.dropped_dedup,
            "dropped_budget": self.dropped_budget,
            "weights": {
                "similarity": W_SIMILARITY,
                "importance": W_IMPORTANCE,
                "recency": W_RECENCY,
                "scope": W_SCOPE,
            },
            "tau": TAU,
            "dedup_cosine": DEDUP_COSINE,
            "embed_ms": round(self.embed_ms, 1),
        }


def age_days(updated_at: str, now: datetime | None = None) -> int:
    """Days since the fact was last confirmed.

    Measured from `updated_at`, never `created_at`: a fact restated yesterday is
    fresh even if it was first recorded two years ago.
    """
    now = now or datetime.now(UTC)
    if not updated_at:
        return 0
    try:
        when = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0, (now - when).days)


def recency(age: int, type_: str | None) -> float:
    tau = TAU.get(type_ or "", TAU_DEFAULT)
    return math.exp(-age / tau)


def scope_boost(
    scope: str, scope_key: str | None, *, project: str | None, task: str | None
) -> float | None:
    """Boost for scope match, or None when the fact must be discarded.

    None means "not merely less relevant, but wrong" -- a fact about another
    project has no business in this answer at any rank. In practice Qdrant has
    already excluded these; this is the second line of defence and the place the
    rule is stated in code.
    """
    if scope == "user":
        return 0.0
    if scope == "project":
        return 0.5 if (scope_key and scope_key == project) else None
    if scope == "task":
        return 1.0 if (scope_key and scope_key == task) else None
    return 0.0


def score_of(
    *, similarity: float, importance: float, recency_: float, boost: float
) -> float:
    return (
        W_SIMILARITY * similarity
        + W_IMPORTANCE * importance
        + W_RECENCY * recency_
        + W_SCOPE * boost
    )


def scope_filter(
    *, owner_id: str, project: str | None, task: str | None
) -> models.Filter:
    """Qdrant filter that admits user-scope facts plus only the matching keys.

    Structured as: owner and status must match, AND at least one of
    (scope=user) / (scope=project AND key=current) / (scope=task AND key=current).
    Without the should-clause a project fact from another repo reaches the
    reranker and pushes a relevant fact out of the pool.
    """
    should: list[models.Filter] = [
        models.Filter(must=[vectors.keyword("scope", "user")])
    ]
    if project:
        should.append(
            models.Filter(
                must=[
                    vectors.keyword("scope", "project"),
                    vectors.keyword("scope_key", project),
                ]
            )
        )
    if task:
        should.append(
            models.Filter(
                must=[
                    vectors.keyword("scope", "task"),
                    vectors.keyword("scope_key", task),
                ]
            )
        )
    return models.Filter(
        must=[
            vectors.keyword("owner_id", owner_id),
            vectors.keyword("status", "active"),
        ],
        should=should,
        min_should=models.MinShould(conditions=should, min_count=1),
    )


def rank(
    hits: list[Any],
    *,
    project: str | None,
    task: str | None,
    now: datetime | None = None,
) -> list[Scored]:
    """Rescore Qdrant hits and sort by the composite score."""
    now = now or datetime.now(UTC)
    out: list[Scored] = []
    for h in hits:
        payload = h.payload or {}
        scope = payload.get("scope") or "user"
        key = payload.get("scope_key")
        boost = scope_boost(scope, key, project=project, task=task)
        if boost is None:
            continue
        type_ = payload.get("type")
        updated = payload.get("updated_at") or ""
        age = age_days(updated, now)
        rec = recency(age, type_)
        imp = float(payload.get("importance") or 0.0)
        sim = float(h.score)
        out.append(
            Scored(
                id=str(h.id),
                text=payload.get("text", ""),
                type=type_,
                scope=scope,
                scope_key=key,
                similarity=sim,
                importance=imp,
                recency=rec,
                scope_boost=boost,
                score=score_of(
                    similarity=sim, importance=imp, recency_=rec, boost=boost
                ),
                age_days=age,
                updated_at=updated,
                task_status=payload.get("task_status"),
                vector=_dense(h),
            )
        )
    out.sort(key=lambda s: s.score, reverse=True)
    return out


def _dense(hit: Any) -> list[float] | None:
    vec = getattr(hit, "vector", None)
    if isinstance(vec, dict):
        return vec.get("dense")
    return vec


def _cosine(a: list[float], b: list[float]) -> float:
    # Vectors are L2-normalised at encode time, so the dot product is the cosine.
    return sum(x * y for x, y in zip(a, b, strict=False))


def dedup(ranked: list[Scored], threshold: float = DEDUP_COSINE) -> list[Scored]:
    """Greedy top-down dedup.

    Even with the nightly consolidator running, near-identical facts reach the
    result set -- 9 of 304 turns in this corpus are exact duplicates, so the
    facts drawn from them will be too. Keeps the highest-scoring member of each
    cluster because the list is already sorted.
    """
    kept, _ = dedup_explain(ranked, threshold)
    return kept


def dedup_explain(
    ranked: list[Scored], threshold: float = DEDUP_COSINE
) -> tuple[list[Scored], list[dict[str, Any]]]:
    """Deduplicate and report which higher-ranked item won each comparison."""
    kept: list[Scored] = []
    dropped: list[dict[str, Any]] = []
    for cand in ranked:
        if cand.vector is None:
            kept.append(cand)
            continue
        winner: Scored | None = None
        cosine = 0.0
        for current in kept:
            if current.vector is None:
                continue
            similarity = _cosine(cand.vector, current.vector)
            if similarity >= threshold:
                winner, cosine = current, similarity
                break
        if winner is None:
            kept.append(cand)
        else:
            dropped.append(
                {
                    "id": cand.id,
                    "text": cand.text,
                    "beaten_by": winner.id,
                    "cosine": round(cosine, 4),
                }
            )
    return kept, dropped


def fill_budget(
    ranked: list[Scored], budget_tokens: int
) -> tuple[list[Scored], int]:
    """Take facts by descending score until the budget is spent.

    A budget rather than a fixed limit because facts vary wildly in length and
    ten long ones would eat half the prompt. docs/05-retrieval.md puts the useful
    range at 600-1000 tokens and notes that less memory often beats more -- past
    that the model starts latching onto the irrelevant.
    """
    if budget_tokens <= 0:
        return list(ranked), sum(_tokens(s.text) for s in ranked)
    out: list[Scored] = []
    used = 0
    for s in ranked:
        cost = _tokens(s.text)
        if used + cost > budget_tokens:
            # Skip rather than stop: a single overlong fact should not truncate
            # everything cheaper behind it.
            continue
        out.append(s)
        used += cost
    return out, used


def _tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def search(
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    owner_id: str,
    project: str | None = None,
    task: str | None = None,
    types: list[str] | None = None,
    limit: int = 30,
    budget_tokens: int = 800,
    overfetch: int = OVERFETCH,
    now: datetime | None = None,
) -> tuple[list[Scored], int]:
    """Full read path. Returns (facts, tokens_used)."""
    result = explain(
        client,
        embedder,
        query=query,
        owner_id=owner_id,
        project=project,
        task=task,
        types=types,
        limit=limit,
        budget_tokens=budget_tokens,
        overfetch=overfetch,
        now=now,
    )
    return result.chosen, result.used_tokens


def explain(
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    owner_id: str,
    project: str | None = None,
    task: str | None = None,
    types: list[str] | None = None,
    limit: int = 30,
    budget_tokens: int = 800,
    overfetch: int = OVERFETCH,
    now: datetime | None = None,
    diagnostics: bool = False,
) -> Explain:
    """Run the production read path and expose each discard decision."""
    import time

    flt = scope_filter(owner_id=owner_id, project=project, task=task)
    if types:
        flt.must.append(vectors.keyword("type", types))

    started = time.perf_counter()
    vec = embedder.encode_one(query)
    embed_ms = (time.perf_counter() - started) * 1000
    hits = client.query_points(
        collection_name=vectors.MEMORIES,
        query=vec,
        using="dense",
        limit=max(overfetch, limit),
        query_filter=flt,
        with_payload=True,
        # Required for dedup below. Qdrant omits vectors unless asked, which is
        # the gap in docs/05-retrieval.md's dedup snippet.
        with_vectors=True,
    ).points

    dropped_scope: list[dict[str, Any]] = []
    if diagnostics:
        diagnostic_must = [
            vectors.keyword("owner_id", owner_id),
            vectors.keyword("status", "active"),
        ]
        if types:
            diagnostic_must.append(vectors.keyword("type", types))
        diagnostic_hits = client.query_points(
            collection_name=vectors.MEMORIES,
            query=vec,
            using="dense",
            limit=max(overfetch, limit),
            query_filter=models.Filter(must=diagnostic_must),
            with_payload=True,
            with_vectors=False,
        ).points
        for hit in diagnostic_hits:
            payload = hit.payload or {}
            scope = payload.get("scope") or "user"
            key = payload.get("scope_key")
            if scope_boost(scope, key, project=project, task=task) is None:
                dropped_scope.append(
                    {
                        "id": str(hit.id),
                        "text": payload.get("text", ""),
                        "scope": scope,
                        "scope_key": key,
                        "similarity": round(float(hit.score), 4),
                    }
                )

    from .config import get_settings

    ranked = rank(hits, project=project, task=task, now=now)
    threshold = get_settings().dedup_cosine
    kept, dropped_dedup = dedup_explain(ranked, threshold=threshold)
    candidates = kept[:limit]
    chosen, used = fill_budget(candidates, budget_tokens)
    chosen_ids = {item.id for item in chosen}
    dropped_budget = [
        {
            "id": item.id,
            "text": item.text,
            "estimated_tokens": _tokens(item.text),
        }
        for item in candidates
        if item.id not in chosen_ids
    ]
    return Explain(
        chosen=chosen,
        used_tokens=used,
        dropped_scope=dropped_scope,
        dropped_dedup=dropped_dedup,
        dropped_budget=dropped_budget,
        embed_ms=embed_ms,
    )
