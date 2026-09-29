"""Read-side expansion over the memory graph.

Search returns atomic claims. Two kinds of neighbour make an answer better and
are cheap to fetch once the claims are chosen:

    history   the claims a result replaced, with the dates they held. "Lives in
              Lisbon" answers "where do I live"; "lived in Porto until
              2026-04-02" answers "where did I live before".
    related   claims linked by `extends` or `derives`: the detail a result
              gained later, the fact it adds detail to, the premises of an
              inference.

Both are bounded per result, re-check every far end against the caller's
scopes (via `store.relations_for` / `store.history_of`), and never include a
memory that is not active except as history, where being superseded is the
point.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import psycopg

from . import store
from .db import Row, iso

# How a neighbour relates to the result it is attached to, from the result's
# point of view.
_OUTGOING = {"extends": "extends", "derives": "derived_from", "updates": "replaces"}
_INCOMING = {"extends": "extended_by", "derives": "premise_of", "updates": "replaced_by"}


def linked_view(row: Row, relation: str) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "text": row["text"],
        "kind": row["kind"],
        "relation": relation,
        "status": row["status"],
        "source_role": row["source_role"],
        "document_date": iso(row.get("document_date")),
        "event_dates": list(row.get("event_dates") or []),
        "valid_until": iso(row.get("valid_until")),
    }


def expand(
    conn: psycopg.Connection,
    memory_ids: Sequence[str],
    *,
    scope_ids: Sequence[str],
    include_history: bool,
    include_related: bool,
    per_memory: int = 3,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """History and related neighbours for each result id, newest first."""
    out: dict[str, dict[str, list[dict[str, Any]]]] = {
        memory_id: {"history": [], "related": []} for memory_id in memory_ids
    }
    if not memory_ids or not (include_history or include_related):
        return out
    if include_history:
        for memory_id in memory_ids:
            out[memory_id]["history"] = [
                linked_view(row, "replaces")
                for row in store.history_of(conn, memory_id, scope_ids=scope_ids, limit=per_memory)
            ]
    if include_related:
        edges = store.relations_for(conn, memory_ids, scope_ids=scope_ids)
        wanted: dict[str, list[tuple[str, str]]] = {}
        for edge in edges:
            source, target = str(edge["from_id"]), str(edge["to_id"])
            if edge["relation"] == "updates":
                continue  # history, not a live neighbour
            if source in out:
                wanted.setdefault(source, []).append((target, _OUTGOING[edge["relation"]]))
            if target in out:
                wanted.setdefault(target, []).append((source, _INCOMING[edge["relation"]]))
        far = {other for pairs in wanted.values() for other, _ in pairs}
        rows = (
            {
                str(row["id"]): row
                for row in conn.execute(
                    """SELECT * FROM memories
                        WHERE id = ANY(%s) AND scope_id = ANY(%s) AND status = 'active'
                          AND (valid_until IS NULL OR valid_until > now())""",
                    (
                        [uuid.UUID(other) for other in sorted(far)],
                        [uuid.UUID(str(scope)) for scope in scope_ids],
                    ),
                )
            }
            if far
            else {}
        )
        for memory_id, pairs in wanted.items():
            seen: set[str] = set()
            for other, relation in pairs:
                row = rows.get(other)
                if row is None or other in seen or other in out:
                    continue
                seen.add(other)
                out[memory_id]["related"].append(linked_view(row, relation))
                if len(out[memory_id]["related"]) >= per_memory:
                    break
    return out
