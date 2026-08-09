"""Compact stable/dynamic profile rendering."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from .retrieval import DEFAULT_TRUST, _token_count
from .store import memory_active


def render(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    stable_kinds: list[str],
    dynamic_days: int,
    budget_tokens: int,
    include_untrusted: bool = False,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=dynamic_days)
    rows = conn.execute(
        """SELECT * FROM memories
            WHERE owner_id=? AND status='active'
            ORDER BY importance DESC,updated_at DESC,id""",
        (owner_id,),
    ).fetchall()
    stable: list[dict[str, Any]] = []
    dynamic: list[dict[str, Any]] = []
    used = 0
    for row in rows:
        if not memory_active(row, now=now):
            continue
        if not include_untrusted and row["source_role"] not in DEFAULT_TRUST:
            continue
        cost = _token_count(row["text"])
        if used + cost > budget_tokens:
            continue
        item = {
            "id": row["id"],
            "text": row["text"],
            "kind": row["kind"],
            "source_role": row["source_role"],
        }
        if row["kind"] in stable_kinds:
            stable.append(item)
        else:
            try:
                updated = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            if updated < cutoff:
                continue
            dynamic.append(item)
        used += cost
    return {
        "stable": stable,
        "dynamic": dynamic,
        "used_tokens": used,
        "generated_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "policy_id": "profile-v1",
    }
