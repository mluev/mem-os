"""Eligibility shared by bounded candidate arms and authoritative row checks."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb
from qdrant_client import models

from . import filters, vectors


def document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": row["kind"],
        "agent_id": row["agent_id"],
        "context": dict(row["context"] or {}),
        "tags": list(row["tags"] or []),
        "subject_id": str(row["subject_id"]) if row.get("subject_id") else None,
    }


def filter_sql(expression: dict[str, Any] | None, *, alias: str = "m") -> tuple[str, list]:
    """Compile the existing JSON filter semantics to parameterized PostgreSQL."""
    filters.validate(expression)
    if not expression:
        return "TRUE", []
    if "all" in expression:
        children = [filter_sql(child, alias=alias) for child in expression["all"]]
        return (
            " AND ".join(f"({sql})" for sql, _ in children) or "TRUE",
            [value for _, params in children for value in params],
        )
    # alias is an internal identifier, never caller input.
    doc = (
        f"jsonb_build_object('kind',{alias}.kind,'agent_id',{alias}.agent_id,"
        f"'context',{alias}.context,'tags',{alias}.tags,'subject_id',{alias}.subject_id)"
    )
    value = f"COALESCE({doc} #> %s::text[], 'null'::jsonb)"
    path = expression["field"].split(".")
    operation = expression["op"]
    if operation == "exists":
        return f"{value} <> 'null'::jsonb", [path]
    if operation == "absent":
        return f"{value} = 'null'::jsonb", [path]
    if operation == "eq":
        return f"{value} = %s::jsonb", [path, Jsonb(expression.get("value"))]
    return (
        "EXISTS (SELECT 1 FROM jsonb_array_elements("
        f"CASE WHEN jsonb_typeof({value})='array' THEN {value} "
        f"ELSE jsonb_build_array({value}) END) item "
        "WHERE item.value IN (SELECT value FROM jsonb_array_elements(%s::jsonb)))",
        [path, path, path, Jsonb(expression["value"])],
    )


def memory_sql(
    *,
    expression: dict[str, Any] | None,
    kinds: list[str] | None,
    allowed_roles: frozenset[str] | None,
    now: datetime,
) -> tuple[str, list]:
    predicate, params = filter_sql(expression)
    clauses = ["(m.valid_until IS NULL OR m.valid_until > %s)", f"({predicate})"]
    values: list[Any] = [now, *params]
    if kinds:
        clauses.append("m.kind=ANY(%s)")
        values.append(kinds)
    if allowed_roles is not None:
        clauses.append("m.source_role=ANY(%s)")
        values.append(sorted(allowed_roles))
    return " AND ".join(clauses), values


def vector_filters(expression: dict[str, Any] | None, *, raw: bool = False) -> list[Any]:
    """Push scalar constraints; PostgreSQL verifies every proposed hit.

    Arbitrary JSON equality and empty-array existence have different semantics
    in Qdrant, so they are deliberately left to the authoritative row check.
    """
    if not expression:
        return []
    if "all" in expression:
        return [
            condition for child in expression["all"] for condition in vector_filters(child, raw=raw)
        ]
    key, operation, value = expression["field"], expression["op"], expression.get("value")
    if raw and key in {"kind", "subject_id", "tags"}:
        return []
    if key not in {"kind", "agent_id", "subject_id", "tags"} and not key.startswith("context."):
        return []
    if operation == "eq" and isinstance(value, (str, bool, int)):
        return [models.FieldCondition(key=key, match=models.MatchValue(value=value))]
    if operation == "in" and value and all(isinstance(item, str) for item in value):
        return [vectors.keyword(key, value)]
    return []


def memory_vectors(
    *,
    expression: dict[str, Any] | None,
    kinds: list[str] | None,
    allowed_roles: frozenset[str] | None,
    now: datetime,
) -> list[Any]:
    conditions = vector_filters(expression)
    if kinds:
        conditions.append(vectors.keyword("kind", kinds))
    if allowed_roles is not None:
        conditions.append(vectors.keyword("source_role", sorted(allowed_roles)))
    conditions.append(
        models.Filter(
            should=[
                models.IsEmptyCondition(is_empty=models.PayloadField(key="valid_until")),
                models.FieldCondition(key="valid_until", range=models.DatetimeRange(gt=now)),
            ]
        )
    )
    return conditions
