"""Context-safe maintenance with conservative exact-duplicate consolidation."""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from . import outbox, store, vectors
from .db import transaction, utcnow


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


@dataclass
class Outcome:
    expired: list[str] = field(default_factory=list)
    demoted: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    candidate_groups: list[list[str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "expired": self.expired,
            "demoted": self.demoted,
            "superseded": self.superseded,
            "candidate_groups": self.candidate_groups,
        }


def plan(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    stale_days: int,
) -> Outcome:
    outcome = Outcome()
    outcome.expired = [
        row["id"]
        for row in conn.execute(
            """SELECT id FROM memories WHERE owner_id=? AND status='active'
                AND valid_until IS NOT NULL
                AND valid_until<=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
            (owner_id,),
        )
    ]
    outcome.demoted = [
        row["id"]
        for row in conn.execute(
            """SELECT id FROM memories WHERE owner_id=? AND status='active'
                AND importance>0
                AND COALESCE(last_retrieved_at,created_at)
                    <=strftime('%Y-%m-%dT%H:%M:%SZ','now',?)""",
            (owner_id, f"-{stale_days} days"),
        )
    ]
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in conn.execute(
        """SELECT id,kind,text,context_json FROM memories
            WHERE owner_id=? AND status='active' ORDER BY updated_at DESC,id""",
        (owner_id,),
    ):
        groups[(row["kind"], row["context_json"], _normalise(row["text"]))].append(row["id"])
    outcome.candidate_groups = [ids for ids in groups.values() if len(ids) > 1]
    return outcome


def run(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    stale_days: int,
    demotion: float,
    dry_run: bool,
) -> Outcome:
    outcome = plan(conn, owner_id=owner_id, stale_days=stale_days)
    if dry_run:
        return outcome
    with transaction(conn):
        now = utcnow()
        for memory_id in outcome.expired:
            conn.execute(
                "UPDATE memories SET status='expired',updated_at=? WHERE id=?",
                (now, memory_id),
            )
            outbox.enqueue(
                conn,
                collection=vectors.MEMORIES,
                entity_id=memory_id,
                operation="delete",
            )
        for memory_id in outcome.demoted:
            conn.execute(
                """UPDATE memories SET importance=MAX(0,importance-?),updated_at=?
                    WHERE id=?""",
                (demotion, now, memory_id),
            )
            row = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            outbox.enqueue(
                conn,
                collection=vectors.MEMORIES,
                entity_id=memory_id,
                operation="upsert",
                payload=store.mem_payload(row),
            )
        for group in outcome.candidate_groups:
            survivor, *duplicates = group
            for duplicate in duplicates:
                conn.execute(
                    """UPDATE memories SET status='superseded',superseded_by=?,updated_at=?
                        WHERE id=?""",
                    (survivor, now, duplicate),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO memory_sources(memory_id,message_id)
                       SELECT ?,message_id FROM memory_sources WHERE memory_id=?""",
                    (survivor, duplicate),
                )
                conn.execute(
                    """INSERT OR IGNORE INTO memory_evidence
                       (memory_id,message_id,start_char,end_char,excerpt_sha256)
                       SELECT ?,message_id,start_char,end_char,excerpt_sha256
                         FROM memory_evidence WHERE memory_id=?""",
                    (survivor, duplicate),
                )
                outbox.enqueue(
                    conn,
                    collection=vectors.MEMORIES,
                    entity_id=duplicate,
                    operation="delete",
                )
                outcome.superseded.append(duplicate)
    return outcome
