"""Per-user export and erasure across the authoritative and derived stores.

Both operations changed meaning when the service stopped having one owner. The
old pair took everything in the database, because everything in it belonged to
the same person. Now a row belongs to a *scope*, and a user's relationship to a
row is one of three things:

* it lives in their private scope -- theirs alone, exported and erased;
* they wrote it into a shared scope -- their words, but the team's record;
* it lives in a shared scope and someone else wrote it -- not theirs at all.

Export takes the first two, because a data-portability request should return
what the person contributed. Erasure takes only the first, and refuses outright
when the second is non-empty: deleting a teammate's citation of a decision
because its author left is not privacy, it is data loss for other people. See
`erase_user` for how that refusal is surfaced.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from qdrant_client import QdrantClient

from . import outbox, vectors
from .db import advisory_lock, iso, transaction, utcnow

EXPORT_FORMAT = "memkit-user-export-v2"

# Never leave the database. Password and key hashes are still credentials: an
# offline attack on the export is an attack on the account.
USER_PUBLIC_COLUMNS = "id,handle,display_name,email,role,created_at,disabled_at"
API_KEY_PUBLIC_COLUMNS = "id,user_id,name,key_prefix,created_at,last_used_at,revoked_at"


def _rows(conn: psycopg.Connection, query: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def _jsonable(value: Any) -> Any:
    """Types psycopg returns that `json.dumps` will not take.

    `timestamptz` arrives as a datetime, `uuid` as a UUID and `numeric` as a
    Decimal, none of which the encoder handles. Timestamps go out in the same
    ISO-8601-with-Z form the API uses, so an export and an API response describe
    a row identically.
    """
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"cannot serialise {type(value).__name__} into an export")


def export_user(
    conn: psycopg.Connection,
    *,
    user_id: str,
    export_dir: Path,
    private_scope_id: str,
    authored_scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Write one JSON file with everything this user contributed.

    Included:

    * their `users` row without `password_hash`;
    * `api_keys` metadata -- id, name, prefix, and the three timestamps, never
      `key_hash`;
    * their own entity (their private scope) and every membership they hold;
    * their sessions and every message they sent;
    * memories in their private scope, **plus** memories they authored in any
      other scope, and the revisions, source links and evidence spans of those;
    * `needs_attention` rows addressed to them;
    * their retrieval runs, the labels on those runs, and the per-memory
      `retrieval_feedback` for the exported memories;
    * their judge runs, which is where their model spend is recorded.

    Deliberately excluded:

    * memories in shared scopes that this user did not author -- a teammate's
      contribution to a scope they happen to share is not this user's data, and
      exporting it would turn a portability request into a scope dump;
    * the shared scopes' own entity rows and other members' identities, for the
      same reason;
    * every credential hash (see `USER_PUBLIC_COLUMNS`).

    `authored_scopes` narrows the second memory set to those scope ids. Pass the
    caller's readable scopes when a user exports themselves, so the file cannot
    contain a scope they have since lost access to; leave it None for an admin
    export, which sees every scope the user wrote into.

    One read transaction covers every query, so the counts in the returned dict
    describe a single consistent snapshot rather than a moving target.
    """
    export_dir.mkdir(parents=True, exist_ok=True)
    stamp = (iso(utcnow()) or "").replace(":", "").replace("-", "")
    path = export_dir / f"memkit-export-{stamp}-{uuid.uuid4().hex[:8]}.json"
    scope_filter = list(authored_scopes) if authored_scopes is not None else None

    with transaction(conn):
        user = _rows(conn, f"SELECT {USER_PUBLIC_COLUMNS} FROM users WHERE id=%s", (user_id,))
        if not user:
            raise LookupError(f"unknown user: {user_id}")
        api_keys = _rows(
            conn,
            f"SELECT {API_KEY_PUBLIC_COLUMNS} FROM api_keys WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        entity = _rows(conn, "SELECT * FROM entities WHERE user_id=%s", (user_id,))
        memberships = _rows(
            conn,
            "SELECT * FROM memberships WHERE user_id=%s ORDER BY entity_id",
            (user_id,),
        )
        sessions = _rows(
            conn, "SELECT * FROM sessions WHERE user_id=%s ORDER BY started_at", (user_id,)
        )
        # `messages.user_id` is denormalised precisely so this does not have to
        # join sessions and hope the join is right.
        messages = _rows(conn, "SELECT * FROM messages WHERE user_id=%s ORDER BY id", (user_id,))
        memories = _rows(
            conn,
            """SELECT * FROM memories
                WHERE scope_id = %s
                   OR (author_id = %s
                       AND (%s::uuid[] IS NULL OR scope_id = ANY(%s::uuid[])))
                ORDER BY created_at,id""",
            (private_scope_id, user_id, scope_filter, scope_filter),
        )
        memory_ids = [str(row["id"]) for row in memories]
        revisions = _rows(
            conn,
            """SELECT * FROM memory_revisions WHERE memory_id = ANY(%s::uuid[])
                ORDER BY memory_id,revision""",
            (memory_ids,),
        )
        sources = _rows(
            conn,
            "SELECT * FROM memory_sources WHERE memory_id = ANY(%s::uuid[]) ORDER BY memory_id",
            (memory_ids,),
        )
        evidence = _rows(
            conn,
            "SELECT * FROM memory_evidence WHERE memory_id = ANY(%s::uuid[]) ORDER BY memory_id",
            (memory_ids,),
        )
        attention = _rows(
            conn,
            "SELECT * FROM needs_attention WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        runs = _rows(
            conn,
            "SELECT * FROM retrieval_runs WHERE user_id=%s ORDER BY created_at",
            (user_id,),
        )
        run_feedback = _rows(
            conn,
            """SELECT * FROM retrieval_run_feedback
                WHERE run_id IN (SELECT id FROM retrieval_runs WHERE user_id=%s)
                ORDER BY id""",
            (user_id,),
        )
        feedback = _rows(
            conn,
            "SELECT * FROM retrieval_feedback WHERE memory_id = ANY(%s::uuid[]) ORDER BY id",
            (memory_ids,),
        )
        judge_runs = _rows(
            conn, "SELECT * FROM judge_runs WHERE user_id=%s ORDER BY id", (user_id,)
        )

    payload = {
        "format": EXPORT_FORMAT,
        "exported_at": iso(utcnow()),
        "user_id": user_id,
        "private_scope_id": private_scope_id,
        "user": user[0],
        "api_keys": api_keys,
        "entities": entity,
        "memberships": memberships,
        "sessions": sessions,
        "messages": messages,
        "memories": memories,
        "memory_revisions": revisions,
        "memory_sources": sources,
        "memory_evidence": evidence,
        "needs_attention": attention,
        "retrieval_runs": runs,
        "retrieval_run_feedback": run_feedback,
        "retrieval_feedback": feedback,
        "judge_runs": judge_runs,
    }
    _write_private_json(path, payload)
    return {
        "path": path,
        "format": EXPORT_FORMAT,
        "api_keys": len(api_keys),
        "memberships": len(memberships),
        "sessions": len(sessions),
        "messages": len(messages),
        "memories": len(memories),
        "memory_revisions": len(revisions),
        "memory_sources": len(sources),
        "memory_evidence": len(evidence),
        "needs_attention": len(attention),
        "retrieval_runs": len(runs),
        "retrieval_run_feedback": len(run_feedback),
        "retrieval_feedback": len(feedback),
        "judge_runs": len(judge_runs),
    }


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    """Write owner-only, atomically, leaving nothing behind on failure.

    The file holds a person's whole history, so the mode is set by `os.open`
    rather than by a later `chmod`: a world-readable window between create and
    chmod is a window an attacker can read. The rename is atomic on the same
    filesystem, so a reader never sees a half-written export, and a failed write
    removes its own temporary instead of leaving a partial file that looks
    finished.
    """
    temporary = path.with_suffix(".json.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=_jsonable)
            handle.write("\n")
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _authored_elsewhere(
    conn: psycopg.Connection, *, user_id: str, private_scope_id: str
) -> list[dict[str, Any]]:
    """Scopes outside the user's own where this user's writing survives."""
    return _rows(
        conn,
        """SELECT m.scope_id,e.slug,count(*) AS memories
             FROM memories m JOIN entities e ON e.id = m.scope_id
            WHERE m.author_id = %s AND m.scope_id <> %s
            GROUP BY m.scope_id,e.slug ORDER BY e.slug""",
        (user_id, private_scope_id),
    )


def erase_user(
    conn: psycopg.Connection,
    client: QdrantClient,
    *,
    user_id: str,
    private_scope_id: str,
) -> dict[str, int]:
    """Erase one user: private memory, raw evidence, credentials, telemetry.

    Refuses when the user authored memories in any scope other than their own.
    `memories.author_id` references `users` with no cascade, so the final DELETE
    would fail on the constraint anyway -- but the point is not the constraint.
    A fact someone wrote into the team scope is the team's record, and the
    honest options are to reassign it to another author or to delete it
    deliberately, both of which are somebody's decision to make. Silently
    cascading it away because the author asked to be forgotten destroys other
    people's knowledge, so the refusal names the count and the scopes and stops.

    What is removed:

    * every memory in the private scope, with its revisions, source links,
      evidence spans, per-memory feedback and attention items (all by cascade);
    * every message and session of the user -- raw evidence is retained against
      prompt rewrites, but not against erasure;
    * their api keys, auth sessions, retrieval runs and run labels, judge runs,
      needs-attention items, jobs and budget reservations;
    * their own entity, and finally the `users` row.

    What is adjusted rather than removed, because the surviving row belongs to
    someone else:

    * `memories.subject_id` pointing at the erased entity is nulled -- a
      teammate's note stays, its reference to the person does not;
    * `memories.reviewed_by`, `needs_attention.resolved_by` and
      `entities.created_by` are nulled for the same reason;
    * `memory_sources` / `memory_evidence` rows citing an erased message are
      dropped even when the citing memory survives, since the excerpt they point
      into no longer exists. The count is returned as `orphaned_citations`.

    The Qdrant side is deleted by filter, not by enumerating ids: listing the
    points first would race with concurrent delivery, and the ids are exactly
    what is being removed.

    The scope locks are what stop an indexer re-inserting a point between the
    two deletions, and they must be the *same* names `outbox.scope_barrier`
    takes: a lock of our own would have been uncontended and would have proved
    nothing. They are taken in sorted order so two erasures cannot deadlock.
    """
    blocking = _authored_elsewhere(conn, user_id=user_id, private_scope_id=private_scope_id)
    if blocking:
        total = sum(int(row["memories"]) for row in blocking)
        where = ", ".join(f"{row['slug']} ({row['memories']})" for row in blocking)
        raise ValueError(
            f"refusing erasure: this user authored {total} memories in shared scopes "
            f"[{where}]. Those are the team's record, not this user's private data. "
            "Reassign them to another author or delete them first, then erase the user."
        )

    # Every scope this erasure will remove points from: the private one, plus
    # any scope holding this user's raw turns.
    locked_scopes = sorted(
        {private_scope_id}
        | {
            str(row["scope_id"])
            for row in conn.execute(
                "SELECT DISTINCT scope_id FROM sessions WHERE user_id=%s", (user_id,)
            )
        }
    )
    with transaction(conn):
        for scope in locked_scopes:
            advisory_lock(conn, outbox.index_lock_name(scope))
        memory_ids = [
            str(row["id"])
            for row in conn.execute(
                "SELECT id FROM memories WHERE scope_id=%s", (private_scope_id,)
            )
        ]
        message_ids = [
            str(row["id"])
            for row in conn.execute("SELECT id FROM messages WHERE user_id=%s", (user_id,))
        ]

        vectors.delete_by_filter(
            client, vectors.MEMORIES, must=[vectors.keyword("scope_id", private_scope_id)]
        )
        vectors.delete_by_filter(client, vectors.RAW, must=[vectors.keyword("user_id", user_id)])

        # Self-reference: a surviving memory may point at one being deleted.
        conn.execute(
            """UPDATE memories SET superseded_by=NULL
                WHERE superseded_by IN (SELECT id FROM memories WHERE scope_id=%s)""",
            (private_scope_id,),
        )
        conn.execute(
            """UPDATE memories SET judge_run_id=NULL
                WHERE judge_run_id IN (SELECT id FROM judge_runs WHERE user_id=%s)""",
            (user_id,),
        )
        conn.execute("UPDATE memories SET reviewed_by=NULL WHERE reviewed_by=%s", (user_id,))
        conn.execute("UPDATE memories SET subject_id=NULL WHERE subject_id=%s", (private_scope_id,))
        conn.execute("UPDATE needs_attention SET resolved_by=NULL WHERE resolved_by=%s", (user_id,))
        conn.execute("UPDATE entities SET created_by=NULL WHERE created_by=%s", (user_id,))

        conn.execute("DELETE FROM memories WHERE scope_id=%s", (private_scope_id,))
        dropped_evidence = conn.execute(
            "DELETE FROM memory_evidence WHERE message_id = ANY(%s::bigint[])", (message_ids,)
        )
        dropped_sources = conn.execute(
            "DELETE FROM memory_sources WHERE message_id = ANY(%s::bigint[])", (message_ids,)
        )
        orphaned = max(0, dropped_evidence.rowcount) + max(0, dropped_sources.rowcount)
        conn.execute("DELETE FROM messages WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM sessions WHERE user_id=%s", (user_id,))
        conn.execute(
            """DELETE FROM budget_reservations
                WHERE user_id=%s OR job_id IN (SELECT id FROM jobs WHERE user_id=%s)""",
            (user_id, user_id),
        )
        conn.execute("DELETE FROM jobs WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM judge_runs WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM needs_attention WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM retrieval_runs WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM api_keys WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM auth_sessions WHERE user_id=%s", (user_id,))
        # Undelivered index work for rows that no longer exist would otherwise
        # be retried until it exhausts its attempts.
        conn.execute(
            "DELETE FROM index_outbox WHERE collection=%s AND entity_id = ANY(%s)",
            (vectors.MEMORIES, memory_ids),
        )
        conn.execute(
            "DELETE FROM index_outbox WHERE collection=%s AND entity_id = ANY(%s)",
            (vectors.RAW, message_ids),
        )
        conn.execute("DELETE FROM entities WHERE user_id=%s", (user_id,))
        conn.execute("DELETE FROM users WHERE id=%s", (user_id,))

    return {
        "memories": len(memory_ids),
        "messages": len(message_ids),
        "orphaned_citations": orphaned,
    }
