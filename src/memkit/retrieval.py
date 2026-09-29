"""Trust-aware hybrid retrieval with an explicit abstention policy.

Three candidate arms, fused and then filtered. Every arm is bounded, and every
arm is scope-filtered: a query can only ever reach memories in the scopes its
principal belongs to. Lexical matching uses Postgres full text with the
`russian` configuration, which stems Cyrillic and ASCII alike -- the SQLite
FTS5 tokenizer had no stemming at all, so this arm used to be blind to Russian
morphology.
"""

from __future__ import annotations

import functools
import math
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import psycopg
from qdrant_client import QdrantClient

from . import eligibility, filters, temporal, vectors
from .db import Row, as_datetime, iso
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
    # Policy v2 signals (decisions/0077). Every one defaults to off, so a v1
    # policy ranks exactly as it did before they existed.
    #
    # Episodes age from when they happened, faster than facts, unless marked
    # significant: last Tuesday's lunch should fade, a wedding should not.
    episode_half_life_days: float = 0.0
    episode_significance: float = 1.0
    # A query naming a time ("last month", "в марте") boosts memories whose
    # event -- or, lacking one, whose saying -- falls inside it.
    temporal_weight: float = 0.0
    # "first"/"latest" questions prefer the earliest/newest matching claim.
    order_weight: float = 0.0
    # Independent mentions: a preference restated across sessions outranks one
    # said once. Saturates at eight mentions.
    reinforcement_weight: float = 0.0
    # A derived claim nobody has confirmed ranks below stated ones.
    inference_penalty: float = 0.0


def load_policy(conn: psycopg.Connection, policy_id: str) -> RetrievalPolicy:
    aliases = {"neutral-v1": "core-retrieval-neutral-v1", "temporal-v2": "core-retrieval-v2"}
    resolved = aliases.get(policy_id, policy_id)
    row = conn.execute(
        "SELECT id,config FROM policies WHERE id=%s AND kind='retrieval'", (resolved,)
    ).fetchone()
    if row is None:
        raise ValueError("unknown retrieval policy")
    config = dict(row["config"])
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
        episode_half_life_days=float(config.get("episode_half_life_days", 0.0)),
        episode_significance=float(config.get("episode_significance", 1.0)),
        temporal_weight=float(config.get("temporal_weight", 0.0)),
        order_weight=float(config.get("order_weight", 0.0)),
        reinforcement_weight=float(config.get("reinforcement_weight", 0.0)),
        inference_penalty=float(config.get("inference_penalty", 0.0)),
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
    # Where the fact lives and who it is about. A team instance returns facts
    # from several scopes in one result, so a caller that cannot tell them
    # apart cannot say "the team decided" versus "you decided".
    review_status: str = "confirmed"
    scope: str | None = None
    scope_slug: str | None = None
    subject: str | None = None
    subject_slug: str | None = None
    # When it was said and when it happened; see temporal.py.
    document_date: str | None = None
    event_dates: list[str] = field(default_factory=list)
    source_count: int = 1
    is_static: bool = False
    # The time-window/order contribution to `score`, for explanation.
    temporal: float = 0.0

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
            "review_status": self.review_status,
            "scope": self.scope,
            "scope_slug": self.scope_slug,
            "subject": self.subject,
            "subject_slug": self.subject_slug,
            "score": round(self.score, 4),
            "similarity": round(self.similarity, 4),
            "lexical": round(self.lexical, 4),
            "entity": round(self.entity, 4),
            "importance": round(self.importance, 3),
            "recency": round(self.recency, 4),
            "updated_at": self.updated_at,
            "document_date": self.document_date,
            "event_dates": list(self.event_dates),
            "source_count": self.source_count,
            "is_static": self.is_static,
            "temporal": round(self.temporal, 4),
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
    # The query vector, so a caller that also searches raw turns does not pay to
    # embed the same string twice. Excluded from as_dict: it is 1024 floats of
    # internal detail, not part of the API response.
    query_vector: list[float] | None = None
    # What the query said about time, when it said anything.
    intent: temporal.TemporalIntent | None = None

    def temporal_dict(self) -> dict[str, Any] | None:
        if self.intent is None or not self.intent.active:
            return None
        return {
            "window": self.intent.window.as_dict() if self.intent.window else None,
            "order": self.intent.order,
            "asks_time": self.intent.asks_time,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "temporal": self.temporal_dict(),
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


def _lexical_candidates(
    conn: psycopg.Connection,
    *,
    query: str,
    scope_ids: Sequence[str],
    limit: int,
    criteria: tuple[str, list] | None = None,
) -> dict[str, float]:
    """A bounded, normalised full-text candidate set.

    Terms come from ``WORD_RE`` and each becomes its own `plainto_tsquery`,
    OR'd together, so caller input is never interpreted as query syntax and a
    memory matching some of the words still surfaces. Passing the whole query
    to one `plainto_tsquery` would AND every term, which is the wrong trade in
    a hybrid ranker: the dense arm supplies precision, and this arm exists for
    the exact word the embedding rounded away.

    `ts_rank_cd` is higher-is-better and unbounded, so scores are normalised by
    the best hit: that keeps this arm comparable with the dense arm's cosine
    without pushing an equally relevant second result below the floor.
    """
    terms = list(dict.fromkeys(_terms(query)))[:32]
    if not terms or not scope_ids:
        return {}
    # One placeholder per term, OR'd with tsquery's `||`.
    tsquery = " || ".join(["plainto_tsquery('russian', %s)"] * len(terms))
    predicate, parameters = criteria or ("TRUE", [])
    rows = conn.execute(
        f"""WITH q AS (SELECT {tsquery} AS query)
            SELECT m.id, ts_rank_cd(m.search_tsv, q.query) AS rank
              FROM memories m, q
             WHERE m.scope_id = ANY(%s) AND m.status='active'
               AND ({predicate})
               AND m.search_tsv @@ q.query
             ORDER BY rank DESC, m.id
             LIMIT %s""",
        (*terms, [uuid.UUID(str(scope)) for scope in scope_ids], *parameters, limit),
    ).fetchall()
    if not rows:
        return {}
    ranks = [float(row["rank"]) for row in rows]
    best = max(ranks, default=1.0) or 1.0
    return {str(row["id"]): rank / best for row, rank in zip(rows, ranks, strict=True)}


def _entity_candidates(
    conn: psycopg.Connection,
    *,
    query: str,
    scope_ids: Sequence[str],
    limit: int,
    criteria: tuple[str, list] | None = None,
) -> dict[str, float]:
    """Exact identifier matches: ticket numbers, error codes, repo names.

    Stemming is the wrong tool for these -- `ERR_X91Q` has no lexeme -- so this
    arm matches the literal substring against the folded column with the
    trigram index, which is also what makes it independent of the lexical arm
    rather than a subset of it, as it was under a shared FTS table.

    `_` and `%` are escaped. They are LIKE wildcards, and `WORD_RE` admits an
    underscore, so the arm whose whole purpose is exactness was matching
    `ERRXX91Q` for `ERR_X91Q`.
    """
    tokens = list(
        dict.fromkeys(
            token
            for token in WORD_RE.findall(query)
            if any(char.isdigit() or char in "./:@#_-" for char in token)
            or (len(token) > 1 and token.isupper())
        )
    )[:16]
    if not tokens or not scope_ids:
        return {}
    patterns = [
        "%" + token.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        for token in tokens
    ]
    predicate, parameters = criteria or ("TRUE", [])
    rows = conn.execute(
        f"""SELECT m.id FROM memories m
            WHERE m.scope_id = ANY(%s) AND m.status='active'
              AND ({predicate})
              AND m.text_folded LIKE ANY(%s)
            ORDER BY m.updated_at DESC, m.id
            LIMIT %s""",
        ([uuid.UUID(str(scope)) for scope in scope_ids], *parameters, patterns, limit),
    ).fetchall()
    return {str(row["id"]): 1.0 for row in rows}


def _candidate_rows(
    conn: psycopg.Connection, *, scope_ids: Sequence[str], candidate_ids: set[str]
) -> dict[str, Row]:
    """Fetch the candidates, re-checking the scope predicate.

    The dense arm's filter lives in Qdrant, which is a derived index and can
    lag. Re-applying the predicate here means a stale point can never leak a
    memory from a scope the caller has lost access to.
    """
    if not candidate_ids or not scope_ids:
        return {}
    rows = conn.execute(
        """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                  sub.name AS subject_name, sub.slug AS subject_slug
             FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
             LEFT JOIN entities sub ON sub.id = m.subject_id
            WHERE m.id = ANY(%s) AND m.scope_id = ANY(%s)""",
        (
            [uuid.UUID(str(cid)) for cid in sorted(candidate_ids)],
            [uuid.UUID(str(s)) for s in scope_ids],
        ),
    ).fetchall()
    return {str(row["id"]): row for row in rows}


def _age_days(value: Any, now: datetime) -> float:
    parsed = as_datetime(value)
    if parsed is None:
        return 0.0
    return max(0.0, (now - parsed).total_seconds() / 86_400)


@functools.lru_cache(maxsize=1)
def _encoding() -> Any:
    """The tokenizer, or None when it cannot be loaded.

    tiktoken fetches its vocabulary over the network on first use. A deployment
    without egress to that host used to fail every search with a proxy error
    rather than fall back, because only ImportError and ValueError were caught.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def _token_count(text: str) -> int:
    encoding = _encoding()
    if encoding is not None:
        return len(encoding.encode(text))
    # Conservative Unicode-aware fallback; unlike len/3 it counts words,
    # punctuation and non-Latin text independently.
    return max(1, len(re.findall(r"\w+|[^\w\s]", text, re.UNICODE)))


def _fill_budget(
    rows: list[Scored], budget_tokens: int, limit: int | None = None
) -> tuple[list[Scored], int]:
    chosen: list[Scored] = []
    used = 0
    for row in rows:
        if limit is not None and len(chosen) >= limit:
            break
        cost = _token_count(row.text)
        if used + cost > budget_tokens:
            continue
        chosen.append(row)
        used += cost
    return chosen, used


def _reinforcement(source_count: int) -> float:
    """0 for one mention, 1 at eight; logarithmic so repetition saturates."""
    return min(1.0, math.log2(max(1, source_count)) / 3.0)


def _when(row: Row) -> tuple[datetime | None, datetime | None]:
    """The interval a memory is about: its events, or the day it was said."""
    start = as_datetime(row.get("event_start"))
    end = as_datetime(row.get("event_end"))
    if start is not None or end is not None:
        return start, end
    said = as_datetime(row.get("document_date"))
    return said, said


def _recency(row: Row, now: datetime, policy: RetrievalPolicy) -> float:
    """Exponential decay; episodes age from their event, and faster.

    Facts age from their last update, as they always have. An episode's
    relevance is tied to when it happened, not when it was last touched, so
    a correction next week does not make last year's trip recent again.
    """
    if (
        row["kind"] == "episode"
        and policy.episode_half_life_days > 0
        and float(row["importance"]) < policy.episode_significance
    ):
        start, end = _when(row)
        anchor = end or start or row["updated_at"]
        return math.exp(-_age_days(anchor, now) / policy.episode_half_life_days)
    return math.exp(-_age_days(row["updated_at"], now) / policy.default_half_life_days)


def _in_range(row: Row, time_range: tuple[datetime | None, datetime | None] | None) -> bool:
    if time_range is None:
        return True
    since, until = time_range
    start, end = _when(row)
    if start is None and end is None:
        return False
    if since is not None and (end or start) < since:
        return False
    return not (until is not None and (start or end) > until)


def _apply_order(scored: list[Scored], rows: dict[str, Row], order: str, weight: float) -> None:
    """Nudge the earliest or the newest relevant claim to the top.

    Normalised over the candidates that survived the relevance floor, so it
    orders among relevant answers and cannot promote an irrelevant one.
    """
    moments: dict[str, float] = {}
    for item in scored:
        start, end = _when(rows[item.id])
        anchor = start if order == "earliest" else (end or start)
        if anchor is not None:
            moments[item.id] = anchor.timestamp()
    if len(moments) < 2:
        return
    low, high = min(moments.values()), max(moments.values())
    if high <= low:
        return
    for item in scored:
        if item.id not in moments:
            continue
        position = (moments[item.id] - low) / (high - low)
        bonus = weight * (position if order == "latest" else 1.0 - position)
        item.score += bonus
        item.temporal += bonus


def explain(
    conn: psycopg.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    query: str,
    scope_ids: Sequence[str],
    expression: dict[str, Any] | None = None,
    kinds: list[str] | None = None,
    limit: int = 30,
    budget_tokens: int = 800,
    policy: RetrievalPolicy | None = None,
    include_untrusted: bool = False,
    reranker: Reranker | None = None,
    now: datetime | None = None,
    memory_collection: str = vectors.MEMORIES,
    as_of: datetime | None = None,
    time_range: tuple[datetime | None, datetime | None] | None = None,
) -> Explain:
    """Rank the caller's memories for `query`.

    `as_of` is the moment the question is asked, which relative phrases in it
    resolve against; it defaults to now and differs for a benchmark or a
    replayed conversation. `time_range` is a hard filter on when a memory's
    event happened -- or, without one, when it was said.
    """
    total_started = time.perf_counter()
    filters.validate(expression)
    policy = policy or RetrievalPolicy()
    now = now or datetime.now(UTC)
    intent = (
        temporal.parse_intent(query, now=as_of or now)
        if policy.temporal_weight or policy.order_weight
        else None
    )
    allowed_roles = None if include_untrusted else policy.allowed_source_roles
    criteria = eligibility.memory_sql(
        expression=expression, kinds=kinds, allowed_roles=allowed_roles, now=now
    )
    embed_started = time.perf_counter()
    dense_vector = embedder.encode_one(query)
    embed_ms = (time.perf_counter() - embed_started) * 1000
    dense_started = time.perf_counter()
    candidate_limit = max(50, limit * 3)
    dense_hits, seen = [], set()
    must = [
        vectors.keyword("scope_id", list(scope_ids)),
        vectors.keyword("status", "active"),
        *eligibility.memory_vectors(
            expression=expression, kinds=kinds, allowed_roles=allowed_roles, now=now
        ),
    ]
    eligible_count = 0
    # Derived payloads may lag, and complex JSON predicates cannot be exactly
    # expressed by Qdrant. Refill after the authoritative check, with a fixed
    # ceiling so pathological filters cannot cause an unbounded index scan.
    for _ in range(4):
        hits = vectors.search(
            client,
            memory_collection,
            dense_vector,
            limit=candidate_limit,
            must=must,
            exclude_ids=list(seen) or None,
        )
        fresh = [hit for hit in hits if str(hit.id) not in seen]
        if not fresh:
            break
        seen.update(str(hit.id) for hit in fresh)
        dense_hits.extend(fresh)
        rows = _candidate_rows(conn, scope_ids=scope_ids, candidate_ids={str(h.id) for h in fresh})
        eligible_count += sum(
            memory_active(row, now=now)
            and (allowed_roles is None or row["source_role"] in allowed_roles)
            and (not kinds or row["kind"] in kinds)
            and filters.matches(eligibility.document(row), expression)
            for row in rows.values()
        )
        if len(hits) < candidate_limit or eligible_count >= candidate_limit:
            break
    dense_ms = (time.perf_counter() - dense_started) * 1000
    dense = {str(hit.id): max(0.0, float(hit.score)) for hit in dense_hits}
    lexical_started = time.perf_counter()
    lexical = _lexical_candidates(
        conn, query=query, scope_ids=scope_ids, limit=candidate_limit, criteria=criteria
    )
    lexical_ms = (time.perf_counter() - lexical_started) * 1000
    entity_started = time.perf_counter()
    entity = _entity_candidates(
        conn, query=query, scope_ids=scope_ids, limit=candidate_limit, criteria=criteria
    )
    entity_ms = (time.perf_counter() - entity_started) * 1000
    candidate_ids = set(dense) | set(lexical) | set(entity)
    fetch_started = time.perf_counter()
    row_by_id = _candidate_rows(conn, scope_ids=scope_ids, candidate_ids=candidate_ids)
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
        context = dict(row["context"] or {})
        tags = list(row["tags"] or [])
        document = eligibility.document(row)
        if not filters.matches(document, expression) or not _in_range(row, time_range):
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
        recency = _recency(row, now, policy)
        boost = 0.0
        if intent is not None and intent.window is not None and policy.temporal_weight:
            start, end = _when(row)
            if intent.window.overlaps(start, end):
                boost += policy.temporal_weight
        score = (
            relevance
            + policy.importance_weight * float(row["importance"])
            + policy.recency_weight * recency
            + policy.reinforcement_weight * _reinforcement(int(row.get("source_count") or 1))
            + boost
        )
        if row["source_role"] == "inference" and row["review_status"] != "confirmed":
            score -= policy.inference_penalty
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
                updated_at=iso(row["updated_at"]) or "",
                revision=int(row["revision"]),
                review_status=str(row["review_status"]),
                scope=str(row["scope_name"]),
                scope_slug=str(row["scope_slug"]),
                subject=str(row["subject_name"]) if row["subject_name"] else None,
                subject_slug=str(row["subject_slug"]) if row["subject_slug"] else None,
                document_date=iso(row.get("document_date")),
                event_dates=list(row.get("event_dates") or []),
                source_count=int(row.get("source_count") or 1),
                is_static=bool(row.get("is_static", False)),
                temporal=boost,
            )
        )
    if intent is not None and intent.order and policy.order_weight and len(scored) > 1:
        _apply_order(scored, row_by_id, intent.order, policy.order_weight)
    scored.sort(key=lambda item: (-item.score, item.id))
    scored = (reranker or IdentityReranker()).rerank(query, scored)
    chosen, used = _fill_budget(scored, budget_tokens, limit=limit)
    scoring_ms = (time.perf_counter() - scoring_started) * 1000
    total_ms = (time.perf_counter() - total_started) * 1000
    return Explain(
        chosen=chosen,
        used_tokens=used,
        query_vector=dense_vector,
        intent=intent,
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


# Reciprocal-rank-fusion constant. 60 is the value the method was published
# with; it keeps one list's top hit from drowning agreement between the others.
RRF_K = 60


def fuse(results: Sequence[Explain], *, budget_tokens: int, limit: int | None = None) -> Explain:
    """Merge rankings for one question asked several ways (decisions/0079).

    Each memory scores the sum of 1/(k + rank) over the lists that returned it,
    so a memory found by the original query and by two rewrites outranks one
    found by a single rewrite, whatever its raw score was. The first result is
    the original query's: its drop lists, intent and vector describe the
    request the caller made.
    """
    if not results:
        raise ValueError("nothing to fuse")
    primary = results[0]
    fused: dict[str, float] = {}
    best: dict[str, Scored] = {}
    for result in results:
        for rank, item in enumerate(result.chosen):
            fused[item.id] = fused.get(item.id, 0.0) + 1.0 / (RRF_K + rank + 1)
            if item.id not in best or item.score > best[item.id].score:
                best[item.id] = item
    ordered = sorted(best.values(), key=lambda item: (-fused[item.id], -item.score, item.id))
    chosen, used = _fill_budget(ordered, budget_tokens, limit=limit)
    timings = dict(primary.timings)
    timings["fused_queries"] = float(len(results))
    return Explain(
        chosen=chosen,
        used_tokens=used,
        dropped_trust=primary.dropped_trust,
        dropped_validity=primary.dropped_validity,
        dropped_filter=primary.dropped_filter,
        dropped_relevance=[i for i in primary.dropped_relevance if i not in best],
        policy_id=primary.policy_id,
        embed_ms=sum(result.embed_ms for result in results),
        timings=timings,
        query_vector=primary.query_vector,
        intent=primary.intent,
    )
