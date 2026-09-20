"""Select facts and original user passages under one context budget.

Raw vector hits are only IDs: text, ownership and role are reloaded from Postgres
before semantic provider egress. Passages remain quotations, never promoted facts.
No new storage or generated summaries are introduced.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

import psycopg
from qdrant_client import QdrantClient

from . import retrieval, store
from .db import iso
from .retrieval import Scored

MAX_PASSAGE_CHARS = 1200
MAX_CANDIDATES = 60


def pack_context(
    baseline: retrieval.Explain,
    raw: list[dict[str, Any]] | None,
    excerpts: dict[str, list[dict[str, Any]]],
    *,
    budget_tokens: int,
    limit: int,
) -> tuple[retrieval.Explain, list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Enforce one context budget, independent of optional model selection.

    Facts and historical quotations alternate so either representation can
    contribute. Supplemental citations spend only the remaining allowance.
    Text is never truncated into a quotation that changes its meaning.
    """
    facts, passages_out, sources = [], [], {}
    used = 0
    raw = raw or []
    for index in range(max(len(baseline.chosen), len(raw))):
        for rows, target in ((baseline.chosen, facts), (raw, passages_out)):
            if index >= len(rows) or len(facts) + len(passages_out) >= limit:
                continue
            row = rows[index]
            text = row.text if isinstance(row, Scored) else str(row["text"])
            cost = retrieval._token_count(text) + 6
            if used + cost <= budget_tokens:
                target.append(row)
                used += cost
    for row in facts:
        sources[row.id] = []
        for source in excerpts.get(row.id, []):
            cost = retrieval._token_count(str(source["excerpt"])) + 6
            if used + cost <= budget_tokens:
                sources[row.id].append(source)
                used += cost
    return replace(baseline, chosen=facts, used_tokens=used), passages_out, sources


def passages(text: str) -> list[tuple[int, int]]:
    """Bounded verbatim passages; prefer paragraph/sentence ends, never truncate a quote."""
    spans, start = [], 0
    while start < len(text) and len(spans) < 8:
        end = min(len(text), start + MAX_PASSAGE_CHARS)
        if end < len(text):
            boundaries = list(re.finditer(r"(?:\n\s*\n|[.!?]\s+)", text[start:end]))
            if boundaries:
                end = start + boundaries[-1].end()
            else:
                # Preserve a long sentence as one unit when possible: cutting at
                # an arbitrary character can detach its exception or negation.
                match = re.search(r"(?:\n\s*\n|[.!?]\s+)", text[end : start + 2400])
                if match:
                    end += match.end()
                else:
                    break
        if text[start:end].strip():
            spans.append((start, end))
        start = end
    return spans


def raw_candidates(
    conn: psycopg.Connection,
    client: QdrantClient,
    *,
    vector: list[float],
    scope_ids: Sequence[str],
    expression: dict[str, Any] | None = None,
    kinds: list[str] | None = None,
) -> tuple[list[Scored], dict[str, dict[str, Any]]]:
    rows = store.raw_search_rows(
        conn,
        client,
        vector=vector,
        scope_ids=scope_ids,
        limit=MAX_CANDIDATES,
        expression=expression,
        kinds=kinds,
    )
    candidates, references = [], {}
    # Round-robin passages prevents one long turn from filling the candidate cap.
    grouped = []
    for row in rows:
        text = str(row["content"])
        grouped.append((row, text, passages(text)))
    for position in range(8):
        for row, text, spans in grouped:
            if position >= len(spans) or len(candidates) >= MAX_CANDIDATES:
                continue
            start, end = spans[position]
            mid = int(row["id"])
            key = f"raw:{mid}:{start}:{end}"
            excerpt = text[start:end]
            references[key] = {
                "message_id": mid,
                "text": excerpt,
                "start_char": start,
                "end_char": end,
                "source_role": "user",
                "scope": row["scope_name"],
                "session_id": row["session_id"],
                "created_at": iso(row["created_at"]),
                "context": dict(row["context"] or {}),
                "similarity": max(0.0, float(row["similarity"])),
            }
            candidates.append(
                Scored(
                    id=key,
                    text=excerpt,
                    kind="evidence",
                    context=dict(row["context"] or {}),
                    tags=[],
                    source_role="user",
                    similarity=max(0.0, float(row["similarity"])),
                    lexical=0,
                    entity=0,
                    importance=0,
                    recency=0,
                    score=max(0.0, float(row["similarity"])),
                    updated_at=iso(row["created_at"]) or "",
                    scope=str(row["scope_name"]),
                    scope_slug=str(row["scope_slug"]),
                    review_status="pending",
                )
            )
    return candidates, references


def assemble(
    conn: psycopg.Connection,
    client: QdrantClient,
    baseline: retrieval.Explain,
    *,
    query: str,
    scope_ids: Sequence[str],
    budget_tokens: int,
    limit: int,
    select: Callable[[str, list[Scored]], list[Scored]],
    expression: dict[str, Any] | None = None,
    kinds: list[str] | None = None,
) -> tuple[retrieval.Explain, list[dict[str, Any]]]:
    raw, references = raw_candidates(
        conn,
        client,
        vector=baseline.query_vector or [],
        scope_ids=scope_ids,
        expression=expression,
        kinds=kinds,
    )
    # Alternate candidate arms instead of comparing cosine and hybrid scores
    # as if they had the same scale. Unused quota transfers to the other arm.
    combined = []
    for i in range(MAX_CANDIDATES):
        for rows in (baseline.chosen, raw):
            if i < len(rows) and len(combined) < MAX_CANDIDATES:
                combined.append(rows[i])
    ranked = select(query, combined)
    facts, evidence, used = [], [], 0
    for row in ranked:
        if len(facts) + len(evidence) >= limit:
            break
        cost = retrieval._token_count(row.text) + 6
        if used + cost > budget_tokens:
            continue
        used += cost
        if row.id in references:
            evidence.append(references[row.id])
        else:
            facts.append(row)
    return replace(baseline, chosen=facts, used_tokens=used), evidence
