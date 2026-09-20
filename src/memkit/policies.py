"""Versioned retrieval, extraction, retention and consolidation policy rows.

The only part of the old records platform worth keeping. A policy is immutable
once written and identified by its version, so a measured ranking change can be
adopted, compared against the previous one, and rolled back by pointing at the
older id -- see docs/decisions/0051.

Policies are optionally scoped: a NULL scope is instance-wide, which is what
the seeded `core-*` rows are.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .db import Row


def put_policy(
    conn: psycopg.Connection,
    *,
    scope_id: str | None,
    kind: str,
    name: str,
    version: int,
    config: dict[str, Any],
) -> str:
    """Write one policy version. Re-writing the same version is refused."""
    if kind not in {"extraction", "retrieval", "retention", "consolidation"}:
        raise ValueError(f"unknown policy kind: {kind!r}")
    if version < 1:
        raise ValueError("policy version starts at 1")
    policy_id = str(uuid.uuid4())
    row = conn.execute(
        """INSERT INTO policies (id,scope_id,kind,name,version,config)
           VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (scope_id,kind,name,version) DO NOTHING
           RETURNING id""",
        (policy_id, scope_id, kind, name, version, Jsonb(config)),
    ).fetchone()
    if row is None:
        raise ValueError(f"policy {kind}/{name} version {version} already exists")
    return str(row["id"])


def list_policies(
    conn: psycopg.Connection, *, scope_id: str | None = None, kind: str | None = None
) -> list[Row]:
    """Instance-wide policies, plus this scope's own."""
    return list(
        conn.execute(
            """SELECT * FROM policies
                WHERE (scope_id IS NULL OR scope_id = %s)
                  AND (%s::text IS NULL OR kind = %s)
                ORDER BY kind, name, version DESC""",
            (scope_id, kind, kind),
        )
    )
