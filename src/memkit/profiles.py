"""The profile block an agent receives at the start of a session.

One SQL query per block, each bounded, because this runs on every session start
and its cost is paid before the user has typed anything.

The blocks answer different questions, which is why they are separate rather
than one ranked list:

    about        who the user is: identity and contact facts
    style        how they like to work with an agent
    team         rules everyone on the team shares
    project      what is true about the workspace this session is in
    recent       what has changed lately, across everything they can see

Splitting them also fixes a failure the single stable/dynamic split had: the
stable half was selected by `kind`, and identity facts fell outside the
configured kinds, so a user's name and role dropped out of context entirely
once they were older than the dynamic window.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import psycopg

from .db import Row, iso, utcnow
from .retrieval import DEFAULT_TRUST, _token_count
from .store import memory_active

# Kinds the extractor actually writes; see the prompt's taxonomy rule.
IDENTITY_KINDS = ("fact",)
STYLE_KINDS = ("preference",)

BLOCKS = ("about", "style", "team", "project", "recent")

# Share of the token budget each block may use before the rest spills forward.
# Identity is small and cheap; style is the largest because it is what changes
# an agent's behaviour most; recent gets what is left.
BUDGET_SHARE = {"about": 0.20, "style": 0.35, "team": 0.20, "project": 0.20, "recent": 0.05}


def _rows(
    conn: psycopg.Connection,
    *,
    scope_ids: Sequence[str],
    kinds: Sequence[str] | None = None,
    subject_id: str | None = None,
    unattributed: bool = False,
    exclude_kinds: Sequence[str] | None = None,
    since: Any = None,
    include_untrusted: bool,
    limit: int = 60,
) -> list[Row]:
    """Candidate memories for one block, ordered by importance then recency.

    Bounded by LIMIT rather than by reading the scope and filtering in Python:
    a profile render is on the hot path and the store grows without bound.
    """
    if not scope_ids:
        return []
    trust = None if include_untrusted else sorted(DEFAULT_TRUST)
    return list(
        conn.execute(
            """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                      sub.name AS subject_name
                 FROM memories m
                 JOIN entities sc ON sc.id = m.scope_id
                 LEFT JOIN entities sub ON sub.id = m.subject_id
                WHERE m.scope_id = ANY(%(scopes)s)
                  AND m.status = 'active'
                  AND (m.valid_until IS NULL OR m.valid_until > now())
                  AND (%(kinds)s::text[] IS NULL OR m.kind = ANY(%(kinds)s))
                  AND (%(exclude)s::text[] IS NULL OR NOT (m.kind = ANY(%(exclude)s)))
                  AND (%(subject)s::uuid IS NULL OR m.subject_id = %(subject)s)
                  AND (NOT %(unattributed)s OR m.subject_id IS NULL)
                  AND (%(since)s::timestamptz IS NULL OR m.updated_at >= %(since)s)
                  AND (%(trust)s::text[] IS NULL OR m.source_role = ANY(%(trust)s))
                ORDER BY m.importance DESC, m.updated_at DESC, m.id
                LIMIT %(limit)s""",
            {
                "scopes": [uuid.UUID(str(s)) for s in scope_ids],
                "kinds": list(kinds) if kinds else None,
                "exclude": list(exclude_kinds) if exclude_kinds else None,
                "subject": subject_id,
                "unattributed": unattributed,
                "since": since,
                "trust": trust,
                "limit": limit,
            },
        )
    )


def _item(row: Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "text": row["text"],
        "kind": row["kind"],
        "source_role": row["source_role"],
        "review_status": row["review_status"],
        "scope": row["scope_name"],
        "subject": row["subject_name"],
        "updated_at": iso(row["updated_at"]),
    }


def render(
    conn: psycopg.Connection,
    *,
    own_scope_id: str,
    team_scope_id: str | None = None,
    allowed_scope_ids: Sequence[str] = (),
    project_scope_id: str | None = None,
    own_subject_id: str | None = None,
    dynamic_days: int = 30,
    budget_tokens: int = 800,
    blocks: Sequence[str] = BLOCKS,
    include_untrusted: bool = False,
) -> dict[str, Any]:
    """Assemble the blocks, spending the token budget in block order.

    Unspent budget rolls forward, so a user with no team rules gets a longer
    style block rather than a shorter profile.
    """
    requested = [block for block in blocks if block in BLOCKS]
    now = utcnow()
    cutoff = now - timedelta(days=dynamic_days)
    seen: set[str] = set()
    result: dict[str, list[dict[str, Any]]] = {block: [] for block in requested}
    used = 0
    remaining = budget_tokens

    for index, block in enumerate(requested):
        if block == "about":
            rows = _rows(
                conn,
                scope_ids=[own_scope_id],
                kinds=IDENTITY_KINDS,
                include_untrusted=include_untrusted,
            )
        elif block == "style":
            rows = _rows(
                conn,
                scope_ids=[own_scope_id],
                kinds=STYLE_KINDS,
                include_untrusted=include_untrusted,
            )
        elif block == "team":
            rows = (
                _rows(
                    conn,
                    scope_ids=[team_scope_id],
                    unattributed=True,
                    include_untrusted=include_untrusted,
                )
                if team_scope_id
                else []
            )
        elif block == "project":
            rows = (
                _rows(
                    conn,
                    scope_ids=[project_scope_id],
                    include_untrusted=include_untrusted,
                )
                if project_scope_id
                else []
            )
        else:  # recent
            rows = _rows(
                conn,
                scope_ids=list(allowed_scope_ids) or [own_scope_id],
                exclude_kinds=IDENTITY_KINDS + STYLE_KINDS,
                since=cutoff,
                include_untrusted=include_untrusted,
            )

        # The last block may use everything left; earlier ones keep to their
        # share so a long style list cannot crowd out the project block.
        is_last = index == len(requested) - 1
        allowance = remaining if is_last else int(budget_tokens * BUDGET_SHARE.get(block, 0.2))
        spent = 0
        for row in rows:
            memory_id = str(row["id"])
            if memory_id in seen or not memory_active(row, now=now):
                continue
            cost = _token_count(str(row["text"]))
            if spent + cost > allowance or cost > remaining:
                continue
            result[block].append(_item(row))
            seen.add(memory_id)
            spent += cost
            used += cost
            remaining -= cost
    return {
        "blocks": result,
        "used_tokens": used,
        "budget_tokens": budget_tokens,
        "generated_at": iso(now),
        "policy_id": "profile-v2",
    }
