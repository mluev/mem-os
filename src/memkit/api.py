"""Strict, single-owner HTTP API for memory, evidence, and generic records."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (
    consolidate,
    extract,
    jobs,
    outbox,
    platform,
    privacy,
    profiles,
    reextract,
    reindex,
    retrieval,
    store,
    vectors,
)
from .config import Settings, get_settings
from .db import ConnectionPool, ensure_owner, init_db, transaction, utcnow
from .embed import get_embedder

logger = logging.getLogger(__name__)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
Kind = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MessageIn(StrictModel):
    session_id: Identifier
    agent_id: Identifier = "chat"
    role: Literal["user", "assistant", "tool"]
    content: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000)
    ]
    external_source: Identifier | None = None
    external_id: Identifier | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    created_at: AwareDatetime | None = None


class MessageOut(StrictModel):
    message_id: int
    stored: Literal[True] = True
    indexed: bool
    index_status: Literal["complete", "pending", "not_applicable"]
    index_job_id: str | None = None
    extraction_job_id: str | None = None
    deduplicated: bool = False
    redacted: bool = False


class EvidenceBatchIn(StrictModel):
    events: list[MessageIn] = Field(min_length=1, max_length=100)


class MemoryIn(StrictModel):
    text: ShortText
    kind: Kind
    context: dict[str, Any] = Field(default_factory=dict)
    tags: list[Kind] = Field(default_factory=list, max_length=20)
    agent_id: Identifier | None = None
    importance: float = Field(default=0.6, ge=0, le=1)
    confidence: float = Field(default=0.9, ge=0, le=1)
    valid_until: AwareDatetime | None = None
    source_role: Literal["user", "assistant", "agent", "tool", "manual"]


class MemoryPatch(StrictModel):
    expected_updated_at: AwareDatetime
    text: ShortText | None = None
    kind: Kind | None = None
    context: dict[str, Any] | None = None
    tags: list[Kind] | None = Field(default=None, max_length=20)
    importance: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    valid_until: AwareDatetime | None = None
    clear_valid_until: bool = False
    move_context: bool = False


class SearchIn(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8192)]
    filter: dict[str, Any] | None = None
    kinds: list[Kind] | None = None
    policy_id: str = "neutral-v1"
    include_untrusted: bool = False
    include_raw: bool = False
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    limit: int = Field(default=30, ge=1, le=200)


class FeedbackIn(StrictModel):
    memory_id: str
    query: str
    useful: bool | None = None
    correct: bool | None = None


class NamespaceIn(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    description: Annotated[str, StringConstraints(max_length=1000)] = ""


class CollectionIn(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    schema_: dict[str, Any] = Field(alias="schema")
    indexed_fields: list[str] = Field(default_factory=list, max_length=64)
    embedding_fields: list[str] = Field(default_factory=list, max_length=16)
    policy: dict[str, Any] = Field(default_factory=dict)


class RecordIn(StrictModel):
    value: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Identifier | None = None


class RecordPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    value: dict[str, Any]
    metadata: dict[str, Any] | None = None
    context: dict[str, Any] | None = None


class RecordSearchIn(StrictModel):
    filter: dict[str, Any] | None = None
    limit: int = Field(default=50, ge=1, le=500)
    cursor: str | None = None


class ProfileIn(StrictModel):
    stable_kinds: list[Kind] = Field(default_factory=lambda: ["identity", "preference"])
    dynamic_days: int = Field(default=30, ge=1, le=3650)
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    include_untrusted: bool = False


class EraseIn(StrictModel):
    confirm: Literal["ERASE ALL DATA"]


class ConsolidateIn(StrictModel):
    dry_run: bool = True


class LinkIn(StrictModel):
    from_ref: Identifier
    relation: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    to_ref: Identifier
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyIn(StrictModel):
    namespace: (
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
        | None
    ) = None
    kind: Literal["extraction", "retrieval", "retention", "consolidation"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    version: int = Field(ge=1)
    config: dict[str, Any]


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_runtime(settings: Settings) -> None:
    if settings.api_key == "change-me":
        raise RuntimeError("MEMKIT_API_KEY must be changed from the public default")
    loopback = settings.host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not settings.allow_remote:
        raise RuntimeError("remote binding requires MEMKIT_ALLOW_REMOTE=true")
    if not loopback and len(settings.api_key) < 32:
        raise RuntimeError("remote binding requires an API key of at least 32 characters")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _validate_runtime(settings)
    init_db(settings.db_path)
    app.state.db = ConnectionPool(settings.db_path)
    with transaction(app.state.db()):
        ensure_owner(app.state.db(), settings.owner_id, settings.owner_name)
    app.state.qdrant = vectors.get_client(settings.qdrant_url)
    vectors.ensure_collections(app.state.qdrant)
    app.state.embedder = get_embedder()
    app.state.embedder.load()
    outbox.drain(app.state.db(), app.state.qdrant, app.state.embedder, limit=500)
    yield
    app.state.db.close_all()
    app.state.qdrant.close()


_startup_settings = get_settings()
app = FastAPI(
    title="memkit",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _startup_settings.expose_docs else None,
    redoc_url="/redoc" if _startup_settings.expose_docs else None,
)
if _startup_settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_startup_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
    )


@app.middleware("http")
async def request_safety(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > 2_000_000
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "invalid content-length"})
        if too_large:
            return JSONResponse(status_code=413, content={"detail": "request body exceeds 2 MB"})
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
    )
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    )
    return response


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_key(
    x_api_key: Annotated[str | None, Depends(_api_key_header)] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(401, "invalid or missing X-API-Key")


def judge_configured(settings: Settings) -> bool:
    from . import judge

    if judge.provider_of(settings.judge_model) == "gemini":
        return bool(settings.gemini_api_key or settings.vertex_project)
    return bool(settings.anthropic_api_key)


def _outbox_state(
    conn: sqlite3.Connection, collection: str, entity_id: str | int
) -> tuple[bool, str | None]:
    row = conn.execute(
        """SELECT id,status FROM index_outbox WHERE collection=? AND entity_id=?
            ORDER BY id DESC LIMIT 1""",
        (collection, str(entity_id)),
    ).fetchone()
    if row is None:
        return True, None
    return row["status"] == "done", str(row["id"])


def _drain() -> None:
    outbox.drain(app.state.db(), app.state.qdrant, app.state.embedder, limit=100)


def _run_extraction(job_id: str) -> None:
    settings = get_settings()
    conn = app.state.db()
    try:
        job = jobs.claim(conn, job_id)
        if jobs.cancel_requested(conn, job_id):
            jobs.finish(conn, job_id, status="cancelled")
            return
        data = json.loads(job["input_json"])
        outcome = extract.run_extraction(
            conn,
            session_id=data["session_id"],
            owner_id=settings.owner_id,
            agent_id=data["agent_id"],
            api_key=settings.anthropic_api_key,
            gemini_api_key=settings.gemini_api_key,
            project=settings.vertex_project,
            location=settings.vertex_location,
            monthly_limit_usd=settings.monthly_cost_limit_usd,
            model=settings.judge_model,
            job_id=job_id,
            force=bool(data.get("force")),
        )
        _drain()
        jobs.finish(
            conn,
            job_id,
            status="failed" if outcome.error else "complete",
            result=outcome.as_dict(),
            error_code=outcome.error,
            error=outcome.error,
        )
    except Exception as exc:
        logger.exception("extraction job %s failed", job_id)
        jobs.finish(conn, job_id, status="failed", error_code="extraction_failed", error=str(exc))


def _queue_extraction(
    conn: sqlite3.Connection, *, session_id: str, agent_id: str, force: bool
) -> str:
    return jobs.create(
        conn,
        kind="extraction",
        input_data={"session_id": session_id, "agent_id": agent_id, "force": force},
        call_limit=1,
    )


@app.get("/healthz")
def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.get("/readyz")
def readyz() -> JSONResponse:
    database_ok = qdrant_ok = embedder_ok = False
    try:
        database_ok = app.state.db().execute("SELECT 1").fetchone()[0] == 1
        qdrant_ok = bool(app.state.qdrant.get_collections())
        embedder_ok = bool(app.state.embedder.ready)
    except Exception:
        pass
    ready = database_ok and qdrant_ok and embedder_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "ready": ready,
            "database": database_ok,
            "qdrant": qdrant_ok,
            "embedder": embedder_ok,
        },
    )


@app.post("/v1/evidence/events", dependencies=[Depends(require_key)], status_code=201)
@app.post(
    "/v1/messages", dependencies=[Depends(require_key)], status_code=201, include_in_schema=False
)
def post_message(body: MessageIn, background: BackgroundTasks) -> MessageOut:
    settings = get_settings()
    conn = app.state.db()
    try:
        with transaction(conn):
            message_id, deduplicated, redacted = store.add_message(
                conn,
                session_id=body.session_id,
                owner_id=settings.owner_id,
                agent_id=body.agent_id,
                role=body.role,
                content=body.content,
                external_source=body.external_source,
                external_id=body.external_id,
                context=body.context,
                created_at=_timestamp(body.created_at),
            )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _drain()
    indexed, index_job_id = _outbox_state(conn, vectors.RAW, message_id)
    applicable = body.role == "user" and len(body.content) >= store.MIN_INDEX_CHARS
    extraction_job_id = None
    pending = extract.messages_since_last(conn, body.session_id)
    if judge_configured(settings) and extract.judge.should_extract(
        messages_since_last=pending,
        session_closed=False,
        text=body.content,
    ):
        extraction_job_id = _queue_extraction(
            conn, session_id=body.session_id, agent_id=body.agent_id, force=True
        )
        background.add_task(_run_extraction, extraction_job_id)
    return MessageOut(
        message_id=message_id,
        indexed=indexed if applicable else True,
        index_status=("complete" if indexed else "pending") if applicable else "not_applicable",
        index_job_id=index_job_id,
        extraction_job_id=extraction_job_id,
        deduplicated=deduplicated,
        redacted=redacted,
    )


@app.post("/v1/evidence/events:batch", dependencies=[Depends(require_key)], status_code=201)
def post_evidence_batch(body: EvidenceBatchIn, background: BackgroundTasks) -> dict[str, Any]:
    settings = get_settings()
    conn = app.state.db()
    stored: list[tuple[MessageIn, int, bool, bool]] = []
    try:
        with transaction(conn):
            for event in body.events:
                message_id, duplicate, redacted = store.add_message(
                    conn,
                    session_id=event.session_id,
                    owner_id=settings.owner_id,
                    agent_id=event.agent_id,
                    role=event.role,
                    content=event.content,
                    external_source=event.external_source,
                    external_id=event.external_id,
                    context=event.context,
                    created_at=_timestamp(event.created_at),
                )
                stored.append((event, message_id, duplicate, redacted))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _drain()
    results: list[dict[str, Any]] = []
    queued_sessions: set[tuple[str, str]] = set()
    for event, message_id, duplicate, redacted in stored:
        applicable = event.role == "user" and len(event.content) >= store.MIN_INDEX_CHARS
        indexed, index_job_id = _outbox_state(conn, vectors.RAW, message_id)
        results.append(
            MessageOut(
                message_id=message_id,
                indexed=indexed if applicable else True,
                index_status=("complete" if indexed else "pending")
                if applicable
                else "not_applicable",
                index_job_id=index_job_id,
                deduplicated=duplicate,
                redacted=redacted,
            ).model_dump()
        )
        queued_sessions.add((event.session_id, event.agent_id))
    if judge_configured(settings):
        for session_id, agent_id in queued_sessions:
            job_id = _queue_extraction(conn, session_id=session_id, agent_id=agent_id, force=False)
            background.add_task(_run_extraction, job_id)
    return {"items": results, "count": len(results)}


@app.post("/v1/sessions/{session_id}/close", dependencies=[Depends(require_key)], status_code=202)
def close_session(session_id: str, background: BackgroundTasks) -> dict[str, Any]:
    conn = app.state.db()
    row = conn.execute(
        "SELECT owner_id,agent_id FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown session")
    if row["owner_id"] != get_settings().owner_id:
        raise HTTPException(404, "unknown session")
    with transaction(conn):
        conn.execute(
            "UPDATE sessions SET ended_at=COALESCE(ended_at,?) WHERE id=?",
            (utcnow(), session_id),
        )
    if not judge_configured(get_settings()):
        return {"job_id": None, "status": "complete", "reason": "judge_not_configured"}
    job_id = _queue_extraction(conn, session_id=session_id, agent_id=row["agent_id"], force=True)
    background.add_task(_run_extraction, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.post("/v1/memories", dependencies=[Depends(require_key)], status_code=201)
def post_memory(body: MemoryIn) -> dict[str, Any]:
    conn = app.state.db()
    with transaction(conn):
        memory_id = store.add_memory(
            conn,
            owner_id=get_settings().owner_id,
            text=body.text,
            kind=body.kind,
            context=body.context,
            tags=list(body.tags),
            agent_id=body.agent_id,
            importance=body.importance,
            confidence=body.confidence,
            valid_until=_timestamp(body.valid_until),
            source_role=body.source_role,
        )
    _drain()
    indexed, outbox_id = _outbox_state(conn, vectors.MEMORIES, memory_id)
    return {"id": memory_id, "stored": True, "indexed": indexed, "index_job_id": outbox_id}


@app.patch("/v1/memories/{memory_id}", dependencies=[Depends(require_key)])
def patch_memory(memory_id: str, body: MemoryPatch) -> dict[str, Any]:
    conn = app.state.db()
    row = conn.execute(
        "SELECT * FROM memories WHERE id=? AND owner_id=?",
        (memory_id, get_settings().owner_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown memory")
    if datetime.fromisoformat(row["updated_at"]) != body.expected_updated_at:
        raise HTTPException(409, "memory changed; reload and retry")
    current_context = json.loads(row["context_json"] or "{}")
    if body.context is not None and body.context != current_context and not body.move_context:
        raise HTTPException(422, "context changes require move_context=true")
    values = {
        "text": body.text if body.text is not None else row["text"],
        "kind": body.kind if body.kind is not None else row["kind"],
        "importance": body.importance if body.importance is not None else row["importance"],
        "confidence": body.confidence if body.confidence is not None else row["confidence"],
        "context_json": json.dumps(
            body.context if body.context is not None else current_context,
            ensure_ascii=False,
            sort_keys=True,
        ),
        "tags_json": json.dumps(
            body.tags if body.tags is not None else json.loads(row["tags_json"]), ensure_ascii=False
        ),
        "valid_until": None
        if body.clear_valid_until
        else (_timestamp(body.valid_until) if body.valid_until is not None else row["valid_until"]),
        "updated_at": utcnow(),
    }
    with transaction(conn):
        conn.execute(
            """UPDATE memories SET text=:text,kind=:kind,importance=:importance,
                confidence=:confidence,context_json=:context_json,tags_json=:tags_json,
                valid_until=:valid_until,updated_at=:updated_at WHERE id=:id""",
            {**values, "id": memory_id},
        )
        saved = conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        outbox.enqueue(
            conn,
            collection=vectors.MEMORIES,
            entity_id=memory_id,
            operation="upsert",
            payload=store.mem_payload(saved),
        )
    _drain()
    return dict(saved)


@app.delete("/v1/memories/{memory_id}", dependencies=[Depends(require_key)])
def delete_memory(memory_id: str) -> dict[str, Any]:
    conn = app.state.db()
    with transaction(conn):
        changed = conn.execute(
            "UPDATE memories SET status='archived',updated_at=? WHERE id=? AND owner_id=?",
            (utcnow(), memory_id, get_settings().owner_id),
        ).rowcount
        if not changed:
            raise HTTPException(404, "unknown memory")
        outbox.enqueue(conn, collection=vectors.MEMORIES, entity_id=memory_id, operation="delete")
    _drain()
    return {"id": memory_id, "status": "archived"}


@app.get("/v1/memories", dependencies=[Depends(require_key)])
def list_memories(
    kind: str | None = None,
    status: Literal["active", "archived", "expired", "superseded"] = "active",
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
) -> dict[str, Any]:
    clauses = ["owner_id=?", "status=?"]
    params: list[Any] = [get_settings().owner_id, status]
    if kind:
        clauses.append("kind=?")
        params.append(kind)
    if status == "active":
        clauses.append("(valid_until IS NULL OR valid_until>?)")
        params.append(utcnow())
    if cursor:
        clauses.append("id>?")
        params.append(cursor)
    rows = (
        app.state.db()
        .execute(
            f"SELECT * FROM memories WHERE {' AND '.join(clauses)} ORDER BY id LIMIT ?",
            (*params, limit + 1),
        )
        .fetchall()
    )
    has_more = len(rows) > limit
    items = [dict(row) for row in rows[:limit]]
    for item in items:
        item["context"] = json.loads(item.pop("context_json"))
        item["tags"] = json.loads(item.pop("tags_json"))
    return {"items": items, "next_cursor": items[-1]["id"] if has_more else None}


@app.get("/v1/memories/{memory_id}/sources", dependencies=[Depends(require_key)])
def memory_sources(memory_id: str) -> dict[str, Any]:
    conn = app.state.db()
    memory = conn.execute(
        "SELECT * FROM memories WHERE id=? AND owner_id=?",
        (memory_id, get_settings().owner_id),
    ).fetchone()
    if memory is None:
        raise HTTPException(404, "unknown memory")
    evidence = [
        dict(row)
        for row in conn.execute(
            """SELECT e.*,m.role,m.content,m.created_at FROM memory_evidence e
                 JOIN messages m ON m.id=e.message_id WHERE e.memory_id=?
                 ORDER BY e.message_id,e.start_char""",
            (memory_id,),
        ).fetchall()
    ]
    return {"memory": dict(memory), "source_role": memory["source_role"], "evidence": evidence}


@app.get("/v1/memories/{memory_id}/history", dependencies=[Depends(require_key)])
def memory_history(memory_id: str) -> dict[str, Any]:
    conn = app.state.db()
    memory = conn.execute(
        "SELECT * FROM memories WHERE id=? AND owner_id=?",
        (memory_id, get_settings().owner_id),
    ).fetchone()
    if memory is None:
        raise HTTPException(404, "unknown memory")
    predecessors = [
        dict(row)
        for row in conn.execute("SELECT * FROM memories WHERE superseded_by=?", (memory_id,))
    ]
    successor = (
        conn.execute("SELECT * FROM memories WHERE id=?", (memory["superseded_by"],)).fetchone()
        if memory["superseded_by"]
        else None
    )
    return {
        "memory": dict(memory),
        "predecessors": predecessors,
        "successor": dict(successor) if successor else None,
    }


@app.post("/v1/memories/search", dependencies=[Depends(require_key)])
@app.post("/v1/search", dependencies=[Depends(require_key)], include_in_schema=False)
def search_memories(body: SearchIn) -> dict[str, Any]:
    started = time.perf_counter()
    conn = app.state.db()
    try:
        policy = retrieval.load_policy(conn, body.policy_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    result = retrieval.explain(
        conn,
        app.state.qdrant,
        app.state.embedder,
        query=body.query,
        owner_id=get_settings().owner_id,
        expression=body.filter,
        kinds=list(body.kinds) if body.kinds else None,
        limit=body.limit,
        budget_tokens=body.budget_tokens,
        policy=policy,
        include_untrusted=body.include_untrusted,
    )
    if result.chosen:
        with transaction(conn):
            store.record_retrieval(conn, [item.id for item in result.chosen])
    raw = (
        store.search_raw(
            app.state.qdrant,
            app.state.embedder,
            query=body.query,
            owner_id=get_settings().owner_id,
            limit=body.limit,
        )
        if body.include_raw
        else []
    )
    return {
        **result.as_dict(),
        "raw": raw,
        "took_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@app.post("/v1/retrieval-feedback", dependencies=[Depends(require_key)], status_code=201)
def retrieval_feedback(body: FeedbackIn) -> dict[str, bool]:
    with transaction(app.state.db()):
        store.record_feedback(
            app.state.db(),
            memory_id=body.memory_id,
            query_hash=hashlib.sha256(body.query.encode()).hexdigest(),
            useful=body.useful,
            correct=body.correct,
        )
    return {"recorded": True}


@app.post("/v1/namespaces", dependencies=[Depends(require_key)], status_code=201)
def create_namespace(body: NamespaceIn) -> dict[str, Any]:
    try:
        with transaction(app.state.db()):
            return platform.create_namespace(
                app.state.db(),
                owner_id=get_settings().owner_id,
                name=body.name,
                description=body.description,
            )
    except platform.PlatformError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/namespaces", dependencies=[Depends(require_key)])
def list_namespaces() -> dict[str, Any]:
    items = platform.list_namespaces(app.state.db(), owner_id=get_settings().owner_id)
    return {"items": items}


@app.get("/v1/namespaces/{namespace}/collections", dependencies=[Depends(require_key)])
def list_collections(namespace: str) -> dict[str, Any]:
    return {
        "items": platform.list_collections(
            app.state.db(), owner_id=get_settings().owner_id, namespace=namespace
        )
    }


@app.post(
    "/v1/namespaces/{namespace}/collections", dependencies=[Depends(require_key)], status_code=201
)
def create_collection(namespace: str, body: CollectionIn) -> dict[str, Any]:
    try:
        with transaction(app.state.db()):
            return platform.create_collection(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                name=body.name,
                schema=body.schema_,
                indexed_fields=body.indexed_fields,
                embedding_fields=body.embedding_fields,
                policy=body.policy,
            )
    except platform.PlatformError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/collections/{namespace}/{name}", dependencies=[Depends(require_key)])
def get_collection(namespace: str, name: str) -> dict[str, Any]:
    try:
        return platform.collection_definition(
            app.state.db(), owner_id=get_settings().owner_id, namespace=namespace, name=name
        )
    except platform.PlatformError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post(
    "/v1/collections/{namespace}/{name}/records",
    dependencies=[Depends(require_key)],
    status_code=201,
)
def create_record(namespace: str, name: str, body: RecordIn) -> dict[str, Any]:
    try:
        with transaction(app.state.db()):
            record, deduplicated = platform.create_record(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                collection_name=name,
                value=body.value,
                metadata=body.metadata,
                context=body.context,
                idempotency_key=body.idempotency_key,
            )
        return {**record, "deduplicated": deduplicated}
    except platform.PlatformError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.patch(
    "/v1/collections/{namespace}/{name}/records/{record_id}", dependencies=[Depends(require_key)]
)
def update_record(namespace: str, name: str, record_id: str, body: RecordPatch) -> dict[str, Any]:
    try:
        with transaction(app.state.db()):
            return platform.update_record(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                collection_name=name,
                record_id=record_id,
                expected_revision=body.expected_revision,
                value=body.value,
                metadata=body.metadata,
                context=body.context,
            )
    except platform.PlatformError as exc:
        status = 409 if "conflict" in str(exc) else 422
        raise HTTPException(status, str(exc)) from exc


@app.delete(
    "/v1/collections/{namespace}/{name}/records/{record_id}", dependencies=[Depends(require_key)]
)
def delete_record(namespace: str, name: str, record_id: str) -> dict[str, Any]:
    try:
        with transaction(app.state.db()):
            platform.delete_record(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                collection_name=name,
                record_id=record_id,
            )
        return {"id": record_id, "status": "deleted"}
    except platform.PlatformError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get(
    "/v1/collections/{namespace}/{name}/records/{record_id}/history",
    dependencies=[Depends(require_key)],
)
def record_history(namespace: str, name: str, record_id: str) -> dict[str, Any]:
    try:
        return {
            "items": platform.record_history(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                collection_name=name,
                record_id=record_id,
            )
        }
    except platform.PlatformError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/v1/collections/{namespace}/{name}/search", dependencies=[Depends(require_key)])
def search_records(namespace: str, name: str, body: RecordSearchIn) -> dict[str, Any]:
    try:
        items, next_cursor = platform.search_record_page(
            app.state.db(),
            owner_id=get_settings().owner_id,
            namespace=namespace,
            collection_name=name,
            expression=body.filter,
            limit=body.limit,
            cursor=body.cursor,
        )
        return {"items": items, "next_cursor": next_cursor}
    except (platform.PlatformError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@app.post("/v1/namespaces/{namespace}/links", dependencies=[Depends(require_key)], status_code=201)
def create_link(namespace: str, body: LinkIn) -> dict[str, Any]:
    try:
        with transaction(app.state.db()):
            return platform.create_link(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                from_ref=body.from_ref,
                relation=body.relation,
                to_ref=body.to_ref,
                metadata=body.metadata,
            )
    except platform.PlatformError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/namespaces/{namespace}/links", dependencies=[Depends(require_key)])
def list_links(namespace: str) -> dict[str, Any]:
    return {
        "items": platform.list_links(
            app.state.db(), owner_id=get_settings().owner_id, namespace=namespace
        )
    }


@app.get("/v1/policies", dependencies=[Depends(require_key)])
def list_policies(namespace: str | None = None) -> dict[str, Any]:
    return {
        "items": platform.list_policies(
            app.state.db(), owner_id=get_settings().owner_id, namespace=namespace
        )
    }


@app.post("/v1/policies", dependencies=[Depends(require_key)], status_code=201)
def create_policy(body: PolicyIn) -> dict[str, Any]:
    conn = app.state.db()
    namespace_id = None
    if body.namespace:
        row = conn.execute(
            "SELECT id FROM namespaces WHERE owner_id=? AND name=?",
            (get_settings().owner_id, body.namespace),
        ).fetchone()
        if row is None:
            raise HTTPException(422, "unknown namespace")
        namespace_id = row["id"]
    try:
        with transaction(conn):
            policy_id = platform.put_policy(
                conn,
                namespace_id=namespace_id,
                kind=body.kind,
                name=body.name,
                version=body.version,
                config=body.config,
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "policy version already exists") from exc
    return {"id": policy_id, **body.model_dump()}


@app.post("/v1/profiles/render", dependencies=[Depends(require_key)])
def render_profile(body: ProfileIn) -> dict[str, Any]:
    return profiles.render(
        app.state.db(),
        owner_id=get_settings().owner_id,
        stable_kinds=list(body.stable_kinds),
        dynamic_days=body.dynamic_days,
        budget_tokens=body.budget_tokens,
        include_untrusted=body.include_untrusted,
    )


def _run_export(job_id: str) -> None:
    conn = app.state.db()
    try:
        jobs.claim(conn, job_id)
        if jobs.cancel_requested(conn, job_id):
            jobs.finish(conn, job_id, status="cancelled")
            return
        path = privacy.export_owner(
            conn, owner_id=get_settings().owner_id, export_dir=get_settings().export_dir
        )
        jobs.finish(conn, job_id, status="complete", result={"path": str(path)})
    except Exception as exc:
        jobs.finish(conn, job_id, status="failed", error_code="export_failed", error=str(exc))


@app.post("/v1/export", dependencies=[Depends(require_key)], status_code=202)
def export_data(background: BackgroundTasks) -> dict[str, str]:
    job_id = jobs.create(app.state.db(), kind="export")
    background.add_task(_run_export, job_id)
    return {"job_id": job_id, "status": "queued"}


def _run_erase(job_id: str) -> None:
    conn = app.state.db()
    try:
        jobs.claim(conn, job_id)
        if jobs.cancel_requested(conn, job_id):
            jobs.finish(conn, job_id, status="cancelled")
            return
        result = privacy.erase_owner(
            conn, app.state.qdrant, app.state.embedder, owner_id=get_settings().owner_id
        )
        jobs.finish(conn, job_id, status="complete", result=result)
    except Exception as exc:
        jobs.finish(conn, job_id, status="failed", error_code="erase_failed", error=str(exc))


@app.post("/v1/erase", dependencies=[Depends(require_key)], status_code=202)
def erase_data(body: EraseIn, background: BackgroundTasks) -> dict[str, str]:
    job_id = jobs.create(app.state.db(), kind="erase", input_data={"confirmed": True})
    background.add_task(_run_erase, job_id)
    return {"job_id": job_id, "status": "queued"}


def _run_reindex(job_id: str) -> None:
    conn = app.state.db()
    holder = f"reindex:{job_id}"
    try:
        jobs.claim(conn, job_id)
        if not jobs.acquire_lease(conn, name="reindex", holder=holder, ttl_seconds=3600):
            raise RuntimeError("another reindex holds the maintenance lease")
        result = reindex.rebuild(
            conn,
            app.state.qdrant,
            app.state.embedder,
            cancelled=lambda: jobs.cancel_requested(conn, job_id),
        )
        jobs.finish(conn, job_id, status="complete", result=result)
    except reindex.ReindexCancelled:
        jobs.finish(conn, job_id, status="cancelled")
    except Exception as exc:
        logger.exception("reindex job %s failed", job_id)
        jobs.finish(conn, job_id, status="failed", error_code="reindex_failed", error=str(exc))
    finally:
        jobs.release_lease(conn, name="reindex", holder=holder)


@app.post("/v1/admin/reindex", dependencies=[Depends(require_key)], status_code=202)
def start_reindex(background: BackgroundTasks) -> dict[str, str]:
    job_id = jobs.create(app.state.db(), kind="reindex")
    background.add_task(_run_reindex, job_id)
    return {"job_id": job_id, "status": "queued"}


def _run_consolidation(job_id: str) -> None:
    conn = app.state.db()
    try:
        job = jobs.claim(conn, job_id)
        if jobs.cancel_requested(conn, job_id):
            jobs.finish(conn, job_id, status="cancelled")
            return
        data = json.loads(job["input_json"])
        outcome = consolidate.run(
            conn,
            owner_id=get_settings().owner_id,
            stale_days=get_settings().consolidate_stale_days,
            demotion=get_settings().consolidate_demotion,
            dry_run=bool(data.get("dry_run", True)),
        )
        _drain()
        jobs.finish(conn, job_id, status="complete", result=outcome.as_dict())
    except Exception as exc:
        jobs.finish(
            conn, job_id, status="failed", error_code="consolidation_failed", error=str(exc)
        )


@app.post("/v1/admin/consolidate", dependencies=[Depends(require_key)], status_code=202)
def start_consolidation(body: ConsolidateIn, background: BackgroundTasks) -> dict[str, str]:
    job_id = jobs.create(app.state.db(), kind="consolidation", input_data={"dry_run": body.dry_run})
    background.add_task(_run_consolidation, job_id)
    return {"job_id": job_id, "status": "queued"}


def _run_replay_report(job_id: str) -> None:
    conn = app.state.db()
    try:
        jobs.claim(conn, job_id)
        if jobs.cancel_requested(conn, job_id):
            jobs.finish(conn, job_id, status="cancelled")
            return
        result = reextract.dry_run_report(
            conn,
            owner_id=get_settings().owner_id,
            model=get_settings().judge_model,
            output_dir=get_settings().export_dir,
        )
        jobs.finish(conn, job_id, status="complete", result=result)
    except Exception as exc:
        jobs.finish(
            conn, job_id, status="failed", error_code="replay_report_failed", error=str(exc)
        )


@app.post("/v1/admin/reextract", dependencies=[Depends(require_key)], status_code=202)
def start_replay_report(background: BackgroundTasks) -> dict[str, str]:
    job_id = jobs.create(app.state.db(), kind="legacy_replay_dry_run")
    background.add_task(_run_replay_report, job_id)
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
def get_job(job_id: str) -> dict[str, Any]:
    try:
        conn = app.state.db()
        return {**dict(jobs.get(conn, job_id)), "history": jobs.history(conn, job_id)}
    except KeyError as exc:
        raise HTTPException(404, "unknown job") from exc


@app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(require_key)], status_code=202)
def cancel_job(job_id: str) -> dict[str, str]:
    try:
        jobs.request_cancel(app.state.db(), job_id)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"job_id": job_id, "status": "cancellation_requested"}


@app.get("/v1/jobs", dependencies=[Depends(require_key)])
def list_jobs(
    status: Literal["queued", "running", "complete", "failed", "cancelled"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status=?")
        params.append(status)
    if cursor:
        try:
            cursor_time, cursor_id = cursor.rsplit("|", 1)
        except ValueError as exc:
            raise HTTPException(422, "invalid job cursor") from exc
        clauses.append("(created_at<? OR (created_at=? AND id<?))")
        params.extend([cursor_time, cursor_time, cursor_id])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = (
        app.state.db()
        .execute(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC,id DESC LIMIT ?",
            (*params, limit + 1),
        )
        .fetchall()
    )
    has_more = len(rows) > limit
    items = [dict(row) for row in rows[:limit]]
    return {
        "items": items,
        "next_cursor": f"{items[-1]['created_at']}|{items[-1]['id']}" if has_more else None,
    }


@app.get("/v1/admin/sessions", dependencies=[Depends(require_key)])
def list_sessions(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    conn = app.state.db()
    owner_id = get_settings().owner_id
    rows = conn.execute(
        """SELECT s.*,
                  COUNT(m.id) AS message_count,
                  SUM(CASE WHEN m.processed=0 THEN 1 ELSE 0 END) AS unprocessed_count
             FROM sessions s LEFT JOIN messages m ON m.session_id=s.id
            WHERE s.owner_id=? GROUP BY s.id ORDER BY s.started_at DESC
            LIMIT ? OFFSET ?""",
        (owner_id, limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM sessions WHERE owner_id=?", (owner_id,)).fetchone()[
        0
    ]
    items = []
    for row in rows:
        item = dict(row)
        item["context"] = json.loads(item.pop("context_json") or "{}")
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/v1/admin/sessions/{session_id}/messages", dependencies=[Depends(require_key)])
def list_session_messages(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    conn = app.state.db()
    session = conn.execute(
        "SELECT * FROM sessions WHERE id=? AND owner_id=?",
        (session_id, get_settings().owner_id),
    ).fetchone()
    if session is None:
        raise HTTPException(404, "unknown session")
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY id LIMIT ? OFFSET ?",
        (session_id, limit, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)
    ).fetchone()[0]
    return {
        "session": dict(session),
        "items": [dict(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/v1/admin/judge-runs", dependencies=[Depends(require_key)])
def list_judge_runs(
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)
) -> dict[str, Any]:
    conn = app.state.db()
    owner_id = get_settings().owner_id
    rows = conn.execute(
        "SELECT * FROM judge_runs WHERE owner_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
        (owner_id, limit, offset),
    ).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) FROM judge_runs WHERE owner_id=?", (owner_id,)
    ).fetchone()[0]
    return {"items": [dict(row) for row in rows], "total": total, "limit": limit, "offset": offset}


@app.get("/v1/admin/judge-runs/{run_id}", dependencies=[Depends(require_key)])
def get_judge_run(run_id: int) -> dict[str, Any]:
    conn = app.state.db()
    row = conn.execute(
        "SELECT * FROM judge_runs WHERE id=? AND owner_id=?",
        (run_id, get_settings().owner_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown judge run")
    return dict(row)


@app.get("/v1/admin/health", dependencies=[Depends(require_key)])
def detailed_health() -> dict[str, Any]:
    conn = app.state.db()
    return {
        "database": {
            "path": str(get_settings().db_path),
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
        },
        "qdrant": {
            "memories": vectors.count(app.state.qdrant, vectors.MEMORIES),
            "raw": vectors.count(app.state.qdrant, vectors.RAW),
        },
        "embedder": {
            "ready": app.state.embedder.ready,
            "device": app.state.embedder.device,
            "revision": get_settings().embed_revision,
        },
        "outbox": {"pending": outbox.pending_count(conn)},
        "jobs": {
            row["status"]: row["n"]
            for row in conn.execute("SELECT status,COUNT(*) n FROM jobs GROUP BY status")
        },
    }


@app.get("/v1/admin/metrics", dependencies=[Depends(require_key)])
def metrics() -> dict[str, Any]:
    conn = app.state.db()
    period = time.strftime("%Y-%m", time.gmtime())
    return {
        "outbox_pending": outbox.pending_count(conn),
        "oldest_unprocessed_message": conn.execute(
            "SELECT MIN(created_at) FROM messages WHERE processed=0"
        ).fetchone()[0],
        "provider_errors": conn.execute(
            "SELECT COUNT(*) FROM judge_runs WHERE error IS NOT NULL"
        ).fetchone()[0],
        "month_spend_usd": conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs WHERE substr(created_at,1,7)=?",
            (period,),
        ).fetchone()[0],
        "month_reserved_usd": conn.execute(
            "SELECT COALESCE(SUM(reserved_usd),0) FROM budget_reservations WHERE period=? AND status='active'",
            (period,),
        ).fetchone()[0],
    }


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


_ui_dir = Path(_startup_settings.ui_dir)
if _ui_dir.is_dir():

    @app.get("/", include_in_schema=False)
    def root_ui() -> RedirectResponse:
        return RedirectResponse("/ui/")

    app.mount("/ui", SPAStaticFiles(directory=_ui_dir, html=True), name="ui")
