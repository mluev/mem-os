"""Strict, scope-addressed HTTP API for team memory.

Authentication has two shapes and they are not interchangeable.

An **API key** is what an agent or hook sends. It names its user explicitly on
every request, so it needs no protection against a hostile page: nothing else
can make the caller attach it.

A **session cookie** is what the dashboard uses. The browser attaches it to any
request to this origin, including one another site provokes, so a
cookie-authenticated mutation must also carry a header no cross-origin form can
set. That is the whole CSRF defence, and it works because CORS is closed.

Every handler resolves a `Principal` and takes its scopes from it. Nothing reads
an owner from configuration: the service this replaced had one owner in settings
and forty handlers that read it, which is exactly what made it single-user.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import psycopg
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (
    auth,
    consolidate,
    entities,
    extract,
    jobs,
    operations,
    outbox,
    policies,
    privacy,
    profiles,
    reextract,
    reindex,
    retrieval,
    store,
    telemetry,
    users,
    vectors,
    worker,
)
from . import (
    principal as principal_module,
)
from .config import Settings, get_settings
from .db import ConnectionPool, init_db, iso, utcnow
from .embed import get_embedder
from .principal import Principal, ScopeForbidden, UnknownScope
from .routers import mount_domain_routers

logger = logging.getLogger(__name__)

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]
Kind = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Slug = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=200)]

SESSION_COOKIE = "memkit_session"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class LoginIn(StrictModel):
    handle: Identifier
    password: Annotated[str, StringConstraints(min_length=1, max_length=200)]


class PasswordChangeIn(StrictModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    new_password: Password


class UserIn(StrictModel):
    handle: Identifier
    display_name: ShortText
    password: Password
    role: Literal["admin", "member"] = "member"
    email: Identifier | None = None


class UserPatch(StrictModel):
    display_name: ShortText | None = None
    role: Literal["admin", "member"] | None = None
    disabled: bool | None = None


class ApiKeyIn(StrictModel):
    name: ShortText
    user_id: Identifier | None = None


class EntityIn(StrictModel):
    kind: Literal["project", "product", "company", "person", "custom"]
    name: ShortText
    slug: Slug | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] = ""
    visibility: Literal["members", "team"] = "members"
    aliases: list[ShortText] = Field(default_factory=list, max_length=20)


class EntityPatch(StrictModel):
    name: ShortText | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    visibility: Literal["members", "team"] | None = None


class AliasIn(StrictModel):
    alias: ShortText


class MemberIn(StrictModel):
    role: Literal["owner", "member", "viewer"] = "member"


class ResolveIn(StrictModel):
    name: ShortText


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
    # Where facts from this conversation belong. A slug, `team`, `private`, or
    # omitted for private. Fixed when the session is created.
    scope: Slug | None = None
    created_at: AwareDatetime | None = None


class MessageOut(StrictModel):
    message_id: int
    indexed: bool
    index_status: str
    index_job_id: str | None = None
    extraction_job_id: str | None = None
    deduplicated: bool = False
    redacted: bool = False


class EvidenceBatchIn(StrictModel):
    events: Annotated[list[MessageIn], Field(min_length=1, max_length=100)]


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
    scope: Slug | None = None
    subject: Slug | None = None


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
    subject: Slug | None = None
    clear_subject: bool = False
    scope: Slug | None = None
    # Moving a fact between scopes changes who can read it, so it must be said
    # out loud rather than inferred from a field appearing in a patch.
    move_scope: bool = False
    move_context: bool = False


class ReviewIn(StrictModel):
    decision: Literal["confirm", "decline", "undo"]
    expected_revision: int | None = Field(default=None, ge=1)


class AttentionResolveIn(StrictModel):
    action: Literal["link_entity", "dismiss"]
    entity: Slug | None = None


class SearchIn(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8192)]
    filter: dict[str, Any] | None = None
    kinds: list[Kind] | None = None
    # Narrow the search to particular scopes. Omitted means every scope the
    # caller can read; naming one they cannot is a 403, not an empty result.
    scopes: list[Slug] | None = None
    subject: Slug | None = None
    policy_id: str = "neutral-v1"
    include_untrusted: bool = False
    include_raw: bool = False
    include_sources: bool = False
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    limit: int = Field(default=30, ge=1, le=200)


class FeedbackIn(StrictModel):
    memory_id: Identifier
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=8192)]
    useful: bool | None = None
    correct: bool | None = None


class RetrievalRunFeedbackIn(StrictModel):
    memory_id: Identifier
    useful: bool | None = None
    correct: bool | None = None


class ProfileIn(StrictModel):
    blocks: list[Literal["about", "style", "team", "project", "recent"]] = Field(
        default_factory=lambda: ["about", "style", "team", "project", "recent"]
    )
    workspace: Slug | None = None
    dynamic_days: int = Field(default=30, ge=1, le=3650)
    budget_tokens: int = Field(default=800, ge=1, le=20_000)
    include_untrusted: bool = False


class EraseIn(StrictModel):
    confirm: Literal["ERASE ALL DATA"]


class ConsolidateIn(StrictModel):
    dry_run: bool = True
    merge: bool = False


class ReplayIn(StrictModel):
    confirm: Literal["REPLAY"] | None = None


class PolicyIn(StrictModel):
    kind: Literal["extraction", "retrieval", "retention", "consolidation"]
    name: ShortText
    version: int = Field(ge=1)
    config: dict[str, Any]
    scope: Slug | None = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class FlexibleOut(BaseModel):
    model_config = ConfigDict(extra="allow")


class HealthOut(StrictModel):
    ok: bool


class ReadyOut(StrictModel):
    ready: bool
    database: bool
    qdrant: bool
    embedder: bool


class BatchOut(StrictModel):
    items: list[dict[str, Any]]
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
    # True when an identical claim already existed in this scope and was
    # returned instead of a twin being written.
    deduplicated: bool = False
    review_status: str = "pending"


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
    timings: dict[str, float]
    raw: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_id: str | None = None


class FeedbackOut(StrictModel):
    recorded: bool


class ProfileOut(StrictModel):
    blocks: dict[str, list[dict[str, Any]]]
    used_tokens: int
    budget_tokens: int
    generated_at: str
    policy_id: str


class SessionOut(StrictModel):
    user: dict[str, Any]
    csrf_required_header: str = auth.CSRF_HEADER


class KeyCreatedOut(StrictModel):
    id: str
    name: str
    key_prefix: str
    # The only time this value exists outside the caller's hands.
    secret: str


class JobOut(FlexibleOut):
    id: str
    kind: str
    status: str


class SessionMessagesOut(OffsetPageOut):
    session: dict[str, Any]


class JudgeRunOut(FlexibleOut):
    id: int
    kind: str
    model: str


class AdminHealthOut(StrictModel):
    ok: bool
    checks: list[dict[str, Any]]
    checked_at: str


class MetricsOut(StrictModel):
    model_config = ConfigDict(extra="allow")


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def _validate_runtime(settings: Settings) -> None:
    if not settings.database_url:
        raise RuntimeError("MEMKIT_DATABASE_URL must be set")
    loopback = settings.host in {"127.0.0.1", "localhost", "::1"}
    if not loopback and not settings.allow_remote:
        raise RuntimeError("remote binding requires MEMKIT_ALLOW_REMOTE=true")
    if len(settings.telemetry_hmac_key) < 32:
        raise RuntimeError(
            "MEMKIT_TELEMETRY_HMAC_KEY must be at least 32 characters: stored query "
            "identities are HMAC'd with it"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _validate_runtime(settings)
    init_db(settings.database_url)
    app.state.db = ConnectionPool(settings.database_url, max_size=settings.database_pool_max)
    with app.state.db.borrow() as conn, conn.transaction():
        entities.ensure_team(conn, name=settings.team_name)
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
    app.state.login_limiter = auth.RateLimiter()
    if app.state.index_ready:
        try:
            with app.state.db.borrow() as conn:
                outbox.drain(conn, app.state.qdrant, app.state.embedder, limit=500)
        except Exception as exc:
            app.state.index_ready = False
            app.state.index_error = str(exc)
            logger.warning("initial index drain failed; worker will retry")
    with app.state.db.borrow() as conn, conn.transaction():
        telemetry.prune(conn, retention_days=settings.telemetry_retention_days)

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
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/docs" if _startup_settings.expose_docs else None,
    redoc_url="/redoc" if _startup_settings.expose_docs else None,
)
if _startup_settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_startup_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type", "X-Request-ID", auth.CSRF_HEADER],
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


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_conn(request: Request) -> psycopg.Connection:
    return request.app.state.db()


def _memory_id(value: str) -> str:
    """Reject an id that cannot exist before Postgres is asked about it.

    `memories.id` is a uuid column, so a malformed string is a type error, and
    an unparseable id would surface as a 500 rather than the miss it is.
    """
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise HTTPException(404, "unknown memory") from exc


def get_principal(
    request: Request,
    x_api_key: Annotated[str | None, Depends(_api_key_header)] = None,
    memkit_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    x_requested_with: Annotated[str | None, Header()] = None,
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> Principal:
    """Resolve the caller, or refuse.

    A key wins over a cookie when both are present: an agent that sends a key
    means to act as that key's user, and silently preferring an ambient browser
    session would be the more surprising of the two.
    """
    if x_api_key:
        user_id = auth.resolve_api_key(conn, x_api_key)
        if user_id is None:
            raise HTTPException(401, "invalid or revoked API key")
        return principal_module.load(conn, user_id, auth_kind="api_key")
    if memkit_session:
        user_id = auth.resolve_session(conn, memkit_session, ttl_days=settings.session_ttl_days)
        if user_id is None:
            raise HTTPException(401, "session is expired or revoked")
        if request.method not in _SAFE_METHODS and x_requested_with != auth.CSRF_VALUE:
            # A cross-origin form post cannot set this header, and CORS is
            # closed, so its absence on a mutation means the request did not
            # come from the dashboard.
            raise HTTPException(403, f"cookie-authenticated writes require {auth.CSRF_HEADER}")
        return principal_module.load(conn, user_id, auth_kind="session")
    raise HTTPException(401, "authentication required")


def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    if not principal.is_admin:
        raise HTTPException(403, "administrator role required")
    return principal


@app.exception_handler(ScopeForbidden)
async def _scope_forbidden(_request: Request, exc: ScopeForbidden) -> JSONResponse:
    """A named scope outside the caller's set is refused, never filtered.

    Filtering would make a forbidden scope indistinguishable from an empty one,
    which hides both a permissions bug and an attempt to read another team's
    memory.
    """
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(UnknownScope)
async def _unknown_scope(_request: Request, exc: UnknownScope) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def judge_configured(settings: Settings) -> bool:
    from . import judge

    if judge.provider_of(settings.judge_model) == "gemini":
        return bool(settings.gemini_api_key or settings.vertex_project)
    return bool(settings.anthropic_api_key)


def _outbox_state(
    conn: psycopg.Connection, collection: str, entity_id: str | int
) -> tuple[bool, str | None]:
    row = conn.execute(
        """SELECT id,status FROM index_outbox
            WHERE collection=%s AND entity_id=%s
            ORDER BY id DESC LIMIT 1""",
        (collection, str(entity_id)),
    ).fetchone()
    if row is None:
        return True, None
    return row["status"] == "done", str(row["id"])


def _drain() -> None:
    if not getattr(app.state, "index_ready", False):
        return
    try:
        with app.state.db.borrow() as conn:
            outbox.drain(conn, app.state.qdrant, app.state.embedder, limit=100)
    except Exception:
        app.state.index_ready = False
        logger.warning("inline index drain failed; worker will retry")


def _wake_worker() -> None:
    running = getattr(app.state, "worker", None)
    if running is not None:
        running.wake()


# ---------------------------------------------------------------------------
# Background work
# ---------------------------------------------------------------------------


def _dispatch_job(job_id: str, kind: str) -> None:
    handlers = {
        "extraction": _run_extraction,
        "export": _run_export,
        "erase": _run_erase,
        "reindex": _run_reindex,
        "consolidation": _run_consolidation,
        "reextract_report": _run_reextract_report,
    }
    handler = handlers.get(kind)
    if handler is None:
        conn = app.state.db()
        jobs.claim(conn, job_id)
        jobs.finish(
            conn,
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
    job = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"], pool=app.state.db):
            if jobs.cancel_requested(conn, job_id):
                jobs.finish(conn, job_id, status="cancelled")
                return
            data = dict(job["input"] or {})
            outcome = extract.run_session_extraction(
                conn,
                max_windows=int(data.get("max_windows") or 1),
                cancelled=lambda: jobs.cancel_requested(conn, job_id),
                session_id=data["session_id"],
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
            # leaving it for an inbound event that may never come.
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
                    user_id=job["user_id"],
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
                conn, job_id, status="failed", error_code="extraction_failed", error=str(exc)
            )


# One window is one provider call, so this caps a single job's spend and the
# time it holds the worker. Twenty-five windows is ~250 messages, well inside
# the renewable job lease.
MAX_WINDOWS_PER_JOB = 25


def _queue_extraction(
    conn: psycopg.Connection,
    *,
    session_id: str,
    agent_id: str,
    force: bool,
    pending: int = 0,
    user_id: str | None = None,
) -> str:
    """Queue extraction sized to the backlog it has to clear.

    `call_limit` and `max_windows` move together: the limit is the hard stop the
    job enforces per provider call, the window count is what the drain loop
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
        user_id=user_id,
    )


def _run_export(job_id: str) -> None:
    conn = app.state.db()
    job = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"], pool=app.state.db):
            data = dict(job["input"] or {})
            result = privacy.export_user(
                conn,
                user_id=data["user_id"],
                export_dir=get_settings().export_dir,
                private_scope_id=data["private_scope_id"],
                authored_scopes=data.get("authored_scopes"),
            )
            jobs.finish(conn, job_id, status="complete", result=result)
    except Exception as exc:
        logger.exception("export job %s failed", job_id)
        if job is not None:
            jobs.finish(conn, job_id, status="failed", error_code="export_failed", error=str(exc))


def _run_erase(job_id: str) -> None:
    conn = app.state.db()
    job = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"], pool=app.state.db):
            data = dict(job["input"] or {})
            result = privacy.erase_user(
                conn,
                app.state.qdrant,
                user_id=data["user_id"],
                private_scope_id=data["private_scope_id"],
            )
            jobs.finish(conn, job_id, status="complete", result=result)
    except ValueError as exc:
        # Refusing to erase a user who authored shared memories is a decision,
        # not a fault: those rows are the team's record.
        if job is not None:
            jobs.finish(conn, job_id, status="failed", error_code="erase_refused", error=str(exc))
    except Exception as exc:
        logger.exception("erase job %s failed", job_id)
        if job is not None:
            jobs.finish(conn, job_id, status="failed", error_code="erase_failed", error=str(exc))


def _run_reindex(job_id: str) -> None:
    conn = app.state.db()
    job = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"], pool=app.state.db):
            app.state.maintenance = True
            try:
                result = reindex.rebuild(
                    conn,
                    app.state.qdrant,
                    app.state.embedder,
                    cancelled=lambda: jobs.cancel_requested(conn, job_id),
                )
            finally:
                app.state.maintenance = False
            jobs.finish(conn, job_id, status="complete", result=result)
    except Exception as exc:
        logger.exception("reindex job %s failed", job_id)
        app.state.maintenance = False
        if job is not None:
            jobs.finish(conn, job_id, status="failed", error_code="reindex_failed", error=str(exc))


def _run_consolidation(job_id: str) -> None:
    settings = get_settings()
    conn = app.state.db()
    job = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"], pool=app.state.db):
            data = dict(job["input"] or {})
            outcome = consolidate.run(
                conn,
                scope_ids=data["scope_ids"],
                stale_days=settings.consolidate_stale_days,
                demotion=settings.consolidate_demotion,
                importance_floor=settings.consolidate_importance_floor,
                dry_run=bool(data.get("dry_run", True)),
                embedder=app.state.embedder,
                client=app.state.qdrant,
                consolidate_cosine=settings.consolidate_cosine,
                merge=bool(data.get("merge", False)),
                merge_model=settings.judge_model,
                monthly_limit_usd=settings.monthly_cost_limit_usd,
                anthropic_api_key=settings.anthropic_api_key,
                gemini_api_key=settings.gemini_api_key,
                project=settings.vertex_project,
                location=settings.vertex_location,
                user_id=job["user_id"],
            )
            _drain()
            jobs.finish(conn, job_id, status="complete", result=outcome.as_dict())
    except Exception as exc:
        logger.exception("consolidation job %s failed", job_id)
        if job is not None:
            jobs.finish(
                conn, job_id, status="failed", error_code="consolidation_failed", error=str(exc)
            )


def _run_reextract_report(job_id: str) -> None:
    conn = app.state.db()
    job = None
    try:
        job = jobs.claim(conn, job_id)
        with jobs.heartbeat(conn, job_id, holder=job["holder"], pool=app.state.db):
            data = dict(job["input"] or {})
            report = reextract.dry_run_report(conn, scope_ids=data["scope_ids"])
            jobs.finish(conn, job_id, status="complete", result=report)
    except Exception as exc:
        logger.exception("reextract report job %s failed", job_id)
        if job is not None:
            jobs.finish(
                conn, job_id, status="failed", error_code="reextract_failed", error=str(exc)
            )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/healthz")
def healthz() -> HealthOut:
    return {"ok": True}


@app.get("/readyz", response_model=ReadyOut)
def readyz() -> JSONResponse:
    database_ok = qdrant_ok = embedder_ok = False
    try:
        with app.state.db.borrow() as conn:
            row = conn.execute("SELECT 1 AS ok").fetchone()
        database_ok = bool(row and row["ok"] == 1)
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


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def _scope_summaries(conn: psycopg.Connection, principal: Principal) -> list[dict[str, Any]]:
    rows = entities.visible_to(conn, principal.user_id)
    return [
        {
            "id": str(row["id"]),
            "slug": row["slug"],
            "kind": row["kind"],
            "name": row["name"],
            "writable": str(row["id"]) in principal.writable_scope_ids,
        }
        for row in rows
    ]


@app.post("/v1/auth/login", response_model=SessionOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Exchange a password for a session cookie.

    Failures are counted per handle and per address and answered identically,
    so the endpoint cannot be used to discover which handles exist.
    """
    limiter: auth.RateLimiter = app.state.login_limiter
    address = request.client.host if request.client else "unknown"
    keys = (f"handle:{body.handle.casefold()}", f"ip:{address}")
    if not limiter.check(*keys):
        raise HTTPException(429, "too many attempts; wait a minute")
    user = users.by_handle(conn, body.handle)
    if user is None or user["disabled_at"] is not None:
        limiter.record(*keys)
        raise HTTPException(401, "invalid credentials")
    if not auth.verify_password(str(user["password_hash"]), body.password):
        limiter.record(*keys)
        raise HTTPException(401, "invalid credentials")
    limiter.reset(*keys)
    with conn.transaction():
        if auth.needs_rehash(str(user["password_hash"])):
            users.set_password(conn, user_id=str(user["id"]), password=body.password)
        token = auth.start_session(
            conn,
            user_id=str(user["id"]),
            ttl_days=settings.session_ttl_days,
            ip=address,
            user_agent=request.headers.get("user-agent"),
        )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_days * 86_400,
        path="/",
    )
    caller = principal_module.load(conn, str(user["id"]), auth_kind="session")
    return {"user": principal_module.describe(caller, _scope_summaries(conn, caller))}


@app.post("/v1/auth/logout")
def logout(
    response: Response,
    memkit_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    if memkit_session:
        with conn.transaction():
            auth.revoke_session(conn, memkit_session)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"recorded": True}


@app.get("/v1/auth/me")
def whoami(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    return principal_module.describe(principal, _scope_summaries(conn, principal))


@app.post("/v1/auth/password")
def change_password(
    body: PasswordChangeIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    memkit_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> FeedbackOut:
    """Change a password and sign the user out everywhere else.

    Other sessions are revoked because the usual reason to change a password is
    that somebody else may have had it.
    """
    user = users.by_id(conn, principal.user_id)
    if user is None or not auth.verify_password(str(user["password_hash"]), body.current_password):
        raise HTTPException(403, "current password does not match")
    with conn.transaction():
        users.set_password(conn, user_id=principal.user_id, password=body.new_password)
        auth.revoke_all_sessions(conn, user_id=principal.user_id, keep=memkit_session)
    return {"recorded": True}


@app.get("/v1/api-keys")
def list_api_keys(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    rows = conn.execute(
        """SELECT id,name,key_prefix,created_at,last_used_at,revoked_at
             FROM api_keys WHERE user_id=%s ORDER BY created_at DESC""",
        (principal.user_id,),
    ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "name": row["name"],
                "key_prefix": row["key_prefix"],
                "created_at": iso(row["created_at"]),
                "last_used_at": iso(row["last_used_at"]),
                "revoked_at": iso(row["revoked_at"]),
            }
            for row in rows
        ]
    }


@app.post("/v1/api-keys", status_code=201)
def create_api_key(
    body: ApiKeyIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> KeyCreatedOut:
    """Mint a key. The secret is returned once and never stored in the clear."""
    target = principal.user_id
    if body.user_id and body.user_id != principal.user_id:
        if not principal.is_admin:
            raise HTTPException(403, "only an administrator may create keys for another user")
        if users.by_id(conn, body.user_id) is None:
            raise HTTPException(404, "unknown user")
        target = body.user_id
    with conn.transaction():
        minted = auth.mint_api_key(conn, user_id=target, name=body.name)
    return {
        "id": minted.id,
        "name": body.name,
        "key_prefix": minted.prefix,
        "secret": minted.token,
    }


@app.delete("/v1/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    with conn.transaction():
        revoked = auth.revoke_api_key(
            conn, key_id=key_id, user_id=None if principal.is_admin else principal.user_id
        )
    if not revoked:
        raise HTTPException(404, "unknown or already revoked key")
    return {"recorded": True}


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _user_row(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": str(data["id"]),
        "handle": data["handle"],
        "display_name": data["display_name"],
        "email": data.get("email"),
        "role": data["role"],
        "created_at": iso(data.get("created_at")),
        "disabled_at": iso(data.get("disabled_at")),
        "own_entity_id": str(data["own_entity_id"]) if data.get("own_entity_id") else None,
        "key_last_used_at": iso(data.get("key_last_used_at")),
    }


@app.get("/v1/users")
def list_users(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    """Everyone on the team.

    Not admin-only: a team memory system is unusable if you cannot see who your
    teammates are, and a fact can name any of them as its subject. Only
    identity is exposed here, never credentials.
    """
    return {"items": [_user_row(row) for row in users.listing(conn)]}


@app.post("/v1/users", status_code=201)
def create_user(
    body: UserIn,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    try:
        with conn.transaction():
            row = users.create(
                conn,
                handle=body.handle,
                display_name=body.display_name,
                password=body.password,
                role=body.role,
                email=body.email,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "handle or email is already taken") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": str(row["id"]), "handle": row["handle"], "role": row["role"]}


@app.patch("/v1/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserPatch,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Change a role or disable an account.

    The last enabled administrator cannot be demoted or disabled: an instance
    with no administrator cannot create users, keys, or entities again.
    """
    target = users.by_id(conn, user_id)
    if target is None:
        raise HTTPException(404, "unknown user")
    losing_admin = (body.role == "member" and target["role"] == "admin") or bool(body.disabled)
    if (
        losing_admin
        and target["role"] == "admin"
        and users.count_admins(conn, excluding=user_id) == 0
    ):
        raise HTTPException(409, "the last administrator cannot be demoted or disabled")
    with conn.transaction():
        row = users.update(
            conn,
            user_id=user_id,
            display_name=body.display_name,
            role=body.role,
            disabled=body.disabled,
        )
    if row is None:
        raise HTTPException(404, "unknown user")
    return {"id": str(row["id"]), "role": row["role"], "disabled_at": iso(row["disabled_at"])}


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


def _entity_row(conn: psycopg.Connection, row: Any, principal: Principal) -> dict[str, Any]:
    entity_id = str(row["id"])
    return {
        "id": entity_id,
        "kind": row["kind"],
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "visibility": row["visibility"],
        "aliases": entities.aliases_of(conn, entity_id),
        "writable": entity_id in principal.writable_scope_ids,
        "created_at": iso(row["created_at"]),
        "archived_at": iso(row["archived_at"]),
    }


def _load_entity(conn: psycopg.Connection, principal: Principal, slug: str) -> Any:
    row = entities.by_slug(conn, slug)
    if row is None:
        raise HTTPException(404, "unknown entity")
    entity_id = str(row["id"])
    # A teammate's user entity is visible as a subject even though its scope is
    # not readable, so identity lookups work without exposing private memory.
    if entity_id not in principal.allowed_scope_ids and row["kind"] != "user":
        raise HTTPException(403, "entity is not accessible")
    return row


@app.get("/v1/entities")
def list_entities(
    kind: str | None = None,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    rows = entities.visible_to(conn, principal.user_id)
    if kind:
        rows = [row for row in rows if row["kind"] == kind]
    people = [] if kind and kind != "user" else entities.teammates(conn, principal.user_id)
    seen = {str(row["id"]) for row in rows}
    rows = rows + [row for row in people if str(row["id"]) not in seen]
    return {"items": [_entity_row(conn, row, principal) for row in rows]}


@app.post("/v1/entities", status_code=201)
def create_entity(
    body: EntityIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    try:
        with conn.transaction():
            row = entities.create(
                conn,
                kind=body.kind,
                name=body.name,
                slug=body.slug,
                description=body.description,
                visibility=body.visibility,
                created_by=principal.user_id,
                aliases=list(body.aliases),
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, "slug is already taken") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"id": str(row["id"]), "slug": row["slug"], "kind": row["kind"]}


@app.get("/v1/entities/{slug}")
def get_entity(
    slug: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    row = _load_entity(conn, principal, slug)
    payload = _entity_row(conn, row, principal)
    payload["members"] = [
        {
            "user_id": str(member["user_id"]),
            "handle": member["handle"],
            "display_name": member["display_name"],
            "role": member["role"],
        }
        for member in entities.members(conn, str(row["id"]))
    ]
    return payload


@app.patch("/v1/entities/{slug}")
def patch_entity(
    slug: str,
    body: EntityPatch,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    row = _load_entity(conn, principal, slug)
    entity_id = str(row["id"])
    if not principal.may_write(entity_id) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        updated = conn.execute(
            """UPDATE entities SET
                  name = COALESCE(%s, name),
                  description = COALESCE(%s, description),
                  visibility = COALESCE(%s, visibility)
                WHERE id=%s RETURNING *""",
            (body.name, body.description, body.visibility, entity_id),
        ).fetchone()
    return _entity_row(conn, updated, principal)


@app.post("/v1/entities/{slug}/archive")
def archive_entity(
    slug: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Hide an entity without deleting its memory.

    Archiving rather than deleting because the memories in that scope cite real
    conversations; a project that ended is still a record of what was decided.
    """
    row = _load_entity(conn, principal, slug)
    if row["kind"] in entities.SYSTEM_KINDS:
        raise HTTPException(409, "a user or team entity cannot be archived")
    if not principal.may_write(str(row["id"])) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        conn.execute(
            "UPDATE entities SET archived_at=COALESCE(archived_at, now()) WHERE id=%s",
            (str(row["id"]),),
        )
    return {"id": str(row["id"]), "archived": True}


@app.post("/v1/entities/{slug}/aliases", status_code=201)
def add_entity_alias(
    slug: str,
    body: AliasIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    row = _load_entity(conn, principal, slug)
    if not principal.may_write(str(row["id"])) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        added = entities.add_aliases(conn, entity_id=str(row["id"]), aliases=[body.alias])
    if not added:
        raise HTTPException(409, "alias is already claimed by another entity")
    return {"id": str(row["id"]), "aliases": entities.aliases_of(conn, str(row["id"]))}


@app.delete("/v1/entities/{slug}/aliases/{alias}")
def remove_entity_alias(
    slug: str,
    alias: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    row = _load_entity(conn, principal, slug)
    if not principal.may_write(str(row["id"])) and not principal.is_admin:
        raise HTTPException(403, "entity is read-only for this user")
    with conn.transaction():
        removed = entities.remove_alias(conn, entity_id=str(row["id"]), alias=alias)
    if not removed:
        raise HTTPException(404, "unknown alias")
    return {"recorded": True}


@app.put("/v1/entities/{slug}/members/{user_id}")
def put_member(
    slug: str,
    user_id: str,
    body: MemberIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    row = _load_entity(conn, principal, slug)
    if row["kind"] in entities.SYSTEM_KINDS:
        raise HTTPException(409, "membership of a user or team entity is managed by the system")
    members = {str(m["user_id"]): m["role"] for m in entities.members(conn, str(row["id"]))}
    if members.get(principal.user_id) != "owner" and not principal.is_admin:
        raise HTTPException(403, "only an entity owner or an administrator may change members")
    if users.by_id(conn, user_id) is None:
        raise HTTPException(404, "unknown user")
    with conn.transaction():
        entities.set_member(conn, entity_id=str(row["id"]), user_id=user_id, role=body.role)
    return {"entity_id": str(row["id"]), "user_id": user_id, "role": body.role}


@app.delete("/v1/entities/{slug}/members/{user_id}")
def delete_member(
    slug: str,
    user_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    row = _load_entity(conn, principal, slug)
    if row["kind"] in entities.SYSTEM_KINDS:
        raise HTTPException(409, "membership of a user or team entity is managed by the system")
    members = {str(m["user_id"]): m["role"] for m in entities.members(conn, str(row["id"]))}
    if members.get(principal.user_id) != "owner" and not principal.is_admin:
        raise HTTPException(403, "only an entity owner or an administrator may change members")
    with conn.transaction():
        removed = entities.remove_member(conn, entity_id=str(row["id"]), user_id=user_id)
    if not removed:
        raise HTTPException(404, "user is not a member")
    return {"recorded": True}


@app.post("/v1/entities/resolve")
def resolve_entity(
    body: ResolveIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Turn a name from conversation into an entity, or nothing.

    Exact alias match only. A near match would attach a claim to the wrong
    person, which is worse than reporting that the name is unknown.
    """
    row = entities.resolve_alias(conn, body.name)
    if row is None:
        return {"entity": None}
    return {"entity": _entity_row(conn, row, principal)}


@app.get("/v1/entities/{slug}/profile")
def entity_profile(
    slug: str,
    budget_tokens: int = Query(800, ge=1, le=20_000),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """What is known about this entity, and what lives in its scope.

    Two different questions, answered together because a page about a person
    needs both: facts the team recorded about them, and facts they recorded
    themselves in a scope the caller shares.
    """
    row = _load_entity(conn, principal, slug)
    entity_id = str(row["id"])
    about = conn.execute(
        """SELECT m.*, sc.name AS scope_name FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
            WHERE m.subject_id=%s AND m.status='active' AND m.scope_id = ANY(%s)
            ORDER BY m.importance DESC, m.updated_at DESC LIMIT 100""",
        (entity_id, principal.scopes()),
    ).fetchall()
    in_scope = (
        conn.execute(
            """SELECT m.*, sc.name AS scope_name FROM memories m
                 JOIN entities sc ON sc.id = m.scope_id
                WHERE m.scope_id=%s AND m.status='active' AND m.subject_id IS NULL
                ORDER BY m.importance DESC, m.updated_at DESC LIMIT 100""",
            (entity_id,),
        ).fetchall()
        if entity_id in principal.allowed_scope_ids
        else []
    )
    return {
        "entity": _entity_row(conn, row, principal),
        "about": [_memory_summary(item) for item in about],
        "in_scope": [_memory_summary(item) for item in in_scope],
        "budget_tokens": budget_tokens,
    }


def _memory_summary(row: Any) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": str(data["id"]),
        "text": data["text"],
        "kind": data["kind"],
        "importance": float(data["importance"]),
        "confidence": float(data["confidence"]),
        "review_status": data["review_status"],
        "source_role": data["source_role"],
        "scope": data.get("scope_name"),
        "updated_at": iso(data["updated_at"]),
        "revision": int(data["revision"]),
    }


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


@app.post("/v1/evidence/events", status_code=201)
@app.post("/v1/messages", status_code=201, include_in_schema=False)
def post_message(
    body: MessageIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> MessageOut:
    scope_id = principal_module.resolve_scope(conn, principal, body.scope, write=True)
    try:
        with conn.transaction():
            message_id, deduplicated, redacted = store.add_message(
                conn,
                session_id=body.session_id,
                user_id=principal.user_id,
                scope_id=scope_id,
                agent_id=body.agent_id,
                role=body.role,
                content=body.content,
                external_source=body.external_source,
                external_id=body.external_id,
                context=body.context,
                created_at=body.created_at,
            )
    except store.SessionNotAvailable as exc:
        raise HTTPException(404, "unknown session") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Indexing is the worker's job. Draining inline made the response wait for
    # one embedding per queued row, so a hundred-event hook batch blocked the
    # request for seconds. The response reports `indexed` separately from
    # `stored`, which is what that distinction is for.
    _wake_worker()
    indexed, index_job_id = _outbox_state(conn, vectors.RAW, message_id)
    applicable = body.role == "user" and len(body.content) >= store.MIN_INDEX_CHARS
    extraction_job_id = None
    pending = extract.messages_since_last(conn, body.session_id)
    if judge_configured(settings) and extract.judge.should_extract(
        messages_since_last=pending,
        session_closed=False,
        text=body.content,
    ):
        with conn.transaction():
            extraction_job_id = _queue_extraction(
                conn,
                session_id=body.session_id,
                agent_id=body.agent_id,
                force=True,
                pending=pending,
                user_id=principal.user_id,
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


@app.post("/v1/evidence/events:batch", status_code=201)
def post_evidence_batch(
    body: EvidenceBatchIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> BatchOut:
    stored: list[tuple[MessageIn, int, bool, bool]] = []
    try:
        with conn.transaction():
            for event in body.events:
                scope_id = principal_module.resolve_scope(conn, principal, event.scope, write=True)
                message_id, duplicate, redacted = store.add_message(
                    conn,
                    session_id=event.session_id,
                    user_id=principal.user_id,
                    scope_id=scope_id,
                    agent_id=event.agent_id,
                    role=event.role,
                    content=event.content,
                    external_source=event.external_source,
                    external_id=event.external_id,
                    context=event.context,
                    created_at=event.created_at,
                )
                stored.append((event, message_id, duplicate, redacted))
    except store.SessionNotAvailable as exc:
        raise HTTPException(404, "unknown session") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _wake_worker()
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
        with conn.transaction():
            for session_id, agent_id in sorted(queued_sessions):
                _queue_extraction(
                    conn,
                    session_id=session_id,
                    agent_id=agent_id,
                    force=False,
                    pending=extract.messages_since_last(conn, session_id),
                    user_id=principal.user_id,
                )
        _wake_worker()
    return {"items": results, "count": len(results)}


@app.post("/v1/sessions/{session_id}/close", status_code=202)
def close_session(
    session_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> JobQueuedOut:
    row = conn.execute(
        "SELECT user_id,agent_id FROM sessions WHERE id=%s", (session_id,)
    ).fetchone()
    if row is None or str(row["user_id"]) != principal.user_id:
        raise HTTPException(404, "unknown session")
    with conn.transaction():
        conn.execute(
            "UPDATE sessions SET ended_at=COALESCE(ended_at, now()) WHERE id=%s", (session_id,)
        )
    if not judge_configured(settings):
        return {"job_id": None, "status": "complete", "reason": "judge_not_configured"}
    with conn.transaction():
        job_id = _queue_extraction(
            conn,
            session_id=session_id,
            agent_id=str(row["agent_id"]),
            force=True,
            pending=extract.messages_since_last(conn, session_id),
            user_id=principal.user_id,
        )
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------


@app.post("/v1/memories", status_code=201)
def post_memory(
    body: MemoryIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryCreatedOut:
    """Save one memory.

    A user's own manual save into their own scope is confirmed immediately:
    they just said it, so asking them to confirm it again is noise. Anything
    else -- a shared scope, or a model-authored write -- starts pending.
    """
    scope_id = principal_module.resolve_scope(conn, principal, body.scope, write=True)
    subject_id = principal_module.resolve_subject(conn, principal, body.subject)
    self_asserted = body.source_role in {"user", "manual"} and scope_id == principal.own_entity_id
    try:
        with conn.transaction():
            existing = store.find_duplicate(
                conn, scope_id=scope_id, text=body.text, kind=body.kind, context=body.context
            )
            if existing is not None:
                return MemoryCreatedOut(
                    id=str(existing["id"]),
                    stored=True,
                    indexed=True,
                    deduplicated=True,
                    review_status=str(existing["review_status"]),
                )
            memory_id = store.add_memory(
                conn,
                scope_id=scope_id,
                subject_id=subject_id,
                author_id=principal.user_id,
                text=body.text,
                kind=body.kind,
                context=body.context,
                tags=list(body.tags),
                agent_id=body.agent_id,
                importance=body.importance,
                confidence=body.confidence,
                valid_until=body.valid_until,
                source_role=body.source_role,
                review_status="confirmed" if self_asserted else "pending",
            )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _drain()
    indexed, job_id = _outbox_state(conn, vectors.MEMORIES, memory_id)
    return MemoryCreatedOut(
        id=memory_id,
        stored=True,
        indexed=indexed,
        index_job_id=job_id,
        review_status="confirmed" if self_asserted else "pending",
    )


@app.patch("/v1/memories/{memory_id}")
def patch_memory(
    memory_id: str,
    body: MemoryPatch,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    memory_id = _memory_id(memory_id)
    current = conn.execute(
        "SELECT * FROM memories WHERE id=%s AND scope_id = ANY(%s)",
        (memory_id, principal.scopes()),
    ).fetchone()
    if current is None:
        raise HTTPException(404, "unknown memory")
    if not principal.may_write(str(current["scope_id"])):
        raise HTTPException(403, "memory is read-only for this user")
    context = dict(current["context"] or {})
    if body.context is not None and body.context != context and not body.move_context:
        raise HTTPException(422, "changing context requires move_context=true")
    scope_id = None
    if body.scope is not None:
        if not body.move_scope:
            raise HTTPException(422, "changing scope requires move_scope=true")
        scope_id = principal_module.resolve_scope(conn, principal, body.scope, write=True)
    subject_id = current["subject_id"]
    if body.clear_subject:
        subject_id = None
    elif body.subject is not None:
        subject_id = principal_module.resolve_subject(conn, principal, body.subject)
    valid_until = current["valid_until"]
    if body.clear_valid_until:
        valid_until = None
    elif body.valid_until is not None:
        valid_until = body.valid_until
    try:
        with conn.transaction():
            saved = store.update_memory(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                expected_revision=body.expected_revision,
                text=body.text or str(current["text"]),
                kind=body.kind or str(current["kind"]),
                context=body.context if body.context is not None else context,
                tags=list(body.tags) if body.tags is not None else list(current["tags"] or []),
                importance=body.importance
                if body.importance is not None
                else float(current["importance"]),
                confidence=body.confidence
                if body.confidence is not None
                else float(current["confidence"]),
                valid_until=valid_until,
                subject_id=subject_id,
                scope_id=scope_id,
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    _drain()
    return {"id": memory_id, "revision": int(saved["revision"]), "status": saved["status"]}


@app.delete("/v1/memories/{memory_id}")
def delete_memory(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    """Archive a memory. Reversible, because a mistaken delete is common."""
    memory_id = _memory_id(memory_id)
    try:
        with conn.transaction():
            saved = store.set_memory_status(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                status="archived",
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    _drain()
    return {"id": memory_id, "revision": int(saved["revision"]), "status": saved["status"]}


@app.post("/v1/memories/{memory_id}/restore")
def restore_memory(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    memory_id = _memory_id(memory_id)
    try:
        with conn.transaction():
            saved = store.set_memory_status(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                status="active",
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    _drain()
    return {"id": memory_id, "revision": int(saved["revision"]), "status": saved["status"]}


@app.post("/v1/memories/{memory_id}/review")
def review_memory(
    memory_id: str,
    body: ReviewIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    """Confirm or delete an unreviewed memory, or undo that decision."""
    memory_id = _memory_id(memory_id)
    status = {"confirm": "confirmed", "decline": "declined", "undo": "pending"}[body.decision]
    try:
        with conn.transaction():
            saved = store.set_review_status(
                conn,
                memory_id=memory_id,
                scopes=sorted(principal.writable_scope_ids),
                review_status=status,
                reviewed_by=principal.user_id,
                expected_revision=body.expected_revision,
            )
    except KeyError as exc:
        raise HTTPException(404, "unknown memory") from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    _drain()
    return {
        "id": memory_id,
        "revision": int(saved["revision"]),
        "status": saved["status"],
        "review_status": saved["review_status"],
    }


_SORTABLE = {
    "updated_at": "m.updated_at",
    "created_at": "m.created_at",
    "importance": "m.importance",
    "confidence": "m.confidence",
    "retrieval_count": "m.retrieval_count",
}


@app.get("/v1/memories")
def list_memories(
    q: str | None = None,
    kind: str | None = None,
    status: str = "active",
    source_role: str | None = None,
    scope: str | None = None,
    subject: str | None = None,
    review_status: str | None = None,
    tag: str | None = None,
    importance_min: float | None = Query(None, ge=0, le=1),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> OffsetPageOut:
    """Filterable, sortable listing with a real total.

    Ordered by recency by default. The previous implementation paged by uuid
    while the dashboard called the result "recent memories", so the list was in
    an arbitrary order that looked chronological.
    """
    if sort not in _SORTABLE:
        raise HTTPException(422, f"cannot sort by {sort!r}")
    direction = "DESC" if order.lower() == "desc" else "ASC"
    scopes = (
        [principal_module.resolve_scope(conn, principal, scope)] if scope else principal.scopes()
    )
    subject_id = principal_module.resolve_subject(conn, principal, subject) if subject else None
    params: dict[str, Any] = {
        "scopes": scopes,
        "status": status,
        "kind": kind,
        "source_role": source_role,
        "subject": subject_id,
        "review_status": review_status,
        "tag": tag,
        "importance_min": importance_min,
        "created_from": created_from,
        "created_to": created_to,
        "query": q,
        "limit": limit,
        "offset": offset,
    }
    where = """
        WHERE m.scope_id = ANY(%(scopes)s)
          AND (%(status)s::text IS NULL OR %(status)s = 'any' OR m.status = %(status)s)
          AND (%(kind)s::text IS NULL OR m.kind = %(kind)s)
          AND (%(source_role)s::text IS NULL OR m.source_role = %(source_role)s)
          AND (%(subject)s::uuid IS NULL OR m.subject_id = %(subject)s)
          AND (%(review_status)s::text IS NULL OR m.review_status = %(review_status)s)
          AND (%(tag)s::text IS NULL OR m.tags ? %(tag)s)
          AND (%(importance_min)s::real IS NULL OR m.importance >= %(importance_min)s)
          AND (%(created_from)s::timestamptz IS NULL OR m.created_at >= %(created_from)s)
          AND (%(created_to)s::timestamptz IS NULL OR m.created_at <= %(created_to)s)
          AND (
              %(query)s::text IS NULL
              OR m.search_tsv @@ plainto_tsquery('russian', %(query)s)
              OR m.text ILIKE '%%' || %(query)s || '%%'
          )
    """
    total_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM memories m {where}",
        params,
    ).fetchone()
    rows = conn.execute(
        f"""SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                   sub.name AS subject_name, sub.slug AS subject_slug,
                   u.handle AS author_handle
              FROM memories m
              JOIN entities sc ON sc.id = m.scope_id
              LEFT JOIN entities sub ON sub.id = m.subject_id
              LEFT JOIN users u ON u.id = m.author_id
              {where}
             ORDER BY {_SORTABLE[sort]} {direction}, m.id
             LIMIT %(limit)s OFFSET %(offset)s""",
        params,
    ).fetchall()
    items = []
    for row in rows:
        item = _memory_summary(row)
        item.update(
            {
                "scope_slug": row["scope_slug"],
                "subject": row["subject_name"],
                "subject_slug": row["subject_slug"],
                "author": row["author_handle"],
                "status": row["status"],
                "context": dict(row["context"] or {}),
                "tags": list(row["tags"] or []),
                "created_at": iso(row["created_at"]),
                "valid_until": iso(row["valid_until"]),
                "retrieval_count": int(row["retrieval_count"]),
                "last_retrieved_at": iso(row["last_retrieved_at"]),
            }
        )
        items.append(item)
    return {
        "items": items,
        "total": int(total_row["n"]) if total_row else 0,
        "limit": limit,
        "offset": offset,
    }


@app.get("/v1/memories/{memory_id}")
def get_memory(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryOut:
    """One memory, including `revision`.

    A correction is a PATCH carrying `expected_revision`, so an agent needs a
    way to read the current revision of a single fact. Search results carry it
    too, but an id learned from a profile block has nowhere else to come from.
    """
    memory_id = _memory_id(memory_id)
    row = conn.execute(
        """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                  sub.name AS subject_name, sub.slug AS subject_slug,
                  u.handle AS author_handle
             FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
             LEFT JOIN entities sub ON sub.id = m.subject_id
             LEFT JOIN users u ON u.id = m.author_id
            WHERE m.id=%s AND m.scope_id = ANY(%s)""",
        (memory_id, principal.scopes()),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown memory")
    memory = _memory_summary(row)
    memory.update(
        {
            "scope_slug": row["scope_slug"],
            "subject": row["subject_name"],
            "subject_slug": row["subject_slug"],
            "author": row["author_handle"],
            "status": row["status"],
            "context": dict(row["context"] or {}),
            "tags": list(row["tags"] or []),
            "created_at": iso(row["created_at"]),
            "valid_until": iso(row["valid_until"]),
            "judge_run_id": row["judge_run_id"],
            "extraction_version": row["extraction_version"],
            "writable": principal.may_write(str(row["scope_id"])),
            "sessions": [
                str(item["session_id"])
                for item in conn.execute(
                    """SELECT DISTINCT ms.session_id FROM memory_sources s
                         JOIN messages ms ON ms.id = s.message_id
                        WHERE s.memory_id=%s""",
                    (memory_id,),
                )
            ],
        }
    )
    return {"memory": memory}


@app.get("/v1/memories/{memory_id}/sources")
def memory_sources(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemorySourcesOut:
    memory_id = _memory_id(memory_id)
    memory = conn.execute(
        "SELECT * FROM memories WHERE id=%s AND scope_id = ANY(%s)",
        (memory_id, principal.scopes()),
    ).fetchone()
    if memory is None:
        raise HTTPException(404, "unknown memory")
    evidence = [
        {
            "message_id": int(row["message_id"]),
            "start_char": int(row["start_char"]),
            "end_char": int(row["end_char"]),
            "excerpt_sha256": row["excerpt_sha256"],
            "role": row["role"],
            "content": row["content"],
            "created_at": iso(row["created_at"]),
        }
        for row in conn.execute(
            """SELECT e.*,m.role,m.content,m.created_at FROM memory_evidence e
                 JOIN messages m ON m.id=e.message_id WHERE e.memory_id=%s
                 ORDER BY e.message_id,e.start_char""",
            (memory_id,),
        )
    ]
    return {
        "memory": _memory_summary(memory),
        "source_role": str(memory["source_role"]),
        "evidence": evidence,
    }


@app.get("/v1/memories/{memory_id}/history")
def memory_history(
    memory_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MemoryHistoryOut:
    memory_id = _memory_id(memory_id)
    memory = conn.execute(
        "SELECT * FROM memories WHERE id=%s AND scope_id = ANY(%s)",
        (memory_id, principal.scopes()),
    ).fetchone()
    if memory is None:
        raise HTTPException(404, "unknown memory")
    revisions = [
        {
            "revision": int(row["revision"]),
            "text": row["text"],
            "kind": row["kind"],
            "status": row["status"],
            "review_status": row["review_status"],
            "importance": float(row["importance"]),
            "confidence": float(row["confidence"]),
            "context": dict(row["context"] or {}),
            "tags": list(row["tags"] or []),
            "source_role": row["source_role"],
            "extraction_version": row["extraction_version"],
            "created_at": iso(row["created_at"]),
        }
        for row in conn.execute(
            "SELECT * FROM memory_revisions WHERE memory_id=%s ORDER BY revision DESC",
            (memory_id,),
        )
    ]
    predecessors = [
        _memory_summary(row)
        for row in conn.execute("SELECT * FROM memories WHERE superseded_by=%s", (memory_id,))
    ]
    successor_row = (
        conn.execute(
            "SELECT * FROM memories WHERE id=%s", (str(memory["superseded_by"]),)
        ).fetchone()
        if memory["superseded_by"]
        else None
    )
    return {
        "memory": _memory_summary(memory),
        "revisions": revisions,
        "predecessors": predecessors,
        "successor": _memory_summary(successor_row) if successor_row else None,
    }


# ---------------------------------------------------------------------------
# Search, review queue, profile
# ---------------------------------------------------------------------------


@app.post("/v1/memories/search")
@app.post("/v1/search", include_in_schema=False)
def search_memories(
    body: SearchIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> MemorySearchOut:
    if not getattr(app.state, "index_ready", False):
        raise HTTPException(503, "vector search dependency is temporarily unavailable")
    scopes = (
        [principal_module.resolve_scope(conn, principal, item) for item in body.scopes]
        if body.scopes
        else principal.scopes()
    )
    expression = body.filter
    if body.subject:
        subject_id = principal_module.resolve_subject(conn, principal, body.subject)
        subject_clause = {"field": "subject_id", "op": "eq", "value": subject_id}
        expression = {"all": [expression, subject_clause]} if expression else subject_clause
    try:
        policy = retrieval.load_policy(conn, body.policy_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    started = time.perf_counter()
    try:
        result = retrieval.explain(
            conn,
            app.state.qdrant,
            app.state.embedder,
            query=body.query,
            scope_ids=scopes,
            expression=expression,
            kinds=body.kinds,
            limit=body.limit,
            budget_tokens=body.budget_tokens,
            policy=policy,
            include_untrusted=body.include_untrusted,
            reranker=getattr(app.state, "reranker", None),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        app.state.index_ready = False
        app.state.index_error = str(exc)
        logger.warning("vector search failed; dependency monitor will reconnect")
        raise HTTPException(503, "vector search dependency is temporarily unavailable") from exc
    result.timings["request_ms"] = (time.perf_counter() - started) * 1000
    with conn.transaction():
        retrieval_id = telemetry.record_retrieval_run(
            conn,
            user_id=principal.user_id,
            query_hash=telemetry.hash_query(settings.telemetry_hmac_key, body.query),
            policy_id=result.policy_id,
            results=[item.as_dict() for item in result.chosen],
            timings=result.timings,
            used_tokens=result.used_tokens,
        )
        if result.chosen:
            store.record_retrieval(conn, [item.id for item in result.chosen])
    raw = (
        store.search_raw(
            app.state.qdrant,
            app.state.embedder,
            query=body.query,
            scope_ids=scopes,
            limit=body.limit,
            vector=result.query_vector,
        )
        if body.include_raw
        else []
    )
    payload = result.as_dict()
    if body.include_sources and result.chosen:
        excerpts = store.evidence_excerpts(conn, [item.id for item in result.chosen])
        for memory in payload["memories"]:
            memory["sources"] = excerpts.get(memory["id"], [])
    return {**payload, "raw": raw, "retrieval_id": retrieval_id}


@app.post("/v1/retrieval-feedback", status_code=201)
def retrieval_feedback(
    body: FeedbackIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> FeedbackOut:
    row = conn.execute(
        "SELECT 1 FROM memories WHERE id=%s AND scope_id = ANY(%s)",
        (body.memory_id, principal.scopes()),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown memory")
    with conn.transaction():
        store.record_feedback(
            conn,
            memory_id=body.memory_id,
            query_hash=telemetry.hash_query(settings.telemetry_hmac_key, body.query),
            useful=body.useful,
            correct=body.correct,
        )
    return {"recorded": True}


@app.post("/v1/retrieval-runs/{retrieval_id}/feedback", status_code=201)
def retrieval_run_feedback(
    retrieval_id: str,
    body: RetrievalRunFeedbackIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FeedbackOut:
    try:
        with conn.transaction():
            telemetry.record_run_feedback(
                conn,
                retrieval_id=retrieval_id,
                user_id=principal.user_id,
                memory_id=body.memory_id,
                useful=body.useful,
                correct=body.correct,
            )
    except LookupError as exc:
        raise HTTPException(404, "unknown retrieval run") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"recorded": True}


@app.get("/v1/retrieval-runs")
def recent_retrieval_runs(
    limit: int = Query(20, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    return {
        "items": telemetry.recent_runs(
            conn,
            user_id=principal.user_id,
            allowed_scope_ids=principal.scopes(),
            limit=limit,
        )
    }


@app.get("/v1/review")
def review_queue(
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
    settings: Settings = Depends(get_settings),
) -> ItemsOut:
    """Everything waiting on a person.

    Four different things share one queue because they share one question --
    "is this right?" -- and splitting them across screens is how a queue stops
    being read. Pending memories are found by their review status rather than
    duplicated into a work table, so confirming one cannot leave a stale row.
    """
    items: list[dict[str, Any]] = []
    if kind in (None, "memory"):
        rows = conn.execute(
            """SELECT m.*, sc.name AS scope_name, sc.slug AS scope_slug,
                      sub.name AS subject_name, u.handle AS author_handle,
                      prev.text AS previous_text
                 FROM memories m
                 JOIN entities sc ON sc.id = m.scope_id
                 LEFT JOIN entities sub ON sub.id = m.subject_id
                 LEFT JOIN users u ON u.id = m.author_id
                 LEFT JOIN memory_revisions prev
                        ON prev.memory_id = m.id AND prev.revision = m.revision - 1
                WHERE m.scope_id = ANY(%s) AND m.status='active'
                  AND m.review_status='pending'
                ORDER BY m.created_at DESC
                LIMIT %s OFFSET %s""",
            (principal.scopes(), limit, offset),
        ).fetchall()
        for row in rows:
            item = _memory_summary(row)
            items.append(
                {
                    "id": str(row["id"]),
                    "kind": "memory",
                    "title": row["text"],
                    "memory": item,
                    "author": row["author_handle"],
                    "subject": row["subject_name"],
                    # An update to a confirmed fact keeps the new text live and
                    # returns for review, so the reviewer needs the old wording.
                    "previous_text": row["previous_text"],
                    "created_at": iso(row["created_at"]),
                    "actions": ["confirm", "decline"],
                }
            )
    if kind in (None, "unresolved_mention", "conflict"):
        rows = conn.execute(
            """SELECT n.*, m.text AS memory_text FROM needs_attention n
                 LEFT JOIN memories m ON m.id = n.ref_memory_id
                WHERE n.user_id=%s AND n.status='open'
                  AND n.kind = ANY(%s)
                ORDER BY n.created_at DESC LIMIT %s OFFSET %s""",
            (
                principal.user_id,
                ["unresolved_mention", "conflict"] if kind is None else [kind],
                limit,
                offset,
            ),
        ).fetchall()
        for row in rows:
            payload = dict(row["payload"] or {})
            items.append(
                {
                    "id": str(row["id"]),
                    "kind": row["kind"],
                    "title": payload.get("name") or row["memory_text"] or "",
                    "detail": row["memory_text"],
                    "memory_id": str(row["ref_memory_id"]) if row["ref_memory_id"] else None,
                    "payload": payload,
                    "created_at": iso(row["created_at"]),
                    "actions": ["link_entity", "dismiss"],
                }
            )
    if kind in (None, "failed_job"):
        rows = conn.execute(
            """SELECT j.* FROM jobs j
                WHERE j.status='failed' AND j.created_at > now() - interval '7 days'
                  AND (j.user_id = %s OR %s)
                  AND NOT EXISTS (
                      SELECT 1 FROM needs_attention n
                       WHERE n.ref_job_id = j.id AND n.status='resolved'
                  )
                ORDER BY j.created_at DESC LIMIT %s""",
            (principal.user_id, principal.is_admin, limit),
        ).fetchall()
        for row in rows:
            items.append(
                {
                    "id": str(row["id"]),
                    "kind": "failed_job",
                    "title": f"{row['kind']} job failed",
                    "detail": row["error"],
                    "error_code": row["error_code"],
                    "created_at": iso(row["created_at"]),
                    "actions": ["dismiss"],
                }
            )
    if kind in (None, "budget"):
        spend = float(
            (
                conn.execute(
                    """SELECT COALESCE(SUM(cost_usd),0) AS s FROM judge_runs
                        WHERE to_char(created_at AT TIME ZONE 'UTC','YYYY-MM') = %s""",
                    (datetime.now(UTC).strftime("%Y-%m"),),
                ).fetchone()
                or {"s": 0}
            )["s"]
        )
        limit_usd = settings.monthly_cost_limit_usd
        if limit_usd and spend >= limit_usd * 0.8:
            items.append(
                {
                    "id": "budget",
                    "kind": "budget",
                    "title": f"Model spend is at {spend / limit_usd:.0%} of the monthly limit",
                    "detail": f"{spend:.2f} of {limit_usd:.2f} USD",
                    "created_at": iso(utcnow()),
                    "actions": ["dismiss"],
                }
            )
    return {"items": items}


@app.post("/v1/attention/{item_id}/resolve")
def resolve_attention(
    item_id: str,
    body: AttentionResolveIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    """Place an unresolved name, or dismiss the item.

    Linking does two things at once on purpose: it attributes the memory to the
    person and teaches the alias, so the same name resolves by itself next time.
    """
    row = conn.execute(
        "SELECT * FROM needs_attention WHERE id=%s AND user_id=%s AND status='open'",
        (item_id, principal.user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "unknown or already resolved item")
    resolution: dict[str, Any] = {"action": body.action}
    with conn.transaction():
        if body.action == "link_entity":
            if not body.entity:
                raise HTTPException(422, "link_entity requires an entity")
            target = entities.by_slug(conn, body.entity)
            if target is None:
                raise HTTPException(404, "unknown entity")
            name = str((row["payload"] or {}).get("name") or "")
            if row["ref_memory_id"] is not None:
                memory = conn.execute(
                    "SELECT * FROM memories WHERE id=%s", (str(row["ref_memory_id"]),)
                ).fetchone()
                if memory is not None:
                    team = entities.team(conn)
                    store.update_memory(
                        conn,
                        memory_id=str(memory["id"]),
                        scopes=sorted(principal.writable_scope_ids),
                        expected_revision=int(memory["revision"]),
                        text=str(memory["text"]),
                        kind=str(memory["kind"]),
                        context=dict(memory["context"] or {}),
                        tags=list(memory["tags"] or []),
                        importance=float(memory["importance"]),
                        confidence=float(memory["confidence"]),
                        valid_until=memory["valid_until"],
                        subject_id=str(target["id"]),
                        # A fact about a person belongs where the team can see
                        # it, which is what routing would have done had the
                        # name resolved at extraction time.
                        scope_id=str(team["id"]) if team and target["kind"] == "user" else None,
                    )
            if name:
                entities.add_aliases(conn, entity_id=str(target["id"]), aliases=[name])
                resolution["alias_taught"] = name
            resolution["entity_id"] = str(target["id"])
        conn.execute(
            """UPDATE needs_attention
                  SET status='resolved',resolved_at=now(),resolved_by=%s,
                      payload = payload || %s
                WHERE id=%s""",
            (principal.user_id, Jsonb({"resolution": resolution}), item_id),
        )
    _drain()
    return {"id": item_id, "status": "resolved", **resolution}


@app.post("/v1/profiles/render")
def render_profile(
    body: ProfileIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ProfileOut:
    """The block an agent injects at the start of a session."""
    project_scope_id = None
    if body.workspace:
        # An unknown or inaccessible workspace is not an error here: a hook
        # sends whatever repository it is in, and a session that happens not to
        # map to an entity should still get the rest of the profile.
        with suppress(ScopeForbidden, UnknownScope):
            project_scope_id = principal_module.resolve_scope(conn, principal, body.workspace)
    return profiles.render(
        conn,
        own_scope_id=principal.own_entity_id,
        team_scope_id=principal.team_entity_id,
        allowed_scope_ids=principal.scopes(),
        project_scope_id=project_scope_id,
        dynamic_days=body.dynamic_days,
        budget_tokens=body.budget_tokens,
        blocks=body.blocks,
        include_untrusted=body.include_untrusted,
    )


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------


@app.get("/v1/policies")
def list_policies(
    kind: str | None = None,
    scope: str | None = None,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    scope_id = principal_module.resolve_scope(conn, principal, scope) if scope else None
    rows = policies.list_policies(conn, scope_id=scope_id, kind=kind)
    return {
        "items": [
            {
                "id": row["id"],
                "scope_id": str(row["scope_id"]) if row["scope_id"] else None,
                "kind": row["kind"],
                "name": row["name"],
                "version": int(row["version"]),
                "config": dict(row["config"] or {}),
                "created_at": iso(row["created_at"]),
            }
            for row in rows
        ]
    }


@app.post("/v1/policies", status_code=201)
def create_policy(
    body: PolicyIn,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> EntityOut:
    scope_id = (
        principal_module.resolve_scope(conn, principal, body.scope, write=True)
        if body.scope
        else None
    )
    try:
        with conn.transaction():
            policy_id = policies.put_policy(
                conn,
                scope_id=scope_id,
                kind=body.kind,
                name=body.name,
                version=body.version,
                config=body.config,
            )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"id": policy_id}


# ---------------------------------------------------------------------------
# Privacy and administration
# ---------------------------------------------------------------------------


@app.post("/v1/export", status_code=202)
def export_data(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Export everything this user owns or authored."""
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="export",
            input_data={
                "user_id": principal.user_id,
                "private_scope_id": principal.own_entity_id,
                "authored_scopes": principal.scopes(),
            },
            user_id=principal.user_id,
        )
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


@app.post("/v1/users/{user_id}/erase", status_code=202)
def erase_user_data(
    user_id: str,
    body: EraseIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Erase one user's private data.

    A user may erase themselves; only an administrator may erase somebody else.
    Memories they authored in shared scopes are the team's record and are not
    removed -- the job refuses rather than deleting them, and says how many.
    """
    if user_id != principal.user_id and not principal.is_admin:
        raise HTTPException(403, "only an administrator may erase another user")
    own = entities.own_entity(conn, user_id)
    if own is None:
        raise HTTPException(404, "unknown user")
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="erase",
            input_data={"user_id": user_id, "private_scope_id": str(own["id"])},
            user_id=principal.user_id,
        )
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


@app.post("/v1/admin/reindex", status_code=202)
def start_reindex(
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    with conn.transaction():
        job_id = jobs.create(conn, kind="reindex", user_id=principal.user_id)
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


@app.post("/v1/admin/consolidate", status_code=202)
def start_consolidation(
    body: ConsolidateIn,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Consolidate the caller's scopes, or every scope for an administrator."""
    scope_ids = (
        [str(row["id"]) for row in conn.execute("SELECT id FROM entities")]
        if principal.is_admin
        else sorted(principal.writable_scope_ids)
    )
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="consolidation",
            input_data={
                "scope_ids": scope_ids,
                "dry_run": body.dry_run,
                "merge": body.merge,
            },
            call_limit=0 if body.dry_run else 20,
            user_id=principal.user_id,
        )
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


@app.post("/v1/admin/reextract", status_code=202)
def start_reextract_report(
    body: ReplayIn | None = None,
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    """Plan a re-extraction. Reports only; it never rewrites the store."""
    del body
    with conn.transaction():
        job_id = jobs.create(
            conn,
            kind="reextract_report",
            input_data={"scope_ids": sorted(principal.writable_scope_ids)},
            user_id=principal.user_id,
        )
    _wake_worker()
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs")
def list_jobs(
    status: str | None = None,
    kind: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    rows = conn.execute(
        """SELECT j.*, u.handle AS user_handle FROM jobs j
             LEFT JOIN users u ON u.id = j.user_id
            WHERE (%s::text IS NULL OR j.status=%s)
              AND (%s::text IS NULL OR j.kind=%s)
              AND (j.user_id = %s OR j.user_id IS NULL OR %s)
            ORDER BY j.created_at DESC LIMIT %s""",
        (status, status, kind, kind, principal.user_id, principal.is_admin, limit),
    ).fetchall()
    return {
        "items": [
            {
                "id": str(row["id"]),
                "kind": row["kind"],
                "status": row["status"],
                "user": row["user_handle"],
                "error": row["error"],
                "error_code": row["error_code"],
                "result": row["result"],
                "created_at": iso(row["created_at"]),
                "finished_at": iso(row["finished_at"]),
            }
            for row in rows
        ]
    }


@app.get("/v1/jobs/{job_id}")
def get_job(
    job_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobOut:
    try:
        row = jobs.get(conn, job_id)
    except KeyError as exc:
        raise HTTPException(404, "unknown job") from exc
    if (
        row["user_id"] is not None
        and str(row["user_id"]) != principal.user_id
        and not principal.is_admin
    ):
        raise HTTPException(404, "unknown job")
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "status": row["status"],
        "result": row["result"],
        "error": row["error"],
        "error_code": row["error_code"],
        "created_at": iso(row["created_at"]),
        "finished_at": iso(row["finished_at"]),
        "events": jobs.history(conn, job_id),
    }


@app.post("/v1/jobs/{job_id}/cancel", status_code=202)
def cancel_job(
    job_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JobQueuedOut:
    try:
        row = jobs.get(conn, job_id)
    except KeyError as exc:
        raise HTTPException(404, "unknown job") from exc
    if (
        row["user_id"] is not None
        and str(row["user_id"]) != principal.user_id
        and not principal.is_admin
    ):
        raise HTTPException(404, "unknown job")
    with conn.transaction():
        jobs.request_cancel(conn, job_id)
    return {"job_id": job_id, "status": "cancel_requested"}


@app.get("/v1/admin/sessions")
def list_sessions(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> OffsetPageOut:
    """Conversations, with what each one produced.

    Administrators see the instance; everyone else sees their own, because a
    transcript is the rawest thing the system holds.
    """
    total = conn.execute(
        """SELECT COUNT(*) AS n FROM sessions
            WHERE user_id = %s OR %s""",
        (principal.user_id, principal.is_admin),
    ).fetchone()
    rows = conn.execute(
        """SELECT s.*, u.handle AS user_handle, e.name AS scope_name, e.slug AS scope_slug,
                  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS messages,
                  (SELECT COUNT(DISTINCT ms.memory_id) FROM memory_sources ms
                     JOIN messages m2 ON m2.id = ms.message_id
                    WHERE m2.session_id = s.id) AS extracted
             FROM sessions s
             JOIN users u ON u.id = s.user_id
             JOIN entities e ON e.id = s.scope_id
            WHERE s.user_id = %s OR %s
            ORDER BY s.started_at DESC LIMIT %s OFFSET %s""",
        (principal.user_id, principal.is_admin, limit, offset),
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "user": row["user_handle"],
                "scope": row["scope_name"],
                "scope_slug": row["scope_slug"],
                "agent_id": row["agent_id"],
                "started_at": iso(row["started_at"]),
                "ended_at": iso(row["ended_at"]),
                "context": dict(row["context"] or {}),
                "messages": int(row["messages"]),
                "extracted": int(row["extracted"]),
            }
            for row in rows
        ],
        "total": int(total["n"]) if total else 0,
        "limit": limit,
        "offset": offset,
    }


@app.get("/v1/admin/sessions/{session_id}/messages")
def list_session_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> SessionMessagesOut:
    session = conn.execute("SELECT * FROM sessions WHERE id=%s", (session_id,)).fetchone()
    if session is None or (str(session["user_id"]) != principal.user_id and not principal.is_admin):
        raise HTTPException(404, "unknown session")
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM messages WHERE session_id=%s", (session_id,)
    ).fetchone()
    rows = conn.execute(
        """SELECT * FROM messages WHERE session_id=%s ORDER BY id LIMIT %s OFFSET %s""",
        (session_id, limit, offset),
    ).fetchall()
    return {
        "session": {
            "id": session["id"],
            "user_id": str(session["user_id"]),
            "scope_id": str(session["scope_id"]),
            "agent_id": session["agent_id"],
            "started_at": iso(session["started_at"]),
            "ended_at": iso(session["ended_at"]),
        },
        "items": [
            {
                "id": int(row["id"]),
                "role": row["role"],
                "content": row["content"],
                "created_at": iso(row["created_at"]),
                "processed": bool(row["processed"]),
                "redacted": bool(row["redacted"]),
            }
            for row in rows
        ],
        "total": int(total["n"]) if total else 0,
        "limit": limit,
        "offset": offset,
    }


@app.get("/v1/admin/sessions/{session_id}/memories")
def list_session_memories(
    session_id: str,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    """What this conversation produced, and what it refused to produce.

    The rejections matter as much as the facts: they are the only place the
    reason a plausible-looking claim was dropped is visible.
    """
    session = conn.execute("SELECT * FROM sessions WHERE id=%s", (session_id,)).fetchone()
    if session is None or (str(session["user_id"]) != principal.user_id and not principal.is_admin):
        raise HTTPException(404, "unknown session")
    rows = conn.execute(
        """SELECT DISTINCT m.*, sc.name AS scope_name FROM memories m
             JOIN entities sc ON sc.id = m.scope_id
             JOIN memory_sources ms ON ms.memory_id = m.id
             JOIN messages msg ON msg.id = ms.message_id
            WHERE msg.session_id = %s AND m.scope_id = ANY(%s)
            ORDER BY m.created_at""",
        (session_id, principal.scopes()),
    ).fetchall()
    memories = []
    for row in rows:
        item = _memory_summary(row)
        item["evidence"] = [
            {
                "message_id": int(span["message_id"]),
                "start_char": int(span["start_char"]),
                "end_char": int(span["end_char"]),
            }
            for span in conn.execute(
                "SELECT * FROM memory_evidence WHERE memory_id=%s ORDER BY message_id,start_char",
                (str(row["id"]),),
            )
        ]
        memories.append(item)
    extraction_jobs = conn.execute(
        """SELECT id,status,result,error,created_at FROM jobs
            WHERE kind='extraction' AND input->>'session_id' = %s
            ORDER BY created_at""",
        (session_id,),
    ).fetchall()
    return {
        "items": memories,
        **{
            "jobs": [
                {
                    "id": str(job["id"]),
                    "status": job["status"],
                    "result": job["result"],
                    "error": job["error"],
                    "created_at": iso(job["created_at"]),
                }
                for job in extraction_jobs
            ]
        },
    }


@app.get("/v1/admin/judge-runs")
def list_judge_runs(
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> ItemsOut:
    rows = conn.execute(
        """SELECT j.id,j.kind,j.model,j.prompt_version,j.error,j.input_tokens,j.output_tokens,
                  j.cost_usd,j.latency_ms,j.created_at,u.handle AS user_handle
             FROM judge_runs j LEFT JOIN users u ON u.id = j.user_id
            WHERE j.user_id = %s OR j.user_id IS NULL OR %s
            ORDER BY j.created_at DESC LIMIT %s""",
        (principal.user_id, principal.is_admin, limit),
    ).fetchall()
    return {
        "items": [
            {
                "id": int(row["id"]),
                "kind": row["kind"],
                "model": row["model"],
                "prompt_version": row["prompt_version"],
                "error": row["error"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None,
                "latency_ms": row["latency_ms"],
                "user": row["user_handle"],
                "created_at": iso(row["created_at"]),
            }
            for row in rows
        ]
    }


@app.get("/v1/admin/judge-runs/{run_id}")
def get_judge_run(
    run_id: int,
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> JudgeRunOut:
    row = conn.execute("SELECT * FROM judge_runs WHERE id=%s", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "unknown judge run")
    if (
        row["user_id"] is not None
        and str(row["user_id"]) != principal.user_id
        and not principal.is_admin
    ):
        raise HTTPException(404, "unknown judge run")
    return {
        "id": int(row["id"]),
        "kind": row["kind"],
        "model": row["model"],
        "prompt_version": row["prompt_version"],
        "input": row["input"],
        "output": row["output"],
        "error": row["error"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "cost_usd": float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        "latency_ms": row["latency_ms"],
        "created_at": iso(row["created_at"]),
    }


@app.get("/v1/admin/health")
def admin_health(
    principal: Principal = Depends(require_admin),
    conn: psycopg.Connection = Depends(get_conn),
) -> FlexibleOut:
    index_ready = getattr(app.state, "index_ready", False)
    memory_count = raw_count = None
    if index_ready:
        try:
            memory_count = vectors.count(app.state.qdrant, vectors.MEMORIES)
            raw_count = vectors.count(app.state.qdrant, vectors.RAW)
        except Exception as exc:
            app.state.index_ready = False
            app.state.index_error = str(exc)
            index_ready = False
    version = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return {
        "database": {"schema_version": int(version["v"]) if version and version["v"] else None},
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
            row["status"]: int(row["n"])
            for row in conn.execute("SELECT status,COUNT(*) AS n FROM jobs GROUP BY status")
        },
    }


@app.get("/v1/admin/metrics")
def metrics(
    principal: Principal = Depends(get_principal),
    conn: psycopg.Connection = Depends(get_conn),
) -> MetricsOut:
    """Instance metrics for an administrator, own metrics for anyone else."""
    period = datetime.now(UTC).strftime("%Y-%m")
    scope = None if principal.is_admin else principal.user_id
    retrieval_metrics = telemetry.metrics(conn, scope)
    active_memories = conn.execute(
        "SELECT COUNT(*) AS n FROM memories WHERE status='active' AND scope_id = ANY(%s)",
        (principal.scopes(),),
    ).fetchone()
    indexed_memories: int | None = None
    if getattr(app.state, "index_ready", True):
        with suppress(Exception):
            indexed_memories = vectors.count(app.state.qdrant, vectors.MEMORIES)
    row = conn.execute(
        """SELECT
              (SELECT MIN(created_at) FROM messages WHERE NOT processed) AS oldest_unprocessed,
              (SELECT COUNT(*) FROM judge_runs WHERE error IS NOT NULL) AS provider_errors,
              (SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs
                WHERE to_char(created_at AT TIME ZONE 'UTC','YYYY-MM') = %(period)s)
                AS month_spend_usd,
              (SELECT COALESCE(SUM(reserved_usd),0) FROM budget_reservations
                WHERE period = %(period)s AND status='active') AS month_reserved_usd,
              (SELECT EXTRACT(EPOCH FROM (now() - MIN(created_at))) FROM index_outbox
                WHERE status IN ('pending','processing','failed')) AS outbox_oldest_age_seconds,
              (SELECT COALESCE(SUM(attempts),0) FROM index_outbox) AS outbox_retries,
              (SELECT EXTRACT(EPOCH FROM (now() - MAX(verified_at))) FROM backup_artifacts)
                AS backup_freshness_seconds,
              (SELECT COUNT(*) FROM memories
                WHERE review_status='pending' AND status='active'
                  AND scope_id = ANY(%(scopes)s)) AS pending_review""",
        {"period": period, "scopes": principal.scopes()},
    ).fetchone()
    return {
        "outbox_pending": outbox.pending_count(conn),
        "oldest_unprocessed_message": iso(row["oldest_unprocessed"]),
        "provider_errors": int(row["provider_errors"]),
        "month_spend_usd": float(row["month_spend_usd"]),
        "month_reserved_usd": float(row["month_reserved_usd"]),
        "month_limit_usd": get_settings().monthly_cost_limit_usd,
        "pending_review": int(row["pending_review"]),
        **retrieval_metrics,
        "outbox_oldest_age_seconds": round(float(row["outbox_oldest_age_seconds"]), 1)
        if row["outbox_oldest_age_seconds"] is not None
        else None,
        "outbox_retries": int(row["outbox_retries"]),
        "index_parity": {
            "database_active": int(active_memories["n"]) if active_memories else 0,
            "qdrant_active": indexed_memories,
        },
        "backup_freshness_seconds": round(float(row["backup_freshness_seconds"]), 1)
        if row["backup_freshness_seconds"] is not None
        else None,
    }


@app.get("/v1/admin/backups")
def backup_status(principal: Principal = Depends(require_admin)) -> ItemsOut:
    return {"items": operations.list_backups(get_settings())}


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
