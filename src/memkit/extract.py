"""Short-transaction, evidence-precise memory extraction."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from . import judge, provenance, store
from .db import transaction, utcnow

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
        }


def messages_since_last(conn: sqlite3.Connection, session_id: str) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=? AND processed=0",
            (session_id,),
        ).fetchone()[0]
    )


def unprocessed_window(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM messages WHERE session_id=? AND processed=0
            ORDER BY id LIMIT ?""",
        (session_id, WINDOW_SIZE),
    ).fetchall()


def claim_window(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    job_id: str,
    lease_seconds: int = 300,
) -> list[sqlite3.Row]:
    """Atomically lease one exact message range so provider work is never duplicated."""
    now = utcnow()
    expires = (
        (datetime.now(UTC) + timedelta(seconds=lease_seconds))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    token = f"{job_id}:{uuid.uuid4()}"
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """UPDATE messages SET claim_token=NULL,claim_expires_at=NULL
                 WHERE processed=0 AND claim_expires_at IS NOT NULL AND claim_expires_at<=?""",
            (now,),
        )
        ids = [
            int(row[0])
            for row in conn.execute(
                """SELECT id FROM messages
                     WHERE session_id=? AND processed=0 AND claim_token IS NULL
                     ORDER BY id LIMIT ?""",
                (session_id, WINDOW_SIZE),
            ).fetchall()
        ]
        if not ids:
            conn.execute("COMMIT")
            return []
        placeholders = ",".join("?" for _ in ids)
        changed = conn.execute(
            f"""UPDATE messages SET claim_token=?,claim_expires_at=?
                  WHERE id IN ({placeholders}) AND processed=0 AND claim_token IS NULL""",
            (token, expires, *ids),
        ).rowcount
        if changed != len(ids):
            conn.execute("ROLLBACK")
            return []
        conn.execute("COMMIT")
        return conn.execute(
            f"SELECT * FROM messages WHERE id IN ({placeholders}) ORDER BY id", ids
        ).fetchall()
    except Exception:
        conn.execute("ROLLBACK")
        raise


def release_window(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> None:
    claims = {str(row["claim_token"]) for row in rows if row["claim_token"]}
    if not claims:
        return
    with transaction(conn):
        conn.executemany(
            """UPDATE messages SET claim_token=NULL,claim_expires_at=NULL
                 WHERE claim_token=? AND processed=0""",
            [(claim,) for claim in claims],
        )


def session_context(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT context_json FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row is None:
        raise ValueError("unknown session")
    return json.loads(row["context_json"] or "{}")


def find_candidates(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    context: dict[str, Any],
    limit: int = 10,
    client: Any = None,
    embedder: Any = None,
    window_text: str = "",
) -> list[dict[str, Any]]:
    """Candidates the judge may UPDATE/DELETE — and must not re-ADD.

    Two arms, and the order between them is load-bearing. Recency in the exact
    session context comes first and keeps RECENCY_SLOTS of the limit: those are
    the only candidates an operation may legally target, since apply_ops rejects
    any UPDATE/DELETE whose target context differs from the op's. The dense arm
    then fills what is left with a search over the window's user text across
    *all* contexts, because the near-duplicate worth noticing usually lives
    under a different or empty context, which exact-context recency can never
    surface — measured on this corpus as a 0.9821-cosine pair that never merged.
    Cross-context candidates inform dedup only.

    SQLite stays authoritative: a dense hit is used only after its row is
    re-read and confirmed active.
    """

    def _shape(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "text": row["text"],
            "importance": row["importance"],
            "context": json.loads(row["context_json"] or "{}"),
        }

    merged: dict[str, dict[str, Any]] = {}

    # Same-context recency first, and it keeps its slots. Dense hits used to be
    # inserted ahead of these and could fill every slot on their own, which left
    # the model with nothing it was allowed to UPDATE or DELETE: apply_ops
    # rejects any operation whose target context differs from the op's.
    rows = conn.execute(
        """SELECT * FROM memories
            WHERE owner_id=? AND status='active' AND context_json=?
            ORDER BY updated_at DESC,id LIMIT ?""",
        (owner_id, json.dumps(context, ensure_ascii=False, sort_keys=True), RECENCY_SLOTS),
    ).fetchall()
    for row in rows:
        merged[row["id"]] = _shape(row)

    if client is not None and embedder is not None and window_text.strip() and len(merged) < limit:
        from . import vectors

        hits = vectors.search(
            client,
            vectors.MEMORIES,
            embedder.encode_one(window_text),
            limit=limit - len(merged),
            must=[
                vectors.keyword("owner_id", owner_id),
                vectors.keyword("status", "active"),
            ],
            exclude_ids=list(merged),
        )
        for hit in hits:
            row = conn.execute(
                "SELECT * FROM memories WHERE id=? AND owner_id=? AND status='active'",
                (str(hit.id), owner_id),
            ).fetchone()
            if row is not None:
                merged.setdefault(row["id"], _shape(row))
    return list(merged.values())[:limit]


def _validated_evidence(
    conn: sqlite3.Connection,
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
        row = conn.execute("SELECT role,content FROM messages WHERE id=?", (message_id,)).fetchone()
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


def plan_dedup(
    conn: sqlite3.Connection,
    *,
    ops: list[judge.Op],
    owner_id: str,
    client: Any,
    embedder: Any,
    threshold: float | None,
) -> dict[int, str]:
    """Map op index → existing memory id for ADD ops that duplicate the store.

    Runs BEFORE the write transaction on purpose: embedding and the Qdrant
    round-trip must not extend a SQLite write lock (the same discipline ADR
    0052 applies to provider calls). apply_ops re-reads each planned target
    inside the transaction and falls back to a normal ADD if it vanished.

    Same-context only (`context_json` byte equality on the canonical encoding):
    by this repo's own model a fact duplicated across contexts is two facts.
    At the configured 0.90 only near-verbatim text clears the bar — a genuine
    paraphrase measures ≈0.898 on this corpus (see config.dedup_cosine).
    """
    if client is None or embedder is None or threshold is None:
        return {}
    from . import vectors

    planned: dict[int, str] = {}
    for index, op in enumerate(ops):
        if op.op != "ADD" or not (op.text or "").strip():
            continue
        op_context = json.dumps(op.context or {}, ensure_ascii=False, sort_keys=True)
        hits = vectors.search(
            client,
            vectors.MEMORIES,
            embedder.encode_one(op.text),
            limit=3,
            must=[
                vectors.keyword("owner_id", owner_id),
                vectors.keyword("status", "active"),
            ],
        )
        for hit in hits:
            if float(hit.score) < threshold:
                continue
            row = conn.execute(
                """SELECT id,context_json FROM memories
                    WHERE id=? AND owner_id=? AND status='active'""",
                (str(hit.id), owner_id),
            ).fetchone()
            if row is not None and (row["context_json"] or "{}") == op_context:
                planned[index] = row["id"]
                break
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
    conn: sqlite3.Connection, memory_id: str, evidence: list[dict[str, Any]]
) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO memory_sources(memory_id,message_id) VALUES (?,?)",
        [(memory_id, item["message_id"]) for item in evidence],
    )
    conn.executemany(
        """INSERT OR IGNORE INTO memory_evidence
           (memory_id,message_id,start_char,end_char,excerpt_sha256)
           VALUES (?,?,?,?,?)""",
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


def apply_ops(
    conn: sqlite3.Connection,
    *,
    ops: list[judge.Op],
    owner_id: str,
    agent_id: str,
    context: dict[str, Any],
    judge_run_id: int,
    source_message_ids: list[int],
    extraction_version: str = judge.PROMPT_VERSION,
    dedup_hits: dict[int, str] | None = None,
) -> ExtractionOutcome:
    outcome = ExtractionOutcome(judge_run_id=judge_run_id)
    allowed = set(source_message_ids)
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
        source_role = provenance.source_role_for(roles)
        if op.op == "ADD":
            existing_id = (dedup_hits or {}).get(index)
            if existing_id is not None:
                row = conn.execute(
                    "SELECT id FROM memories WHERE id=? AND owner_id=? AND status='active'",
                    (existing_id, owner_id),
                ).fetchone()
                # The plan was computed outside this transaction; a vanished
                # target simply means the ADD proceeds normally below.
                if row is not None:
                    _link_evidence(conn, existing_id, evidence)
                    outcome.deduplicated += 1
                    continue
            memory_id = store.add_memory(
                conn,
                owner_id=owner_id,
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
            )
            _link_evidence(conn, memory_id, evidence)
            outcome.added += 1
            continue

        existing = conn.execute(
            "SELECT * FROM memories WHERE id=? AND owner_id=? AND status='active'",
            (op.id, owner_id),
        ).fetchone()
        if existing is None:
            outcome.skipped += 1
            continue
        existing_context = json.loads(existing["context_json"] or "{}")
        if existing_context != (op.context or {}):
            outcome.reject(op, "target_context_mismatch")
            continue
        if op.op == "DELETE":
            store.set_memory_status(
                conn,
                memory_id=existing["id"],
                owner_id=owner_id,
                status="archived",
                expected_revision=int(existing["revision"]),
            )
            outcome.deleted += 1
            continue

        store.update_memory(
            conn,
            memory_id=existing["id"],
            owner_id=owner_id,
            expected_revision=int(existing["revision"]),
            text=op.text or existing["text"],
            kind=op.kind or existing["kind"],
            context=existing_context,
            tags=json.loads(existing["tags_json"] or "[]"),
            importance=op.importance if op.importance is not None else existing["importance"],
            confidence=op.confidence if op.confidence is not None else existing["confidence"],
            # An UPDATE that says nothing about validity must not clear an
            # existing expiry; explicit clearing stays on PATCH clear_valid_until.
            valid_until=op.valid_until if op.valid_until is not None else existing["valid_until"],
            extraction_version=extraction_version,
            judge_run_id=judge_run_id,
            source_role=source_role,
        )
        _link_evidence(conn, existing["id"], evidence)
        outcome.updated += 1
    return outcome


def run_extraction(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    owner_id: str,
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
) -> ExtractionOutcome:
    session = conn.execute(
        "SELECT owner_id,agent_id FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    if session is None:
        return ExtractionOutcome(error="unknown_session")
    if session["owner_id"] != owner_id or session["agent_id"] != agent_id:
        return ExtractionOutcome(error="session_identity_mismatch")
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
        with transaction(conn):
            conn.executemany(
                """UPDATE messages SET processed=1,claim_token=NULL,claim_expires_at=NULL
                     WHERE id=? AND claim_token=?""",
                [(row["id"], row["claim_token"]) for row in window],
            )
        return ExtractionOutcome(skipped=len(window), claimed=len(window), windows=1)
    context = session_context(conn, session_id)
    candidates = find_candidates(
        conn,
        owner_id=owner_id,
        context=context,
        client=client,
        embedder=embedder,
        window_text=window_text,
    )

    # The window's own recording date is the prompt's temporal anchor. Without
    # it "last month" in a backfilled window resolves against nothing (v7) or
    # against today (wrong for every imported transcript).
    session_date = (str(window[0]["created_at"] or ""))[:10] or None

    # This call performs only short reservation/log transactions internally.
    result = judge.extract(
        conn,
        window=window,
        candidates=candidates,
        monthly_limit_usd=monthly_limit_usd,
        api_key=api_key,
        gemini_api_key=gemini_api_key,
        project=project,
        location=location,
        model=model,
        context=context,
        session_date=session_date,
        agent_id=agent_id,
        owner_id=owner_id,
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
    # for the same reason the provider call does: nothing slow may hold the
    # write lock.
    dedup_hits = plan_dedup(
        conn,
        ops=result.ops,
        owner_id=owner_id,
        client=client,
        embedder=embedder,
        threshold=dedup_cosine,
    )
    with transaction(conn):
        applied = apply_ops(
            conn,
            ops=result.ops,
            owner_id=owner_id,
            agent_id=agent_id,
            context=context,
            judge_run_id=result.judge_run_id,
            source_message_ids=[int(row["id"]) for row in window],
            dedup_hits=dedup_hits,
        )
        conn.executemany(
            """UPDATE messages SET processed=1,claim_token=NULL,claim_expires_at=NULL
                 WHERE id=? AND claim_token=?""",
            [(row["id"], row["claim_token"]) for row in window],
        )
    for dropped in result.unknown_candidates:
        applied.rejected += 1
        applied.rejections.append({**dropped, "reason": "unknown_candidate"})
    applied.cost_usd = result.cost_usd
    applied.judge_run_id = result.judge_run_id
    applied.claimed = len(window)
    applied.windows = 1
    return applied


def run_session_extraction(
    conn: sqlite3.Connection,
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
