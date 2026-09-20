"""Short-transaction, evidence-precise memory extraction."""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from . import entities, judge, maintenance, provenance, store
from .db import Row, advisory_lock, iso, utcnow
from .principal import ScopeForbidden
from .semantic_runtime import SemanticBlocks

logger = logging.getLogger(__name__)
WINDOW_SIZE = 10
# Candidate slots reserved for same-context recency, out of `find_candidates`'
# limit. The remainder goes to the cross-context dense arm, which informs dedup
# but can never be an UPDATE target.
RECENCY_SLOTS = 6


@dataclass
class ExtractionOutcome:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    skipped: int = 0
    rejected: int = 0
    # One entry per rejected op: {"op", "id", "reason"}. Lands in the job result
    # JSON via as_dict(), so extraction quality is debuggable from /v1/jobs
    # without a new table. A bare counter hid *why* ops died, which made every
    # prompt regression look identical.
    rejections: list[dict[str, Any]] = field(default_factory=list)
    # ADD ops whose text was a near-verbatim duplicate of an existing active
    # memory in the same context: the evidence is linked to that memory instead
    # of inserting a twin. See decisions/0055.
    deduplicated: int = 0
    cost_usd: float = 0.0
    judge_run_id: int | None = None
    error: str | None = None
    # Messages leased by this call. Zero means there was nothing left to claim,
    # which is the only safe signal that a drain loop has finished: a window
    # held by another job's live lease also yields zero, and retrying it would
    # spin forever.
    claimed: int = 0
    # The gate refused this window and released it. Distinct from a clean empty
    # result, because a refusal is not progress.
    declined: bool = False
    # Windows a single run consumed. One, unless run_session_extraction looped.
    windows: int = 0
    # Facts that named somebody nobody could resolve. Kept, but private and
    # unattributed until a human says who was meant.
    unresolved_mentions: int = 0
    semantic_support: dict[str, int] = field(default_factory=dict)

    @property
    def applied(self) -> int:
        return self.added + self.updated + self.deleted

    def absorb(self, other: ExtractionOutcome) -> None:
        """Fold one window's result into a running total."""
        self.added += other.added
        self.updated += other.updated
        self.deleted += other.deleted
        self.skipped += other.skipped
        self.rejected += other.rejected
        self.rejections.extend(other.rejections)
        self.deduplicated += other.deduplicated
        self.cost_usd += other.cost_usd
        self.claimed += other.claimed
        self.windows += other.windows
        self.unresolved_mentions += other.unresolved_mentions
        for key, value in other.semantic_support.items():
            self.semantic_support[key] = self.semantic_support.get(key, 0) + value
        self.declined = other.declined
        if other.judge_run_id is not None:
            self.judge_run_id = other.judge_run_id
        if other.error:
            self.error = other.error

    def reject(self, op: Any, reason: str) -> None:
        self.rejected += 1
        self.rejections.append({"op": op.op, "id": op.id, "reason": reason})

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "deleted": self.deleted,
            "skipped": self.skipped,
            "rejected": self.rejected,
            "rejections": self.rejections,
            "deduplicated": self.deduplicated,
            "cost_usd": round(self.cost_usd, 6),
            "judge_run_id": self.judge_run_id,
            "error": self.error,
            "claimed": self.claimed,
            "windows": self.windows,
            "unresolved_mentions": self.unresolved_mentions,
            "semantic_support": self.semantic_support,
        }


def messages_since_last(conn: psycopg.Connection, session_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE session_id=%s AND NOT processed",
        (session_id,),
    ).fetchone()
    return int(row["n"]) if row else 0


def unprocessed_window(conn: psycopg.Connection, session_id: str) -> list[Row]:
    return conn.execute(
        """SELECT * FROM messages WHERE session_id=%s AND NOT processed
            ORDER BY id LIMIT %s""",
        (session_id, WINDOW_SIZE),
    ).fetchall()


def claim_window(
    conn: psycopg.Connection,
    *,
    session_id: str,
    job_id: str,
    lease_seconds: int = 300,
) -> list[Row]:
    """Atomically lease one exact message range so provider work is never duplicated.

    Serialize assembly per session: SKIP LOCKED alone protects individual rows,
    but racing workers can split and interleave one ordered conversation window.
    The transaction lock ends before provider work; unrelated sessions can claim
    concurrently. Leases continue protecting messages after the lock is released.
    """
    token = f"{job_id}:{uuid.uuid4()}"
    with conn.transaction():
        advisory_lock(conn, f"extraction-window:{session_id}")
        now = utcnow()
        # Windows whose holder died are claimable again.
        conn.execute(
            """UPDATE messages SET claim_token=NULL,claim_expires_at=NULL
                 WHERE session_id=%s AND NOT processed AND claim_expires_at IS NOT NULL
                   AND claim_expires_at <= %s""",
            (session_id, now),
        )
        rows = conn.execute(
            """UPDATE messages SET claim_token=%s, claim_expires_at=%s
                WHERE id IN (
                    SELECT id FROM messages
                     WHERE session_id=%s AND NOT processed AND claim_token IS NULL
                     ORDER BY id
                     FOR UPDATE SKIP LOCKED
                     LIMIT %s
                )
                RETURNING *""",
            (token, now + timedelta(seconds=lease_seconds), session_id, WINDOW_SIZE),
        ).fetchall()
    return sorted(rows, key=lambda row: int(row["id"]))


def release_window(conn: psycopg.Connection, rows: list[Row]) -> None:
    claims = sorted({str(row["claim_token"]) for row in rows if row["claim_token"]})
    if not claims:
        return
    conn.execute(
        """UPDATE messages SET claim_token=NULL,claim_expires_at=NULL
             WHERE claim_token = ANY(%s) AND NOT processed""",
        (claims,),
    )


def session_context(conn: psycopg.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT context FROM sessions WHERE id=%s", (session_id,)).fetchone()
    if row is None:
        raise ValueError("unknown session")
    return dict(row["context"] or {})


def session_identity(conn: psycopg.Connection, session_id: str) -> Row:
    """The user and scope a session is fixed to.

    Extraction routes facts on behalf of whoever owns the session, so this is
    the authorization anchor for the whole run: no request parameter can change
    which user's memory a window writes into.
    """
    row = conn.execute(
        "SELECT id,user_id,scope_id,agent_id,context FROM sessions WHERE id=%s",
        (session_id,),
    ).fetchone()
    if row is None:
        raise ValueError("unknown session")
    return row


def find_candidates(
    conn: psycopg.Connection,
    *,
    scope_id: str,
    allowed_scope_ids: Sequence[str],
    context: dict[str, Any],
    limit: int = 10,
    client: Any = None,
    embedder: Any = None,
    window_text: str = "",
) -> list[dict[str, Any]]:
    """Candidates the judge may UPDATE/DELETE — and must not re-ADD.

    Two arms, and the order between them is load-bearing. Recency in the
    session's own scope and context comes first and keeps RECENCY_SLOTS of the
    limit: those are the only candidates an operation may legally target, since
    apply_ops rejects any UPDATE/DELETE whose target scope or context differs.
    The dense arm then fills what is left with a search over the window's user
    text across every scope the speaker can read, because the near-duplicate
    worth noticing usually lives under a different or empty context, which
    exact-context recency can never surface — measured on this corpus as a
    0.9821-cosine pair that never merged. Those extra candidates inform dedup
    only.

    Postgres stays authoritative: a dense hit is used only after its row is
    re-read and confirmed active, because the index is derived and can lag.
    """

    def _shape(row: Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "kind": row["kind"],
            "text": row["text"],
            "importance": float(row["importance"]),
            "context": dict(row["context"] or {}),
            "scope_id": str(row["scope_id"]),
        }

    merged: dict[str, dict[str, Any]] = {}
    rows = conn.execute(
        """SELECT * FROM memories
            WHERE scope_id=%s AND status='active' AND context=%s
            ORDER BY updated_at DESC,id LIMIT %s""",
        (scope_id, Jsonb(context), RECENCY_SLOTS),
    ).fetchall()
    for row in rows:
        merged[str(row["id"])] = _shape(row)

    if client is not None and embedder is not None and window_text.strip() and len(merged) < limit:
        from . import vectors

        hits = vectors.search(
            client,
            vectors.MEMORIES,
            embedder.encode_one(window_text),
            limit=limit - len(merged),
            must=[
                vectors.keyword("scope_id", list(allowed_scope_ids)),
                vectors.keyword("status", "active"),
            ],
            exclude_ids=list(merged),
        )
        for hit in hits:
            row = conn.execute(
                """SELECT * FROM memories
                    WHERE id=%s AND scope_id = ANY(%s) AND status='active'""",
                (str(hit.id), [uuid.UUID(str(s)) for s in allowed_scope_ids]),
            ).fetchone()
            if row is not None:
                merged.setdefault(str(row["id"]), _shape(row))
    return list(merged.values())[:limit]


def _validated_evidence(
    conn: psycopg.Connection,
    op: judge.Op,
    *,
    allowed_message_ids: set[int],
) -> tuple[list[dict[str, Any]], set[str]] | None:
    citations = op.evidence or []
    if op.op in {"ADD", "UPDATE"} and not citations:
        return None
    evidence: list[dict[str, Any]] = []
    roles: set[str] = set()
    for citation in citations:
        message_id = citation["message_id"]
        if message_id not in allowed_message_ids:
            return None
        row = conn.execute(
            "SELECT role,content FROM messages WHERE id=%s", (message_id,)
        ).fetchone()
        if row is None:
            return None
        start = citation["start_char"]
        end = citation["end_char"]
        quote = str(citation.get("quote") or "")
        if quote:
            first = str(row["content"]).find(quote)
            # Derive offsets locally only from a unique verbatim user span.
            # Ambiguous or non-verbatim quotes remain invalid citations.
            if first < 0 or str(row["content"]).find(quote, first + 1) >= 0:
                return None
            start, end = first, first + len(quote)
        if end > len(row["content"]):
            return None
        excerpt = row["content"][start:end]
        if not excerpt.strip():
            return None
        roles.add(row["role"])
        evidence.append(
            {
                "message_id": message_id,
                "start_char": start,
                "end_char": end,
                "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
            }
        )
    return evidence, roles


@dataclass(frozen=True)
class DedupTarget:
    id: str
    revision: int


def plan_dedup(
    conn: psycopg.Connection,
    *,
    ops: list[judge.Op],
    scope_id: str,
    client: Any,
    embedder: Any,
    threshold: float | None,
    subjects: dict[int, str | None] | None = None,
    source_roles: dict[int, str] | None = None,
    eligible: set[int] | None = None,
    semantic: SemanticBlocks | None = None,
) -> dict[int, DedupTarget]:
    """Map op index → existing memory id for ADD ops that duplicate the store.

    Runs BEFORE the write transaction on purpose: embedding and the Qdrant
    round-trip must not extend a write transaction (the same discipline ADR
    0052 applies to provider calls). apply_ops re-reads each planned target
    inside the transaction and falls back to a normal ADD if it vanished.

    Same scope and same context only: by this repo's own model a fact
    duplicated across scopes is two facts, and one of them may be shared while
    the other is private. At the configured 0.90 only near-verbatim text clears
    the bar — a genuine paraphrase measures ≈0.898 on this corpus (see
    config.dedup_cosine).
    """
    if client is None or embedder is None or threshold is None:
        return {}
    from . import vectors

    planned: dict[int, DedupTarget] = {}
    pairs: dict[int, dict[str, Any]] = {}
    adds = [
        (index, op)
        for index, op in enumerate(ops)
        if op.op == "ADD" and (op.text or "").strip() and (eligible is None or index in eligible)
    ]
    if not adds:
        return {}
    # One embedding call for the whole set: each acquires the embedder lock, and
    # a window can carry several ADDs.
    embedded = embedder.encode([str(op.text) for _, op in adds])
    for (index, op), op_vector in zip(adds, embedded, strict=True):
        target_scope = op.scope_id or scope_id
        hits = vectors.search(
            client,
            vectors.MEMORIES,
            op_vector,
            limit=3,
            must=[
                vectors.keyword("scope_id", target_scope),
                vectors.keyword("status", "active"),
            ],
        )
        for hit in hits:
            if float(hit.score) < threshold:
                continue
            row = conn.execute(
                """SELECT * FROM memories
                    WHERE id=%s AND scope_id=%s AND status='active'
                    AND (valid_until IS NULL OR valid_until > now())
                    AND source_role=%s""",
                (str(hit.id), target_scope, (source_roles or {}).get(index, "user")),
            ).fetchone()
            if (
                row is not None
                and dict(row["context"] or {}) == (op.context or {})
                and (str(row["subject_id"]) if row["subject_id"] else None)
                == (subjects or {}).get(index)
                and row["kind"] == (op.kind or "fact")
                and iso(row["valid_until"]) == iso(op.valid_until)
            ):
                planned[index] = DedupTarget(str(row["id"]), int(row["revision"]))
                pairs[index] = {"existing": row["text"], "incoming": op.text}
                break
    if semantic is not None:
        allowed = semantic.verify_duplicates(pairs)
        planned = {index: target for index, target in planned.items() if index in allowed}
    return planned


def _context_allowed(operation: dict[str, str], session: dict[str, Any]) -> bool:
    return all(key in session and str(session[key]) == value for key, value in operation.items())


def reconcile_context(operation: dict[str, str], session: dict[str, Any]) -> dict[str, str] | None:
    """Map an op's context onto the session's own keys, or None if it cannot be.

    The guard exists to stop a claim being written into a scope the session is
    not in. Renaming a key is not that: shown `{"source_workspace": "shop"}` the
    judge routinely answers `{"workspace": "shop"}`, and rejecting it silently
    dropped correct, durable project facts — measured on a mixed session where
    two of four extracted facts died this way.

    Every value must still come from the session context, and an ambiguous
    value (two session keys holding it) is refused. So a rename can only ever
    resolve to a scope the session already occupies; it can never invent one.
    """
    resolved: dict[str, str] = {}
    for key, value in operation.items():
        if key in session and str(session[key]) == value:
            resolved[key] = value
            continue
        candidates = [k for k, v in session.items() if str(v) == value and k not in operation]
        if len(candidates) != 1:
            return None
        resolved[candidates[0]] = value
    return resolved


def _link_evidence(
    conn: psycopg.Connection, memory_id: str, evidence: list[dict[str, Any]]
) -> None:
    """Attach cited spans to a memory, idempotently.

    Idempotent because dedup links the same evidence to an existing memory, and
    a replay can re-cite a span that is already recorded.
    """
    if not evidence:
        return
    # `executemany` is a cursor method in psycopg; a connection only has
    # `execute`, so batching these goes through an explicit cursor.
    with conn.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO memory_sources(memory_id,message_id) VALUES (%s,%s)
               ON CONFLICT DO NOTHING""",
            [(memory_id, item["message_id"]) for item in evidence],
        )
        cursor.executemany(
            """INSERT INTO memory_evidence
               (memory_id,message_id,start_char,end_char,excerpt_sha256)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT DO NOTHING""",
            [
                (
                    memory_id,
                    item["message_id"],
                    item["start_char"],
                    item["end_char"],
                    item["excerpt_sha256"],
                )
                for item in evidence
            ],
        )
        cursor.executemany(
            """INSERT INTO memory_revision_evidence
               (memory_id,revision,message_id,start_char,end_char)
               SELECT id,revision,%s,%s,%s FROM memories WHERE id=%s
               ON CONFLICT DO NOTHING""",
            [(e["message_id"], e["start_char"], e["end_char"], memory_id) for e in evidence],
        )


def _resolve_routing(
    conn: psycopg.Connection,
    op: judge.Op,
    *,
    entity_map: dict[str, str],
    session_scope_id: str,
    own_scope_id: str,
    team_scope_id: str | None,
    writable_scope_ids: Sequence[str],
) -> tuple[str, str | None, str | None]:
    """Where this operation writes, what it is about, and any unresolved name.

    The rules, in the order they apply:

    * A fact about a listed teammate goes to the team scope with that person as
      subject. It is deliberately not private: the team's picture of a person
      is shared, and the person themselves can see and delete it.
    * A named scope must be one the speaker may write to. Otherwise the
      operation is refused rather than quietly redirected, because a fact
      written to the wrong scope is either a leak or a loss.
    * An unlisted person's name resolves to nothing, so the fact stays private
      and the name is returned for a needs-attention item. Guessing which
      teammate was meant would put a claim on the wrong person's profile.
    """
    subject_id = entity_map.get(str(op.subject)) if op.subject is not None else None
    unresolved: str | None = None
    if subject_id is None and op.subject_name:
        resolved = entities.resolve_alias(conn, op.subject_name)
        if resolved is not None:
            subject_id = str(resolved["id"])
        else:
            unresolved = op.subject_name.strip()

    if op.scope is not None:
        scope_id = entity_map.get(str(op.scope))
        if scope_id is None:
            raise LookupError("unknown_entity")
    elif subject_id is not None and subject_id != own_scope_id and team_scope_id:
        # A fact about somebody else belongs where the team can see it.
        scope_id = team_scope_id
    else:
        scope_id = session_scope_id

    if unresolved is not None:
        scope_id = own_scope_id
        subject_id = None
    if scope_id not in set(writable_scope_ids):
        raise PermissionError("scope_not_allowed")
    return scope_id, subject_id, unresolved


def apply_ops(
    conn: psycopg.Connection,
    *,
    ops: list[judge.Op],
    user_id: str,
    session_scope_id: str,
    own_scope_id: str,
    team_scope_id: str | None,
    writable_scope_ids: Sequence[str],
    agent_id: str,
    context: dict[str, Any],
    judge_run_id: int,
    source_message_ids: list[int],
    entity_map: dict[str, str] | None = None,
    extraction_version: str = judge.PROMPT_VERSION,
    dedup_hits: dict[int, DedupTarget] | None = None,
) -> ExtractionOutcome:
    maintenance.require_write(conn)
    store.require_scope_write(conn, user_id=user_id, scope_id=session_scope_id)
    writable_scope_ids = sorted(set(writable_scope_ids) & entities.writable_by(conn, user_id))
    outcome = ExtractionOutcome(judge_run_id=judge_run_id)
    allowed = set(source_message_ids)
    entity_map = entity_map or {}
    for index, op in enumerate(ops):
        validated = _validated_evidence(conn, op, allowed_message_ids=allowed)
        if validated is None:
            outcome.reject(op, "evidence_invalid")
            continue
        evidence, roles = validated
        if not provenance.may_write(op=op.op, roles=roles):
            outcome.reject(op, "assistant_only_source")
            continue
        op_context = reconcile_context(op.context or {}, context)
        if op_context is None:
            outcome.reject(op, "context_mismatch")
            continue
        op.context = op_context
        try:
            scope_id, subject_id, unresolved = _resolve_routing(
                conn,
                op,
                entity_map=entity_map,
                session_scope_id=session_scope_id,
                own_scope_id=own_scope_id,
                team_scope_id=team_scope_id,
                writable_scope_ids=writable_scope_ids,
            )
            store.require_scope_write(conn, user_id=user_id, scope_id=scope_id)
        except LookupError:
            outcome.reject(op, "unknown_entity")
            continue
        except (PermissionError, ScopeForbidden):
            outcome.reject(op, "scope_not_allowed")
            continue
        op.scope_id = scope_id
        source_role = provenance.source_role_for(roles)

        if op.op == "ADD":
            target = (dedup_hits or {}).get(index)
            if target is not None:
                row = conn.execute(
                    """SELECT id FROM memories
                        WHERE id=%s AND scope_id=%s AND status='active' AND revision=%s
                        AND context=%s AND subject_id IS NOT DISTINCT FROM %s::uuid
                        AND kind=%s AND source_role=%s
                        AND valid_until IS NOT DISTINCT FROM %s::timestamptz
                        AND (valid_until IS NULL OR valid_until > now()) FOR UPDATE""",
                    (
                        target.id,
                        scope_id,
                        target.revision,
                        Jsonb(op_context),
                        subject_id,
                        op.kind or "fact",
                        source_role,
                        op.valid_until,
                    ),
                ).fetchone()
                # The plan was computed outside this transaction; a vanished
                # target simply means the ADD proceeds normally below.
                if row is not None:
                    _link_evidence(conn, target.id, evidence)
                    outcome.deduplicated += 1
                    continue
            memory_id = store.add_memory(
                conn,
                scope_id=scope_id,
                subject_id=subject_id,
                author_id=user_id,
                text=op.text or "",
                kind=op.kind or "fact",
                context=op.context or {},
                tags=op.tags or [],
                agent_id=agent_id,
                importance=op.importance or 0.6,
                confidence=op.confidence or 0.9,
                valid_until=op.valid_until,
                extraction_version=extraction_version,
                judge_run_id=judge_run_id,
                source_role=source_role,
                # Extraction is automatic, so the fact is live but unconfirmed.
                review_status="pending",
            )
            _link_evidence(conn, memory_id, evidence)
            outcome.added += 1
            if unresolved is not None:
                _flag_unresolved_mention(
                    conn,
                    user_id=user_id,
                    scope_id=scope_id,
                    memory_id=memory_id,
                    name=unresolved,
                )
                outcome.unresolved_mentions += 1
            continue

        existing = conn.execute(
            """SELECT * FROM memories
                WHERE id=%s AND scope_id = ANY(%s) AND status='active'""",
            (op.id, [uuid.UUID(str(scope)) for scope in writable_scope_ids]),
        ).fetchone()
        if existing is None:
            outcome.skipped += 1
            continue
        if str(existing["scope_id"]) != scope_id:
            outcome.reject(op, "target_scope_mismatch")
            continue
        existing_context = dict(existing["context"] or {})
        if existing_context != (op.context or {}):
            outcome.reject(op, "target_context_mismatch")
            continue
        if op.op == "DELETE":
            store.set_memory_status(
                conn,
                memory_id=str(existing["id"]),
                scopes=writable_scope_ids,
                status="archived",
                expected_revision=int(existing["revision"]),
            )
            outcome.deleted += 1
            continue

        store.update_memory(
            conn,
            memory_id=str(existing["id"]),
            scopes=writable_scope_ids,
            expected_revision=int(existing["revision"]),
            text=op.text or existing["text"],
            kind=op.kind or existing["kind"],
            context=existing_context,
            tags=list(existing["tags"] or []),
            importance=op.importance if op.importance is not None else existing["importance"],
            confidence=op.confidence if op.confidence is not None else existing["confidence"],
            # An UPDATE that says nothing about validity must not clear an
            # existing expiry; explicit clearing stays on PATCH clear_valid_until.
            valid_until=op.valid_until if op.valid_until is not None else existing["valid_until"],
            extraction_version=extraction_version,
            judge_run_id=judge_run_id,
            source_role=source_role,
            # A confirmed fact that the extractor rewrites goes back for review:
            # the new text is live, and the previous wording is one revision
            # back for whoever confirms it.
            review_status="pending",
        )
        _link_evidence(conn, str(existing["id"]), evidence)
        outcome.updated += 1
    return outcome


def _flag_unresolved_mention(
    conn: psycopg.Connection,
    *,
    user_id: str,
    scope_id: str,
    memory_id: str,
    name: str,
) -> None:
    """Queue a name nobody could resolve for a human to place.

    The fact is kept -- it was stated -- but it stays private and unattributed
    until somebody says who was meant, because attaching it to the wrong person
    is worse than leaving it unattached.
    """
    conn.execute(
        """INSERT INTO needs_attention (id,user_id,scope_id,kind,ref_memory_id,payload)
           VALUES (%s,%s,%s,'unresolved_mention',%s,%s)""",
        (str(uuid.uuid4()), user_id, scope_id, memory_id, Jsonb({"name": name})),
    )


def run_extraction(
    conn: psycopg.Connection,
    *,
    session_id: str,
    agent_id: str,
    api_key: str,
    gemini_api_key: str,
    project: str,
    location: str,
    monthly_limit_usd: float,
    model: str,
    job_id: str | None = None,
    force: bool = False,
    client: Any = None,
    embedder: Any = None,
    dedup_cosine: float | None = None,
    semantic: SemanticBlocks | None = None,
    guard: Callable[[], None] | None = None,
) -> ExtractionOutcome:
    """Extract one window of one session, on behalf of that session's user.

    The session is the authorization anchor: user and scope come from the row,
    never from a parameter, so nothing a client sends can redirect extraction
    into somebody else's memory.
    """
    try:
        session = session_identity(conn, session_id)
    except ValueError:
        return ExtractionOutcome(error="unknown_session")
    if session["agent_id"] != agent_id:
        return ExtractionOutcome(error="session_identity_mismatch")
    user_id = str(session["user_id"])
    session_scope_id = str(session["scope_id"])
    try:
        with conn.transaction():
            store.require_scope_write(conn, user_id=user_id, scope_id=session_scope_id)
    except ScopeForbidden:
        return ExtractionOutcome(error="scope_not_allowed")
    own = entities.own_entity(conn, user_id)
    if own is None:
        return ExtractionOutcome(error="user_has_no_scope")
    own_scope_id = str(own["id"])
    team = entities.team(conn)
    team_scope_id = str(team["id"]) if team else None
    writable = sorted(entities.writable_by(conn, user_id))
    readable = sorted(str(row["id"]) for row in entities.visible_to(conn, user_id))

    window = claim_window(conn, session_id=session_id, job_id=job_id or "inline")
    if not window:
        return ExtractionOutcome()
    window_text = "\n".join(str(row["content"] or "") for row in window if row["role"] == "user")
    if not force and not judge.should_extract(
        # Every user turn in the window, not just the last message: an explicit
        # "remember this" in the middle of a batch was invisible whenever the
        # final claimed message happened to be an assistant turn.
        messages_since_last=len(window),
        session_closed=False,
        text=window_text,
    ):
        release_window(conn, window)
        return ExtractionOutcome(claimed=len(window), declined=True, windows=1)
    if not any(row["role"] == "user" for row in window):
        try:
            with conn.transaction():
                _require_window(conn, window, guard=guard)
                store.require_scope_write(conn, user_id=user_id, scope_id=session_scope_id)
                _mark_processed(conn, window)
        except ScopeForbidden:
            release_window(conn, window)
            return ExtractionOutcome(error="scope_not_allowed", claimed=len(window), windows=1)
        except ExtractionLeaseLost:
            return ExtractionOutcome(error="extraction_lease_lost", claimed=len(window), windows=1)
        return ExtractionOutcome(skipped=len(window), claimed=len(window), windows=1)
    context = dict(session["context"] or {})
    candidates = find_candidates(
        conn,
        scope_id=session_scope_id,
        allowed_scope_ids=readable,
        context=context,
        client=client,
        embedder=embedder,
        window_text=window_text,
    )
    known_entities = entities.for_prompt(conn, user_id=user_id)

    # The window's own recording date is the prompt's temporal anchor. Without
    # it "last month" in a backfilled window resolves against nothing (v7) or
    # against today (wrong for every imported transcript).
    session_date = (iso(window[0]["created_at"]) or "")[:10] or None

    # This call performs only short reservation/log transactions internally.
    result = judge.extract(
        conn,
        window=window,
        candidates=candidates,
        entities=known_entities,
        monthly_limit_usd=monthly_limit_usd,
        api_key=api_key,
        gemini_api_key=gemini_api_key,
        project=project,
        location=location,
        model=model,
        context=context,
        session_date=session_date,
        agent_id=agent_id,
        user_id=user_id,
        job_id=job_id,
    )
    outcome = ExtractionOutcome(
        judge_run_id=result.judge_run_id,
        cost_usd=result.cost_usd,
        error=result.error,
        claimed=len(window),
        windows=1,
    )
    if result.error or result.judge_run_id is None:
        release_window(conn, window)
        return outcome
    # Embedding and the index round-trip happen before the write transaction,
    # for the same reason the provider call does: nothing slow may hold a write
    # transaction open.
    # Resolve the same routing and citation constraints before any extra egress.
    # Preserve operation indexes; invalid operations are still rejected by apply_ops.
    prepared = list(result.ops)
    eligible: set[int] = set()
    subjects: dict[int, str | None] = {}
    source_roles: dict[int, str] = {}
    claims: list[dict[str, Any]] = []
    allowed_messages = {int(row["id"]) for row in window}
    by_message = {int(row["id"]): row for row in window}
    for index, op in enumerate(result.ops):
        if op.op not in {"ADD", "UPDATE"}:
            continue
        evidence = _validated_evidence(conn, op, allowed_message_ids=allowed_messages)
        op_context = reconcile_context(op.context or {}, context)
        if (
            evidence is None
            or op_context is None
            or not provenance.may_write(op=op.op, roles=evidence[1])
        ):
            continue
        try:
            target_scope, subject, unresolved = _resolve_routing(
                conn,
                op,
                entity_map=result.entity_map,
                session_scope_id=session_scope_id,
                own_scope_id=own_scope_id,
                team_scope_id=team_scope_id,
                writable_scope_ids=writable,
            )
        except (LookupError, PermissionError):
            continue
        prepared[index] = replace(op, scope_id=target_scope, context=op_context)
        subjects[index] = subject
        source_roles[index] = provenance.source_role_for(evidence[1])
        if unresolved is None:
            eligible.add(index)
        if semantic is not None and semantic.support != "off":
            claims.append(
                {
                    "claim": op.text,
                    "user_spans": [
                        by_message[e["message_id"]]["content"][e["start_char"] : e["end_char"]]
                        for e in evidence[0]
                        if by_message[e["message_id"]]["role"] == "user"
                    ],
                    "context": {
                        "recording_date": session_date,
                        "entities": known_entities,
                        "conversation": [{"role": r["role"], "text": r["content"]} for r in window],
                    },
                }
            )
    support_counts = semantic.inspect_support(claims) if semantic is not None else {}
    dedup_hits = plan_dedup(
        conn,
        ops=prepared,
        scope_id=session_scope_id,
        client=client,
        embedder=embedder,
        threshold=dedup_cosine,
        subjects=subjects,
        source_roles=source_roles,
        eligible=eligible,
        semantic=semantic,
    )
    try:
        with conn.transaction():
            _require_window(conn, window, guard=guard)
            applied = apply_ops(
                conn,
                ops=result.ops,
                user_id=user_id,
                session_scope_id=session_scope_id,
                own_scope_id=own_scope_id,
                team_scope_id=team_scope_id,
                writable_scope_ids=writable,
                agent_id=agent_id,
                context=context,
                judge_run_id=result.judge_run_id,
                source_message_ids=[int(row["id"]) for row in window],
                entity_map=result.entity_map,
                dedup_hits=dedup_hits,
            )
            _mark_processed(conn, window)
    except ExtractionLeaseLost:
        outcome.error = "extraction_lease_lost"
        return outcome
    except ScopeForbidden:
        release_window(conn, window)
        outcome.error = "scope_not_allowed"
        return outcome
    for dropped in result.unknown_candidates:
        applied.rejected += 1
        applied.rejections.append({**dropped, "reason": "unknown_candidate"})
    for dropped in result.unknown_entities:
        applied.rejected += 1
        applied.rejections.append({**dropped, "reason": "unknown_entity"})
    applied.cost_usd = result.cost_usd
    applied.judge_run_id = result.judge_run_id
    applied.claimed = len(window)
    applied.windows = 1
    applied.semantic_support = support_counts
    return applied


class ExtractionLeaseLost(RuntimeError):
    """The provider's input window is no longer ours to commit."""


def _require_window(
    conn: psycopg.Connection, window: list[Row], *, guard: Callable[[], None] | None = None
) -> None:
    maintenance.require_write(conn)
    if guard is not None:
        guard()
    rows = conn.execute(
        """SELECT id,claim_token,claim_expires_at,processed FROM messages
           WHERE id=ANY(%s) ORDER BY id FOR UPDATE""",
        ([int(row["id"]) for row in window],),
    ).fetchall()
    claims = {int(row["id"]): row["claim_token"] for row in window}
    now = utcnow()
    if len(rows) != len(window) or any(
        row["processed"]
        or row["claim_token"] != claims[int(row["id"])]
        or row["claim_expires_at"] is None
        or row["claim_expires_at"] <= now
        for row in rows
    ):
        raise ExtractionLeaseLost("extraction_lease_lost")


def _mark_processed(conn: psycopg.Connection, window: list[Row]) -> None:
    """Retire a leased window, matching on the claim token we still hold.

    The token in the predicate is what makes this safe after a lease expiry: if
    another job has since taken the window, this update touches nothing rather
    than marking somebody else's work done.
    """
    pairs = [(int(row["id"]), row["claim_token"]) for row in window]
    changed = conn.execute(
        """UPDATE messages SET processed=true,claim_token=NULL,claim_expires_at=NULL
             WHERE (id, claim_token) IN (
                 SELECT unnest(%s::bigint[]), unnest(%s::text[])
             )""",
        ([pair[0] for pair in pairs], [pair[1] for pair in pairs]),
    ).rowcount
    if changed != len(window):
        raise ExtractionLeaseLost("extraction_lease_lost")


def run_session_extraction(
    conn: psycopg.Connection,
    *,
    max_windows: int = 1,
    cancelled: Any = None,
    **kwargs: Any,
) -> ExtractionOutcome:
    """Drain up to `max_windows` windows of one session, then stop.

    One job used to process exactly one ten-message window and return, and
    nothing re-queued it on success. The batch evidence endpoint queues one job
    per session per request while the Claude Code hook posts in hundred-event
    chunks, so a long session left almost all of its messages unextracted
    indefinitely -- they were never claimed again.

    Stops on the first window that makes no progress: nothing left to claim, a
    refusal by the gate, a provider error, or cooperative cancellation. Each
    window is a separate provider call, so `max_windows` must not exceed the
    job's `call_limit`.
    """
    total = ExtractionOutcome()
    for _ in range(max(1, max_windows)):
        if cancelled is not None and cancelled():
            break
        outcome = run_extraction(conn, **kwargs)
        total.absorb(outcome)
        if outcome.claimed == 0 or outcome.declined or outcome.error:
            break
    return total
