"""Strict, single-owner HTTP API for memory, evidence, and generic records."""

from __future__ import annotations

import json
import logging
import secrets
import shutil
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (
    consolidate,
    evaluations,
    extract,
    jobs,
    operations,
    outbox,
    platform,
    policy_sweep,
    privacy,
    profiles,
    reextract,
    reindex,
    release,
    replay,
    retrieval,
    store,
    telemetry,
    vectors,
    worker,
)
from .config import Settings, get_settings
from .db import ConnectionPool, ensure_owner, init_db, transaction, utcnow
from .embed import get_embedder
from .routers import mount_domain_routers

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
    expected_revision: int = Field(ge=1)
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
    # Attach hash-verified verbatim source spans to each memory: search over
    # atomic facts, hand back the evidence that carries the detail. Presentation
    # only — ranking never sees it.
    include_sources: bool = False
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    limit: int = Field(default=30, ge=1, le=200)


class FeedbackIn(StrictModel):
    memory_id: str
    query: str
    useful: bool | None = None
    correct: bool | None = None


class RetrievalRunFeedbackIn(StrictModel):
    memory_id: str
    useful: bool | None = None
    correct: bool | None = None


class NamespaceIn(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    description: Annotated[str, StringConstraints(max_length=1000)] = ""


class CollectionIn(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
    schema_: dict[str, Any] = Field(alias="schema")
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
    stable_kinds: list[Kind] = Field(default_factory=lambda: ["fact", "preference"])
    dynamic_days: int = Field(default=30, ge=1, le=3650)
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    include_untrusted: bool = False


class EraseIn(StrictModel):
    confirm: Literal["ERASE ALL DATA"]


class ConsolidateIn(StrictModel):
    dry_run: bool = True
    # LLM-confirmed semantic merge of near-duplicate clusters (decisions/0056).
    # Only meaningful with dry_run=false; defaults keep the roadmap's promise
    # that no automatic semantic merge runs unless explicitly requested.
    merge: bool = False


class ReplayIn(StrictModel):
    apply: bool = False


class ReplayReviewIn(StrictModel):
    decision: Literal["accepted", "rejected", "edited"]
    edits: dict[str, Any] | None = None


class ChecksumIn(StrictModel):
    checksum: str


class PromotionIn(ChecksumIn):
    confirm: Literal["PROMOTE"]


class PolicyActivationIn(ChecksumIn):
    confirm: Literal["ACTIVATE"]


class EvaluationArmsIn(StrictModel):
    no_memory: str
    current_memory: str
    reviewed_v7: str
    oracle_memory: str


class EvaluationCaseIn(StrictModel):
    case_key: Identifier
    prompt: ShortText
    arms: EvaluationArmsIn


class EvaluationCreateIn(StrictModel):
    model: Literal["gpt-5.6-sol"] = "gpt-5.6-sol"
    cases: list[EvaluationCaseIn] = Field(min_length=1, max_length=32)
    rubric: dict[str, Any] | None = None


class EvaluationReviewIn(StrictModel):
    ranking: list[Literal["A", "B", "C", "D"]] = Field(min_length=4, max_length=4)
    harmful: list[Literal["A", "B", "C", "D"]] = Field(default_factory=list)
    notes: Annotated[str, StringConstraints(max_length=2000)] = ""
    current_vs_v7: Literal["v7_win", "current_win", "tie"]


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


class FlexibleOut(BaseModel):
    """Typed public fields while allowing additive response evolution."""

    model_config = ConfigDict(extra="allow")


class HealthOut(StrictModel):
    ok: bool


class ReadyOut(StrictModel):
    ready: bool
    database: bool
    qdrant: bool
    embedder: bool


class BatchOut(StrictModel):
    items: list[MessageOut]
    count: int


class JobQueuedOut(StrictModel):
    job_id: str | None
    status: str
    reason: str | None = None


class MemoryCreatedOut(StrictModel):
    id: str
    stored: bool
    indexed: bool
    index_job_id: str | None = None


class EntityOut(FlexibleOut):
    id: str
    revision: int | None = None
    status: str | None = None


class ItemsOut(StrictModel):
    items: list[dict[str, Any]]


class CursorPageOut(ItemsOut):
    next_cursor: str | None


class OffsetPageOut(ItemsOut):
    total: int
    limit: int
    offset: int


class MemoryOut(StrictModel):
    memory: dict[str, Any]


class MemorySourcesOut(StrictModel):
    memory: dict[str, Any]
    source_role: str
    evidence: list[dict[str, Any]]


class MemoryHistoryOut(StrictModel):
    memory: dict[str, Any]
    revisions: list[dict[str, Any]]
    predecessors: list[dict[str, Any]]
    successor: dict[str, Any] | None


class MemorySearchOut(StrictModel):
    memories: list[dict[str, Any]]
    used_tokens: int
    dropped_trust: list[str]
    dropped_validity: list[str]
    dropped_filter: list[str]
    dropped_relevance: list[str]
    policy_id: str
    embed_ms: float
    retrieval_id: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    raw: list[dict[str, Any]]
    took_ms: float


class FeedbackOut(StrictModel):
    recorded: bool


class ProfileOut(StrictModel):
    stable: list[dict[str, Any]]
    dynamic: list[dict[str, Any]]
    used_tokens: int
    generated_at: str
    policy_id: str


class JobOut(FlexibleOut):
    id: str
    kind: str
    status: str
    history: list[dict[str, Any]]


class SessionMessagesOut(OffsetPageOut):
    session: dict[str, Any]


class JudgeRunOut(FlexibleOut):
    id: int


class AdminHealthOut(StrictModel):
    database: dict[str, Any]
    qdrant: dict[str, Any]
    embedder: dict[str, Any]
    outbox: dict[str, Any]
    jobs: dict[str, int]


class MetricsOut(StrictModel):
    outbox_pending: int
    oldest_unprocessed_message: str | None
    provider_errors: int
    month_spend_usd: float
    month_reserved_usd: float
    search_latency_ms: dict[str, float | None] | None = None
    retrieval_runs: int | None = None
    abstention_rate: float | None = None
    feedback_labels: int | None = None
    feedback_runs: int | None = None
    useful_rate: float | None = None
    correct_rate: float | None = None
    outbox_oldest_age_seconds: float | None = None
    outbox_retries: int | None = None
    index_parity: dict[str, int | bool | None] | None = None
    backup_freshness_seconds: float | None = None


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
    app.state.index_ready = False
    app.state.index_error = None
    try:
        vectors.ensure_collections(app.state.qdrant)
        app.state.index_ready = True
    except Exception as exc:
        app.state.index_error = str(exc)
        logger.warning("vector index unavailable at startup; running in degraded mode")
    app.state.embedder = get_embedder()
    app.state.embedder.load()
    if app.state.index_ready:
        try:
            outbox.drain(app.state.db(), app.state.qdrant, app.state.embedder, limit=500)
        except Exception as exc:
            app.state.index_ready = False
            app.state.index_error = str(exc)
            logger.warning("initial index drain failed; worker will retry")
    with transaction(app.state.db()):
        telemetry.prune(app.state.db(), retention_days=settings.telemetry_retention_days)

    app.state.maintenance = False
    _start_durable_worker(app)
    yield
    app.state.worker.stop()
    app.state.db.close_all()
    app.state.qdrant.close()


def _start_durable_worker(application: FastAPI) -> None:
    def dependency_status(ready: bool, error: str | None) -> None:
        application.state.index_ready = ready
        application.state.index_error = error

    application.state.worker = worker.Worker(
        application.state.db,
        application.state.qdrant,
        application.state.embedder,
        _dispatch_job,
        dependency_status=dependency_status,
    )
    application.state.worker.start()


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
    if getattr(app.state, "maintenance", False) and request.url.path.startswith("/v1"):
        return JSONResponse(
            status_code=503,
            content={"detail": "maintenance is in progress; retry shortly"},
            headers={"Retry-After": "60", "X-Request-ID": request_id},
        )
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
    try:
        outbox.drain(app.state.db(), app.state.qdrant, app.state.embedder, limit=100)
        app.state.index_ready = True
        app.state.index_error = None
    except Exception as exc:
        app.state.index_ready = False
        app.state.index_error = str(exc)
        logger.warning("index delivery deferred; durable outbox retained")


def _wake_worker() -> None:
    durable_worker = getattr(app.state, "worker", None)
    if durable_worker is not None:
        durable_worker.wake()


def _dispatch_job(job_id: str, kind: str) -> None:
    handlers = {
        "extraction": _run_extraction,
        "export": _run_export,
        "erase": _run_erase,
        "reindex": _run_reindex,
        "consolidation": _run_consolidation,
        "legacy_replay_dry_run": _run_replay_report,
        "shadow_replay": _run_shadow_replay,
    }
    handler = handlers.get(kind)
    if handler is None:
        jobs.claim(app.state.db(), job_id)
        jobs.finish(
            app.state.db(),
            job_id,
            status="failed",
            error_code="unknown_job_kind",
            error=f"no handler for job kind {kind!r}",
        )
        return
    handler(job_id)


def _run_extraction(job_id: str) -> None:
    settings = get_settings()
    conn = app.state.db()
    job: sqlite3.Row | None = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"]):
            if jobs.cancel_requested(conn, job_id):
                jobs.finish(conn, job_id, status="cancelled")
                return
            data = json.loads(job["input_json"])
            outcome = extract.run_session_extraction(
                conn,
                max_windows=int(data.get("max_windows") or 1),
                cancelled=lambda: jobs.cancel_requested(conn, job_id),
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
                client=app.state.qdrant,
                embedder=app.state.embedder,
                dedup_cosine=settings.dedup_cosine,
            )
            _drain()
            # A forced run (an explicit "remember this", or a closed session)
            # must finish the session even when its backlog exceeded this job's
            # window cap, so hand the remainder to a fresh job rather than
            # leaving it for the next inbound event that may never come.
            remaining = extract.messages_since_last(conn, data["session_id"])
            continuation = None
            if (
                not outcome.error
                and outcome.claimed
                and remaining >= (1 if data.get("force") else extract.WINDOW_SIZE)
            ):
                continuation = _queue_extraction(
                    conn,
                    session_id=data["session_id"],
                    agent_id=data["agent_id"],
                    force=bool(data.get("force")),
                    pending=remaining,
                )
                _wake_worker()
            jobs.finish(
                conn,
                job_id,
                status="failed" if outcome.error else "complete",
                result={**outcome.as_dict(), "continuation_job_id": continuation},
                error_code=outcome.error,
                error=outcome.error,
            )
    except Exception as exc:
        logger.exception("extraction job %s failed", job_id)
        if job is not None:
            jobs.finish(
                conn,
                job_id,
                status="failed",
                error_code="extraction_failed",
                error=str(exc),
            )


# One window is one provider call, so this caps a single job's spend and the
# time it holds the worker. Twenty-five windows is ~250 messages, well inside
# the renewable job lease.
MAX_WINDOWS_PER_JOB = 25


def _queue_extraction(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    agent_id: str,
    force: bool,
    pending: int = 0,
) -> str:
    """Queue extraction sized to the backlog it has to clear.

    `call_limit` and `max_windows` move together: the limit is the hard stop
    the job enforces per provider call, the window count is what the drain loop
    attempts.
    """
    windows = max(1, -(-max(pending, 0) // extract.WINDOW_SIZE))
    windows = min(windows, MAX_WINDOWS_PER_JOB)
    return jobs.create(
        conn,
        kind="extraction",
        input_data={
            "session_id": session_id,
            "agent_id": agent_id,
            "force": force,
            "max_windows": windows,
        },
        call_limit=windows,
    )


@app.get("/healthz")
def healthz() -> HealthOut:
    return {"ok": True}


@app.get("/readyz", response_model=ReadyOut)
def readyz() -> JSONResponse:
    database_ok = qdrant_ok = embedder_ok = False
    try:
        database_ok = app.state.db().execute("SELECT 1").fetchone()[0] == 1
        qdrant_ok = bool(getattr(app.state, "index_ready", False))
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
def post_message(body: MessageIn) -> MessageOut:
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
            conn,
            session_id=body.session_id,
            agent_id=body.agent_id,
            force=True,
            pending=pending,
        )
        _wake_worker()
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
def post_evidence_batch(body: EvidenceBatchIn) -> BatchOut:
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
            _queue_extraction(
                conn,
                session_id=session_id,
                agent_id=agent_id,
                force=False,
                pending=extract.messages_since_last(conn, session_id),
            )
            _wake_worker()
    return {"items": results, "count": len(results)}


@app.post("/v1/sessions/{session_id}/close", dependencies=[Depends(require_key)], status_code=202)
def close_session(session_id: str) -> JobQueuedOut:
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
    job_id = _queue_extraction(
        conn,
        session_id=session_id,
        agent_id=row["agent_id"],
        force=True,
        pending=extract.messages_since_last(conn, session_id),
    )
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


@app.post("/v1/memories", dependencies=[Depends(require_key)], status_code=201)
def post_memory(body: MemoryIn) -> MemoryCreatedOut:
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
def patch_memory(memory_id: str, body: MemoryPatch) -> EntityOut:
    conn = app.state.db()
    row = conn.execute(
        "SELECT * FROM memories WHERE id=? AND owner_id=?",
        (memory_id, get_settings().owner_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown memory")
    current_context = json.loads(row["context_json"] or "{}")
    if body.context is not None and body.context != current_context and not body.move_context:
        raise HTTPException(422, "context changes require move_context=true")
    try:
        with transaction(conn):
            saved = store.update_memory(
                conn,
                memory_id=memory_id,
                owner_id=get_settings().owner_id,
                expected_revision=body.expected_revision,
                text=body.text if body.text is not None else row["text"],
                kind=body.kind if body.kind is not None else row["kind"],
                context=body.context if body.context is not None else current_context,
                tags=list(body.tags) if body.tags is not None else json.loads(row["tags_json"]),
                importance=body.importance if body.importance is not None else row["importance"],
                confidence=body.confidence if body.confidence is not None else row["confidence"],
                valid_until=None
                if body.clear_valid_until
                else (
                    _timestamp(body.valid_until)
                    if body.valid_until is not None
                    else row["valid_until"]
                ),
            )
    except RuntimeError as exc:
        raise HTTPException(409, "memory changed; reload and retry") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _drain()
    return dict(saved)


@app.delete("/v1/memories/{memory_id}", dependencies=[Depends(require_key)])
def delete_memory(memory_id: str) -> EntityOut:
    conn = app.state.db()
    try:
        with transaction(conn):
            store.set_memory_status(
                conn,
                memory_id=memory_id,
                owner_id=get_settings().owner_id,
                status="archived",
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, "memory changed; retry") from exc
    _drain()
    return {"id": memory_id, "status": "archived"}


@app.get("/v1/memories", dependencies=[Depends(require_key)])
def list_memories(
    kind: str | None = None,
    status: Literal["active", "archived", "expired", "superseded"] = "active",
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
) -> CursorPageOut:
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


@app.get("/v1/memories/{memory_id}", dependencies=[Depends(require_key)])
def get_memory(memory_id: str) -> MemoryOut:
    """One memory, including `revision`.

    A correction is a PATCH carrying `expected_revision`, so an agent needs a
    way to read the current revision of a single fact. Search results carry it
    too, but an id learned from a profile block or an earlier turn has nowhere
    else to come from.
    """
    conn = app.state.db()
    row = conn.execute(
        "SELECT * FROM memories WHERE id=? AND owner_id=?",
        (memory_id, get_settings().owner_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown memory")
    memory = dict(row)
    memory["context"] = json.loads(memory.pop("context_json"))
    memory["tags"] = json.loads(memory.pop("tags_json"))
    return {"memory": memory}


@app.get("/v1/memories/{memory_id}/sources", dependencies=[Depends(require_key)])
def memory_sources(memory_id: str) -> MemorySourcesOut:
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
def memory_history(memory_id: str) -> MemoryHistoryOut:
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
        "revisions": [
            {
                **dict(row),
                "context": json.loads(row["context_json"]),
                "tags": json.loads(row["tags_json"]),
            }
            for row in conn.execute(
                "SELECT * FROM memory_revisions WHERE memory_id=? ORDER BY revision DESC",
                (memory_id,),
            )
        ],
        "predecessors": predecessors,
        "successor": dict(successor) if successor else None,
    }


@app.post("/v1/memories/search", dependencies=[Depends(require_key)])
@app.post("/v1/search", dependencies=[Depends(require_key)], include_in_schema=False)
def search_memories(body: SearchIn) -> MemorySearchOut:
    started = time.perf_counter()
    conn = app.state.db()
    try:
        policy = retrieval.load_policy(conn, body.policy_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not getattr(app.state, "index_ready", True):
        raise HTTPException(503, "vector search dependency is temporarily unavailable")
    try:
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
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        app.state.index_ready = False
        app.state.index_error = str(exc)
        logger.warning("vector search failed; dependency monitor will reconnect")
        raise HTTPException(503, "vector search dependency is temporarily unavailable") from exc
    took_ms = (time.perf_counter() - started) * 1000
    result.timings["request_ms"] = took_ms
    settings = get_settings()
    with transaction(conn):
        retrieval_id = telemetry.record_retrieval_run(
            conn,
            owner_id=settings.owner_id,
            query_hash=telemetry.hash_query(settings.telemetry_hmac_key, body.query),
            policy_id=result.policy_id,
            results=[item.as_dict() for item in result.chosen],
            timings=result.timings,
            used_tokens=result.used_tokens,
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
    payload = result.as_dict()
    if body.include_sources and result.chosen:
        excerpts = store.evidence_excerpts(conn, [item.id for item in result.chosen])
        for memory in payload["memories"]:
            memory["sources"] = excerpts.get(memory["id"], [])
    return {
        **payload,
        "retrieval_id": retrieval_id,
        "raw": raw,
        "took_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@app.post("/v1/retrieval-feedback", dependencies=[Depends(require_key)], status_code=201)
def retrieval_feedback(body: FeedbackIn) -> FeedbackOut:
    settings = get_settings()
    with transaction(app.state.db()):
        store.record_feedback(
            app.state.db(),
            memory_id=body.memory_id,
            query_hash=telemetry.hash_query(settings.telemetry_hmac_key, body.query),
            useful=body.useful,
            correct=body.correct,
        )
    return {"recorded": True}


@app.post(
    "/v1/retrieval-runs/{retrieval_id}/feedback",
    dependencies=[Depends(require_key)],
    status_code=201,
)
def retrieval_run_feedback(retrieval_id: str, body: RetrievalRunFeedbackIn) -> FeedbackOut:
    try:
        with transaction(app.state.db()):
            telemetry.record_run_feedback(
                app.state.db(),
                retrieval_id=retrieval_id,
                owner_id=get_settings().owner_id,
                memory_id=body.memory_id,
                useful=body.useful,
                correct=body.correct,
            )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"recorded": True}


@app.get("/v1/retrieval-runs", dependencies=[Depends(require_key)])
def recent_retrieval_runs(limit: int = Query(20, ge=1, le=100)) -> ItemsOut:
    return {
        "items": telemetry.recent_runs(
            app.state.db(), owner_id=get_settings().owner_id, limit=limit
        )
    }


@app.post("/v1/namespaces", dependencies=[Depends(require_key)], status_code=201)
def create_namespace(body: NamespaceIn) -> EntityOut:
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
def list_namespaces() -> ItemsOut:
    items = platform.list_namespaces(app.state.db(), owner_id=get_settings().owner_id)
    return {"items": items}


@app.get("/v1/namespaces/{namespace}/collections", dependencies=[Depends(require_key)])
def list_collections(namespace: str) -> ItemsOut:
    return {
        "items": platform.list_collections(
            app.state.db(), owner_id=get_settings().owner_id, namespace=namespace
        )
    }


@app.post(
    "/v1/namespaces/{namespace}/collections", dependencies=[Depends(require_key)], status_code=201
)
def create_collection(namespace: str, body: CollectionIn) -> EntityOut:
    try:
        with transaction(app.state.db()):
            return platform.create_collection(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                name=body.name,
                schema=body.schema_,
                policy=body.policy,
            )
    except platform.PlatformError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/collections/{namespace}/{name}", dependencies=[Depends(require_key)])
def get_collection(namespace: str, name: str) -> EntityOut:
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
def create_record(namespace: str, name: str, body: RecordIn) -> EntityOut:
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
def update_record(namespace: str, name: str, record_id: str, body: RecordPatch) -> EntityOut:
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
def delete_record(
    namespace: str,
    name: str,
    record_id: str,
    expected_revision: int = Query(..., ge=1),
) -> EntityOut:
    try:
        with transaction(app.state.db()):
            platform.delete_record(
                app.state.db(),
                owner_id=get_settings().owner_id,
                namespace=namespace,
                collection_name=name,
                record_id=record_id,
                expected_revision=expected_revision,
            )
        return {"id": record_id, "status": "deleted"}
    except platform.PlatformError as exc:
        status = 409 if "conflict" in str(exc) else 404
        raise HTTPException(status, str(exc)) from exc


@app.get(
    "/v1/collections/{namespace}/{name}/records/{record_id}/history",
    dependencies=[Depends(require_key)],
)
def record_history(namespace: str, name: str, record_id: str) -> ItemsOut:
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
def search_records(namespace: str, name: str, body: RecordSearchIn) -> CursorPageOut:
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
def create_link(namespace: str, body: LinkIn) -> EntityOut:
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
def list_links(namespace: str) -> ItemsOut:
    return {
        "items": platform.list_links(
            app.state.db(), owner_id=get_settings().owner_id, namespace=namespace
        )
    }


@app.get("/v1/policies", dependencies=[Depends(require_key)])
def list_policies(namespace: str | None = None) -> ItemsOut:
    return {
        "items": platform.list_policies(
            app.state.db(), owner_id=get_settings().owner_id, namespace=namespace
        )
    }


@app.post("/v1/policies", dependencies=[Depends(require_key)], status_code=201)
def create_policy(body: PolicyIn) -> EntityOut:
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
def render_profile(body: ProfileIn) -> ProfileOut:
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
    job: sqlite3.Row | None = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"]):
            if jobs.cancel_requested(conn, job_id):
                jobs.finish(conn, job_id, status="cancelled")
                return
            path = privacy.export_owner(
                conn, owner_id=get_settings().owner_id, export_dir=get_settings().export_dir
            )
            jobs.finish(conn, job_id, status="complete", result={"path": str(path)})
    except Exception as exc:
        if job is not None:
            jobs.finish(conn, job_id, status="failed", error_code="export_failed", error=str(exc))


@app.post("/v1/export", dependencies=[Depends(require_key)], status_code=202)
def export_data() -> JobQueuedOut:
    job_id = jobs.create(app.state.db(), kind="export")
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


def _run_erase(job_id: str) -> None:
    conn = app.state.db()
    job: sqlite3.Row | None = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"]):
            if jobs.cancel_requested(conn, job_id):
                jobs.finish(conn, job_id, status="cancelled")
                return
            result = privacy.erase_owner(
                conn,
                app.state.qdrant,
                app.state.embedder,
                owner_id=get_settings().owner_id,
                export_dir=get_settings().export_dir,
            )
            jobs.finish(conn, job_id, status="complete", result=result)
    except Exception as exc:
        if job is not None:
            jobs.finish(conn, job_id, status="failed", error_code="erase_failed", error=str(exc))


@app.post("/v1/erase", dependencies=[Depends(require_key)], status_code=202)
def erase_data(body: EraseIn) -> JobQueuedOut:
    job_id = jobs.create(app.state.db(), kind="erase", input_data={"confirmed": True})
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


def _run_reindex(job_id: str) -> None:
    conn = app.state.db()
    holder = f"reindex:{job_id}"
    job: sqlite3.Row | None = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"]):
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
        if job is not None:
            jobs.finish(conn, job_id, status="cancelled")
    except Exception as exc:
        logger.exception("reindex job %s failed", job_id)
        if job is not None:
            jobs.finish(conn, job_id, status="failed", error_code="reindex_failed", error=str(exc))
    finally:
        jobs.release_lease(conn, name="reindex", holder=holder)


@app.post("/v1/admin/reindex", dependencies=[Depends(require_key)], status_code=202)
def start_reindex() -> JobQueuedOut:
    job_id = jobs.create(app.state.db(), kind="reindex")
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


def _run_consolidation(job_id: str) -> None:
    conn = app.state.db()
    job: sqlite3.Row | None = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"]):
            if jobs.cancel_requested(conn, job_id):
                jobs.finish(conn, job_id, status="cancelled")
                return
            data = json.loads(job["input_json"])
            settings = get_settings()
            outcome = consolidate.run(
                conn,
                owner_id=settings.owner_id,
                stale_days=settings.consolidate_stale_days,
                demotion=settings.consolidate_demotion,
                importance_floor=settings.consolidate_importance_floor,
                dry_run=bool(data.get("dry_run", True)),
                embedder=app.state.embedder,
                consolidate_cosine=settings.consolidate_cosine,
                merge=bool(data.get("merge", False)),
                merge_model=settings.judge_model,
                monthly_limit_usd=settings.monthly_cost_limit_usd,
                anthropic_api_key=settings.anthropic_api_key,
                gemini_api_key=settings.gemini_api_key,
                project=settings.vertex_project,
                location=settings.vertex_location,
            )
            _drain()
            jobs.finish(conn, job_id, status="complete", result=outcome.as_dict())
    except Exception as exc:
        if job is not None:
            jobs.finish(
                conn, job_id, status="failed", error_code="consolidation_failed", error=str(exc)
            )


@app.post("/v1/admin/consolidate", dependencies=[Depends(require_key)], status_code=202)
def start_consolidation(body: ConsolidateIn) -> JobQueuedOut:
    job_id = jobs.create(
        app.state.db(),
        kind="consolidation",
        input_data={"dry_run": body.dry_run, "merge": body.merge},
    )
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


def _run_replay_report(job_id: str) -> None:
    conn = app.state.db()
    job: sqlite3.Row | None = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"]):
            if jobs.cancel_requested(conn, job_id):
                jobs.finish(conn, job_id, status="cancelled")
                return
            settings = get_settings()
            result = reextract.dry_run_report(
                conn,
                owner_id=settings.owner_id,
                model=settings.judge_model,
                output_dir=settings.export_dir,
            )
            jobs.finish(conn, job_id, status="complete", result=result)
    except Exception as exc:
        if job is not None:
            jobs.finish(
                conn, job_id, status="failed", error_code="replay_report_failed", error=str(exc)
            )


def _run_shadow_replay(job_id: str) -> None:
    conn = app.state.db()
    job: sqlite3.Row | None = None
    try:
        job = jobs.claim(conn, job_id)
        data = json.loads(job["input_json"])
        with jobs.heartbeat(conn, job_id, holder=job["holder"], lease_seconds=3600):
            result = replay.run_shadow_replay(
                conn,
                settings=get_settings(),
                batch_id=str(data["batch_id"]),
                job_id=job_id,
                cancelled=lambda: jobs.cancel_requested(conn, job_id),
            )
        jobs.finish(
            conn,
            job_id,
            status="cancelled" if result.get("cancelled") else "complete",
            result=result,
        )
    except Exception as exc:
        logger.exception("shadow replay job %s failed", job_id)
        if job is not None:
            jobs.finish(
                conn, job_id, status="failed", error_code="shadow_replay_failed", error=str(exc)
            )


@app.post("/v1/admin/reextract", dependencies=[Depends(require_key)], status_code=202)
def start_replay_report(body: ReplayIn | None = None) -> JobQueuedOut:
    apply = bool(body and body.apply)
    if apply and not judge_configured(get_settings()):
        raise HTTPException(409, "replay apply requires a configured judge provider")
    if apply:
        try:
            created = replay.create_batch(app.state.db(), settings=get_settings())
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        job_id = created["job_id"]
        reason = f"review_batch:{created['batch_id']}"
    else:
        job_id = jobs.create(app.state.db(), kind="legacy_replay_dry_run")
        reason = None
    _wake_worker()
    return {"job_id": job_id, "status": "queued", "reason": reason}


@app.get("/v1/replay-batches", dependencies=[Depends(require_key)])
def list_replay_batches() -> ItemsOut:
    return {"items": replay.list_batches(app.state.db(), owner_id=get_settings().owner_id)}


@app.get("/v1/replay-batches/{batch_id}", dependencies=[Depends(require_key)])
def replay_batch(batch_id: str) -> FlexibleOut:
    try:
        return replay.get_batch(app.state.db(), batch_id=batch_id, owner_id=get_settings().owner_id)
    except LookupError as exc:
        raise HTTPException(404, "unknown replay batch") from exc


@app.get("/v1/replay-batches/{batch_id}/items", dependencies=[Depends(require_key)])
def replay_batch_items(batch_id: str) -> ItemsOut:
    try:
        replay.get_batch(app.state.db(), batch_id=batch_id, owner_id=get_settings().owner_id)
    except LookupError as exc:
        raise HTTPException(404, "unknown replay batch") from exc
    return {"items": replay.list_items(app.state.db(), batch_id=batch_id)}


@app.patch(
    "/v1/replay-batches/{batch_id}/items/{item_id}/review",
    dependencies=[Depends(require_key)],
)
def review_replay_item(batch_id: str, item_id: str, body: ReplayReviewIn) -> FlexibleOut:
    try:
        return replay.review_item(
            app.state.db(),
            batch_id=batch_id,
            item_id=item_id,
            decision=body.decision,
            edits=body.edits,
        )
    except LookupError as exc:
        raise HTTPException(404, "unknown replay item") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/replay-batches/{batch_id}/validate", dependencies=[Depends(require_key)])
def validate_replay_batch(batch_id: str) -> FlexibleOut:
    try:
        return release.validate_candidate(
            app.state.db(),
            app.state.qdrant,
            app.state.embedder,
            settings=get_settings(),
            batch_id=batch_id,
        )
    except LookupError as exc:
        raise HTTPException(404, "unknown replay batch") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/replay-batches/{batch_id}/approve", dependencies=[Depends(require_key)])
def approve_replay_batch(batch_id: str, body: ChecksumIn) -> FlexibleOut:
    try:
        return replay.approve_batch(
            app.state.db(),
            batch_id=batch_id,
            owner_id=get_settings().owner_id,
            checksum=body.checksum,
        )
    except LookupError as exc:
        raise HTTPException(404, "unknown replay batch") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/replay-batches/{batch_id}/promotion-gates", dependencies=[Depends(require_key)])
def replay_promotion_gates(batch_id: str, body: ChecksumIn) -> FlexibleOut:
    try:
        return release.release_gate_status(
            app.state.db(),
            settings=get_settings(),
            batch_id=batch_id,
            checksum=body.checksum,
        )
    except LookupError as exc:
        raise HTTPException(404, "unknown replay batch") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/replay-batches/{batch_id}/promote", dependencies=[Depends(require_key)])
def promote_replay_batch(batch_id: str, body: PromotionIn) -> FlexibleOut:
    settings = get_settings()
    try:
        gate = release.release_gate_status(
            app.state.db(), settings=settings, batch_id=batch_id, checksum=body.checksum
        )
    except LookupError as exc:
        raise HTTPException(404, "unknown replay batch") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not gate["passed"]:
        failed = [name for name, passed in gate["checks"].items() if not passed]
        raise HTTPException(409, f"promotion gates are incomplete: {', '.join(failed)}")
    if getattr(app.state, "maintenance", False):
        raise HTTPException(409, "maintenance is already in progress")

    checkpoint = operations.create_backup(settings, kind="pre-promotion", protected=True)
    started = time.monotonic()
    app.state.maintenance = True
    durable_worker = getattr(app.state, "worker", None)
    if durable_worker is not None:
        durable_worker.stop()
    try:
        result = release.promote(
            app.state.db(),
            app.state.qdrant,
            app.state.embedder,
            settings=settings,
            batch_id=batch_id,
            checksum=body.checksum,
            deadline=started + 15 * 60,
        )
        elapsed = time.monotonic() - started
        if elapsed > 15 * 60:
            raise RuntimeError("promotion exceeded the 15-minute maintenance window")
        result["checkpoint"] = checkpoint
        result["maintenance_seconds"] = round(elapsed, 1)
    except Exception as exc:
        logger.exception("promotion failed; restoring protected checkpoint")
        rollback_error: Exception | None = None
        try:
            app.state.db.close_all()
            staged = settings.db_path.with_suffix(f"{settings.db_path.suffix}.rollback.tmp")
            shutil.copy2(Path(checkpoint["path"]), staged)
            operations.verify_backup(staged, expected_sha256=checkpoint["sha256"])
            staged.replace(settings.db_path)
            for suffix in ("-wal", "-shm"):
                settings.db_path.with_name(settings.db_path.name + suffix).unlink(missing_ok=True)
            init_db(settings.db_path)
            app.state.db = ConnectionPool(settings.db_path)
            rollback_conn = app.state.db()
            with transaction(rollback_conn):
                ensure_owner(rollback_conn, settings.owner_id, settings.owner_name)
            reindex.rebuild(app.state.db(), app.state.qdrant, app.state.embedder)
        except Exception as rollback_exc:
            rollback_error = rollback_exc
            logger.exception("automatic promotion rollback failed")
        finally:
            _start_durable_worker(app)
            app.state.maintenance = False
        if rollback_error is not None:
            raise HTTPException(
                500, "promotion and automatic rollback failed; protected checkpoint retained"
            ) from rollback_error
        raise HTTPException(
            500, "promotion failed and SQLite plus Qdrant were rolled back automatically"
        ) from exc
    _start_durable_worker(app)
    app.state.maintenance = False
    return result


@app.post("/v1/replay-batches/{batch_id}/export", dependencies=[Depends(require_key)])
def export_replay_batch(batch_id: str) -> FlexibleOut:
    try:
        return replay.export_batch(
            app.state.db(),
            batch_id=batch_id,
            owner_id=get_settings().owner_id,
            output_dir=get_settings().export_dir / "review-artifacts",
        )
    except LookupError as exc:
        raise HTTPException(404, "unknown replay batch") from exc


@app.post("/v1/evaluations", dependencies=[Depends(require_key)], status_code=201)
def create_evaluation(body: EvaluationCreateIn) -> FlexibleOut:
    try:
        return evaluations.create(
            app.state.db(),
            model=body.model,
            cases=[case.model_dump() for case in body.cases],
            rubric=body.rubric,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/v1/evaluations", dependencies=[Depends(require_key)])
def list_evaluations() -> ItemsOut:
    return {"items": evaluations.list_runs(app.state.db())}


@app.get("/v1/evaluations/{evaluation_id}", dependencies=[Depends(require_key)])
def get_evaluation(evaluation_id: str) -> FlexibleOut:
    try:
        return evaluations.get_run(app.state.db(), evaluation_id)
    except LookupError as exc:
        raise HTTPException(404, "unknown evaluation") from exc


@app.get("/v1/evaluations/{evaluation_id}/cases", dependencies=[Depends(require_key)])
def list_evaluation_cases(evaluation_id: str) -> ItemsOut:
    try:
        return {"items": evaluations.list_cases(app.state.db(), evaluation_id=evaluation_id)}
    except LookupError as exc:
        raise HTTPException(404, "unknown evaluation") from exc


@app.get("/v1/evaluations/{evaluation_id}/cases/{case_id}", dependencies=[Depends(require_key)])
def get_evaluation_case(evaluation_id: str, case_id: str) -> FlexibleOut:
    try:
        return evaluations.get_case(app.state.db(), evaluation_id=evaluation_id, case_id=case_id)
    except LookupError as exc:
        raise HTTPException(404, "unknown evaluation case") from exc


@app.post(
    "/v1/evaluations/{evaluation_id}/cases/{case_id}/review",
    dependencies=[Depends(require_key)],
)
def review_evaluation_case(
    evaluation_id: str, case_id: str, body: EvaluationReviewIn
) -> FlexibleOut:
    try:
        return evaluations.review_case(
            app.state.db(),
            evaluation_id=evaluation_id,
            case_id=case_id,
            ranking=list(body.ranking),
            harmful=list(body.harmful),
            notes=body.notes,
            current_vs_v7=body.current_vs_v7,
        )
    except LookupError as exc:
        raise HTTPException(404, "unknown evaluation case") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/evaluations/{evaluation_id}/finalize", dependencies=[Depends(require_key)])
def finalize_evaluation(evaluation_id: str) -> FlexibleOut:
    try:
        return evaluations.finalize(app.state.db(), evaluation_id=evaluation_id)
    except LookupError as exc:
        raise HTTPException(404, "unknown evaluation") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/v1/jobs/{job_id}", dependencies=[Depends(require_key)])
def get_job(job_id: str) -> JobOut:
    try:
        conn = app.state.db()
        return {**dict(jobs.get(conn, job_id)), "history": jobs.history(conn, job_id)}
    except KeyError as exc:
        raise HTTPException(404, "unknown job") from exc


@app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(require_key)], status_code=202)
def cancel_job(job_id: str) -> JobQueuedOut:
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
) -> CursorPageOut:
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
) -> OffsetPageOut:
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
) -> SessionMessagesOut:
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
) -> OffsetPageOut:
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
def get_judge_run(run_id: int) -> JudgeRunOut:
    conn = app.state.db()
    row = conn.execute(
        "SELECT * FROM judge_runs WHERE id=? AND owner_id=?",
        (run_id, get_settings().owner_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown judge run")
    return dict(row)


@app.get("/v1/admin/health", dependencies=[Depends(require_key)])
def detailed_health() -> AdminHealthOut:
    conn = app.state.db()
    index_ready = bool(getattr(app.state, "index_ready", True))
    memory_count = raw_count = None
    if index_ready:
        try:
            memory_count = vectors.count(app.state.qdrant, vectors.MEMORIES)
            raw_count = vectors.count(app.state.qdrant, vectors.RAW)
        except Exception as exc:
            app.state.index_ready = False
            app.state.index_error = str(exc)
            index_ready = False
    return {
        "database": {
            "path": str(get_settings().db_path),
            "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
        },
        "qdrant": {
            "available": index_ready,
            "memories": memory_count,
            "raw": raw_count,
            "error": getattr(app.state, "index_error", None),
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
def metrics() -> MetricsOut:
    conn = app.state.db()
    period = time.strftime("%Y-%m", time.gmtime())
    retrieval_metrics = telemetry.metrics(conn)
    active_memories = int(
        conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0]
    )
    indexed_memories: int | None = None
    if getattr(app.state, "index_ready", True):
        with suppress(Exception):
            indexed_memories = vectors.count(app.state.qdrant, vectors.MEMORIES)
    oldest_outbox = conn.execute(
        """SELECT MAX(0,(julianday('now')-julianday(MIN(created_at)))*86400)
             FROM index_outbox WHERE status IN ('pending','processing','failed')"""
    ).fetchone()[0]
    backup_age = conn.execute(
        """SELECT MAX(0,(julianday('now')-julianday(MAX(verified_at)))*86400)
             FROM backup_artifacts"""
    ).fetchone()[0]
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
        **retrieval_metrics,
        "outbox_oldest_age_seconds": round(float(oldest_outbox), 1)
        if oldest_outbox is not None
        else None,
        "outbox_retries": int(
            conn.execute("SELECT COALESCE(SUM(attempts),0) FROM index_outbox").fetchone()[0]
        ),
        "index_parity": {
            "sqlite_active": active_memories,
            "qdrant_active": indexed_memories,
            "matches": indexed_memories == active_memories
            if indexed_memories is not None
            else None,
        },
        "backup_freshness_seconds": round(float(backup_age), 1) if backup_age is not None else None,
    }


@app.get("/v1/admin/backups", dependencies=[Depends(require_key)])
def backup_status() -> ItemsOut:
    return {"items": operations.list_backups(get_settings())}


@app.post("/v1/admin/policy-sweep", dependencies=[Depends(require_key)])
def run_policy_sweep() -> FlexibleOut:
    try:
        return policy_sweep.sweep(
            app.state.db(),
            owner_id=get_settings().owner_id,
            output_dir=get_settings().export_dir / "release-artifacts",
        )
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/admin/policy-sweep/{checksum}/activate", dependencies=[Depends(require_key)])
def activate_policy_sweep(checksum: str, body: PolicyActivationIn) -> FlexibleOut:
    path = get_settings().export_dir / "release-artifacts" / f"policy-sweep-{checksum}.json"
    try:
        return policy_sweep.activate(
            app.state.db(),
            artifact_path=path,
            checksum=body.checksum,
            confirm=body.confirm,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, "unknown policy sweep artifact") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, Any]):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


mount_domain_routers(app)

_ui_dir = Path(_startup_settings.ui_dir)
if _ui_dir.is_dir():

    @app.get("/", include_in_schema=False)
    def root_ui() -> RedirectResponse:
        return RedirectResponse("/ui/")

    app.mount("/ui", SPAStaticFiles(directory=_ui_dir, html=True), name="ui")
