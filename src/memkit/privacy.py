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
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient

from . import jobs, maintenance, store, vectors
from .db import iso, transaction, utcnow

EXPORT_FORMAT = "memkit-user-export-v2"

# Never leave the database. Password and key hashes are still credentials: an
# offline attack on the export is an attack on the account.
USER_PUBLIC_COLUMNS = "id,handle,display_name,email,role,created_at,disabled_at"
API_KEY_PUBLIC_COLUMNS = "id,user_id,name,key_prefix,created_at,last_used_at,revoked_at"


class ErasureCleanupPending(RuntimeError):
    """Authoritative deletion committed; derived cleanup must be retried."""


def export_user(
    conn: psycopg.Connection,
    *,
    user_id: str,
    export_dir: Path,
    private_scope_id: str,
    authored_scopes: list[str] | None = None,
) -> dict[str, Any]:
    with maintenance.shared(conn):
        previous = conn.isolation_level
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        try:
            return _export_user(
                conn,
                user_id=user_id,
                export_dir=export_dir,
                private_scope_id=private_scope_id,
                authored_scopes=authored_scopes,
            )
        finally:
            conn.isolation_level = previous


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


def _export_user(
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
        revision_evidence = _rows(
            conn,
            "SELECT * FROM memory_revision_evidence WHERE memory_id = ANY(%s::uuid[]) ORDER BY memory_id,revision,message_id,start_char",
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
        "memory_revision_evidence": revision_evidence,
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
        "memory_revision_evidence": len(revision_evidence),
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


def _erase_database(
    conn: psycopg.Connection,
    *,
    user_id: str,
    private_scope_id: str,
    job_id: str,
    export_paths: list[str],
    guard: Callable[[], None] | None = None,
) -> dict[str, int]:
    """Delete authoritative rows and save the cleanup checkpoint atomically."""
    with transaction(conn):
        if guard is not None:
            guard()
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

        # Shared records survive. Their current references must still become
        # a new revision and index event; old revisions retain team history.
        surviving = conn.execute(
            """SELECT id FROM memories WHERE scope_id<>%s AND (
                   subject_id=%s OR
                   superseded_by IN (SELECT id FROM memories WHERE scope_id=%s) OR
                   judge_run_id IN (SELECT id FROM judge_runs WHERE user_id=%s))""",
            (private_scope_id, private_scope_id, private_scope_id, user_id),
        ).fetchall()
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
        for saved in surviving:
            current = conn.execute("SELECT * FROM memories WHERE id=%s", (saved["id"],)).fetchone()
            store.update_memory(
                conn,
                memory_id=str(current["id"]),
                scopes=[str(current["scope_id"])],
                expected_revision=int(current["revision"]),
                text=current["text"],
                kind=current["kind"],
                context=current["context"],
                tags=current["tags"],
                importance=current["importance"],
                confidence=current["confidence"],
                valid_until=current["valid_until"],
            )
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
        conn.execute("UPDATE jobs SET user_id=NULL WHERE id=%s AND user_id=%s", (job_id, user_id))
        conn.execute("DELETE FROM jobs WHERE user_id=%s AND id<>%s", (user_id, job_id))
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
        checkpoint = {
            "accepted": True,
            "database_erased": True,
            "user_id": user_id,
            "private_scope_id": private_scope_id,
            "export_paths": export_paths,
            "counts": {
                "memories": len(memory_ids),
                "messages": len(message_ids),
                "orphaned_citations": orphaned,
            },
        }
        conn.execute(
            "UPDATE jobs SET input=jsonb_set(input,'{erasure}',%s),updated_at=now() WHERE id=%s",
            (Jsonb(checkpoint), job_id),
        )

    return {
        "memories": len(memory_ids),
        "messages": len(message_ids),
        "orphaned_citations": orphaned,
    }


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def initialize_erasure_manifest(backup_dir: Path, receipts: list[dict[str, str]]) -> Path:
    """Explicitly establish an audited baseline, publishing its marker last."""
    root = backup_dir.expanduser().resolve() / "erasures"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _sync_directory(root.parent)
    for receipt in receipts:
        user_id = str(uuid.UUID(receipt["user_id"]))
        scope_id = str(uuid.UUID(receipt["private_scope_id"]))
        path = root / f"{user_id}.json"
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("user_id") != user_id or saved.get("private_scope_id") != scope_id:
                raise ValueError("baseline conflicts with an existing erasure receipt")
            continue
        _write_durable_json(
            path,
            {
                "format": "memkit-erasure-v1",
                "user_id": user_id,
                "private_scope_id": scope_id,
                "accepted_at": receipt.get("accepted_at") or iso(utcnow()),
            },
        )
    # Validate preexisting receipts too; a broken file is not an empty baseline.
    for path in root.glob("*.json"):
        if path.name == "manifest.json":
            continue
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("format") != "memkit-erasure-v1":
            raise ValueError(f"invalid existing erasure receipt: {path.name}")
        uuid.UUID(saved["user_id"])
        uuid.UUID(saved["private_scope_id"])
    _write_durable_json(root / "manifest.json", {"format": "memkit-erasure-manifest-v1"})
    return root


def ensure_erasure_manifest(backup_dir: Path, *, existing_backups: bool = False) -> Path:
    """Initialize fresh installs only; missing historical receipts fail closed."""
    base = backup_dir.expanduser().resolve()
    root = base / "erasures"
    if (root / "manifest.json").exists():
        erasure_manifest(base)
        return root
    if existing_backups or any(base.glob("*.dump")) or any(root.glob("*.json")):
        raise RuntimeError(
            "erasure manifest missing for existing backups; audit prior erasures and run "
            "`memkit backup init-erasure-manifest --confirm BASELINE` with known receipts"
        )
    return initialize_erasure_manifest(base, [])


def _write_durable_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, default=_jsonable)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _write_erasure_manifest(
    backup_dir: Path, *, user_id: str, private_scope_id: str, existing_backups: bool = False
) -> None:
    root = ensure_erasure_manifest(backup_dir, existing_backups=existing_backups)
    target = root / f"{uuid.UUID(user_id)}.json"
    if target.exists():
        record = json.loads(target.read_text(encoding="utf-8"))
        if record.get("user_id") != user_id or record.get("private_scope_id") != private_scope_id:
            raise RuntimeError("erasure manifest target mismatch")
        return
    _write_durable_json(
        target,
        {
            "format": "memkit-erasure-v1",
            "user_id": user_id,
            "private_scope_id": private_scope_id,
            "accepted_at": iso(utcnow()),
        },
    )


def erasure_manifest(backup_dir: Path) -> list[dict[str, str]]:
    """Read the latest receipts; never manufacture an empty ledger on restore."""
    root = backup_dir.expanduser().resolve() / "erasures"
    marker = root / "manifest.json"
    if (
        not marker.is_file()
        or json.loads(marker.read_text()).get("format") != "memkit-erasure-manifest-v1"
    ):
        raise RuntimeError(
            "latest erasure manifest is missing; restored service must remain offline"
        )
    records = []
    for path in sorted(root.glob("*.json")):
        if path.name == "manifest.json":
            continue
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("format") != "memkit-erasure-v1":
            raise RuntimeError(f"invalid erasure receipt: {path.name}")
        for key in ("user_id", "private_scope_id"):
            uuid.UUID(item[key])
        records.append(item)
    return records


def _managed_exports(export_dir: Path, user_id: str) -> list[str]:
    found = []
    root = export_dir.expanduser().resolve()
    for path in root.glob("memkit-export-*.json"):
        if path.is_symlink() or not path.is_file():
            continue
        # Existing filenames predate user identifiers. Reading the owner field
        # keeps old exports erasable without deleting another person's file.
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("format") == EXPORT_FORMAT and payload.get("user_id") == user_id:
            found.append(str(path))
    return found


def erase_user(
    conn: psycopg.Connection,
    client: QdrantClient,
    *,
    user_id: str,
    private_scope_id: str,
    export_dir: Path | None = None,
    backup_dir: Path | None = None,
    job_id: str | None = None,
    guard: Callable[[], None] | None = None,
) -> dict[str, int]:
    """Commit private erasure, then retryably remove derived copies.

    Retained backups are not edited. A durable receipt outside PostgreSQL must
    be reapplied after restoring an older dump, before serving it. Shared facts
    authored by this user still block erasure; no other person's record is lost.
    """
    if export_dir is None or backup_dir is None:
        from .config import get_settings

        settings = get_settings()
        export_dir = export_dir or settings.export_dir
        backup_dir = backup_dir or settings.backup_dir
    if job_id is None:
        # Direct/operator calls use the same durable, fenced job protocol as
        # the worker. Creation and claim commit together so no worker can take
        # the operation in between them.
        with transaction(conn):
            direct_id = jobs.create(
                conn,
                kind="erase",
                input_data={"user_id": user_id, "private_scope_id": private_scope_id},
            )
            holder = str(jobs.claim(conn, direct_id)["holder"])
        try:
            with jobs.heartbeat(conn, direct_id, holder=holder) as lost:

                def direct_guard() -> None:
                    if lost.is_set():
                        raise jobs.LeaseLost(f"erasure lease lost: {direct_id}")
                    jobs.require_current(conn, direct_id, holder)
                    if guard is not None:
                        guard()

                result = erase_user(
                    conn,
                    client,
                    user_id=user_id,
                    private_scope_id=private_scope_id,
                    export_dir=export_dir,
                    backup_dir=backup_dir,
                    job_id=direct_id,
                    guard=direct_guard,
                )
                jobs.finish(conn, direct_id, holder=holder, status="complete", result=result)
                return result
        except (maintenance.MaintenanceBusy, ErasureCleanupPending) as exc:
            jobs.defer(conn, direct_id, holder=holder, error=str(exc))
            raise
        except jobs.LeaseLost:
            raise
        except Exception as exc:
            jobs.finish(
                conn,
                direct_id,
                holder=holder,
                status="failed",
                error_code="erase_failed",
                error=str(exc),
            )
            raise
    with maintenance.exclusive(conn):
        checkpoint: dict[str, Any] = {}
        if job_id is not None:
            job = jobs.get(conn, job_id)
            if job["kind"] != "erase":
                raise ValueError("erasure requires an erase job")
            checkpoint = (job["input"] or {}).get("erasure") or {}
            if checkpoint and (
                checkpoint["user_id"] != user_id
                or checkpoint["private_scope_id"] != private_scope_id
            ):
                raise ValueError("erasure checkpoint target mismatch")
        if not checkpoint.get("database_erased"):
            blocking = _authored_elsewhere(conn, user_id=user_id, private_scope_id=private_scope_id)
            if blocking:
                where = ", ".join(f"{row['slug']} ({row['memories']})" for row in blocking)
                raise ValueError(
                    f"refusing erasure: shared authored memories [{where}]; reassign or delete them first"
                )
            try:
                paths = _managed_exports(export_dir, user_id)
                existing_backups = conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM backup_artifacts) AS present"
                ).fetchone()["present"]
                # A changed mount path is not a fresh install. Validate the
                # baseline before accepting an irreversible erasure receipt.
                ensure_erasure_manifest(backup_dir, existing_backups=existing_backups)
            except (OSError, psycopg.OperationalError, psycopg.InterfaceError) as exc:
                if checkpoint.get("accepted"):
                    raise ErasureCleanupPending(
                        f"erasure {job_id} accepted; preparation retry pending: {exc}"
                    ) from exc
                raise
            # Acceptance survives a crash before the receipt or database phase.
            # Once accepted, retry resumes this operation rather than treating a
            # cancellation as if an already-persisted restore receipt vanished.
            with transaction(conn):
                if guard is not None:
                    guard()
                conn.execute(
                    "UPDATE jobs SET input=jsonb_set(input,'{erasure}',%s),updated_at=now() WHERE id=%s",
                    (
                        Jsonb(
                            {
                                "accepted": True,
                                "database_erased": False,
                                "user_id": user_id,
                                "private_scope_id": private_scope_id,
                                "export_paths": paths,
                            }
                        ),
                        job_id,
                    ),
                )
            try:
                _write_erasure_manifest(
                    backup_dir,
                    user_id=user_id,
                    private_scope_id=private_scope_id,
                    existing_backups=existing_backups,
                )
            except OSError as exc:
                raise ErasureCleanupPending(
                    f"erasure {job_id} accepted; receipt persistence pending: {exc}"
                ) from exc
            try:
                _erase_database(
                    conn,
                    user_id=user_id,
                    private_scope_id=private_scope_id,
                    job_id=job_id,
                    export_paths=paths,
                    guard=guard,
                )
            except (OSError, psycopg.OperationalError, psycopg.InterfaceError) as exc:
                raise ErasureCleanupPending(
                    f"erasure {job_id} accepted; database retry pending: {exc}"
                ) from exc
            checkpoint = jobs.get(conn, job_id)["input"]["erasure"]
        try:
            with transaction(conn):
                if guard is not None:
                    guard()
                vectors.erase_user_indices(
                    client, user_id=user_id, private_scope_id=private_scope_id
                )
                root = export_dir.expanduser().resolve()
                for raw_path in checkpoint["export_paths"]:
                    path = Path(raw_path)
                    if path.is_symlink() or not path.resolve().is_relative_to(root):
                        raise RuntimeError("erasure export path escaped the managed directory")
                    path.unlink(missing_ok=True)
                if root.is_dir():
                    _sync_directory(root)
        except jobs.LeaseLost:
            raise
        except Exception as exc:
            raise ErasureCleanupPending(
                f"erasure {job_id} committed; cleanup pending: {exc}"
            ) from exc
        return dict(checkpoint["counts"])


def replay_erasure_manifest(conn: psycopg.Connection, backup_dir: Path) -> dict[str, int]:
    """Sanitize an offline restored database before rebuilding any index.

    External index/export cleanup is performed by the saved erase jobs after
    startup. Operators must discard old Qdrant storage and restore no exports.
    """
    receipts = erasure_manifest(backup_dir)
    reapplied = 0
    with maintenance.exclusive(conn):
        for receipt in receipts:
            user_id, scope_id = receipt["user_id"], receipt["private_scope_id"]
            if not conn.execute("SELECT 1 FROM users WHERE id=%s", (user_id,)).fetchone():
                continue
            if _authored_elsewhere(conn, user_id=user_id, private_scope_id=scope_id):
                raise RuntimeError(
                    "restored shared authorship blocks erasure; keep the service offline"
                )
            job_id = jobs.create(
                conn, kind="erase", input_data={"user_id": user_id, "private_scope_id": scope_id}
            )
            _erase_database(
                conn, user_id=user_id, private_scope_id=scope_id, job_id=job_id, export_paths=[]
            )
            reapplied += 1
    return {"receipts": len(receipts), "reapplied": reapplied}
