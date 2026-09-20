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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (
    auth,
    entities,
    job_runner,
    maintenance,
    outbox,
    telemetry,
    vectors,
    worker,
)
from .config import Settings, get_settings
from .db import ConnectionPool, init_db
from .embed import get_embedder
from .http import SESSION_COOKIE as SESSION_COOKIE
from .http import get_conn as get_conn
from .http import get_principal as get_principal
from .http import judge_configured as judge_configured
from .http import require_admin as require_admin
from .principal import ScopeForbidden, UnknownScope
from .routers import mount_domain_routers
from .schemas import (
    AdminHealthOut as AdminHealthOut,
)
from .schemas import (
    AliasIn as AliasIn,
)
from .schemas import (
    ApiKeyIn as ApiKeyIn,
)
from .schemas import (
    AttentionResolveIn as AttentionResolveIn,
)
from .schemas import (
    BatchOut as BatchOut,
)
from .schemas import (
    ConsolidateIn as ConsolidateIn,
)
from .schemas import (
    CursorPageOut as CursorPageOut,
)
from .schemas import (
    EntityIn as EntityIn,
)
from .schemas import (
    EntityOut as EntityOut,
)
from .schemas import (
    EntityPatch as EntityPatch,
)
from .schemas import (
    EraseIn as EraseIn,
)
from .schemas import (
    EvidenceBatchIn as EvidenceBatchIn,
)
from .schemas import (
    FeedbackIn as FeedbackIn,
)
from .schemas import (
    FeedbackOut as FeedbackOut,
)
from .schemas import (
    FlexibleOut as FlexibleOut,
)
from .schemas import (
    HealthOut as HealthOut,
)
from .schemas import (
    ItemsOut as ItemsOut,
)
from .schemas import (
    JobOut as JobOut,
)
from .schemas import (
    JobQueuedOut as JobQueuedOut,
)
from .schemas import (
    JudgeRunOut as JudgeRunOut,
)
from .schemas import (
    KeyCreatedOut as KeyCreatedOut,
)
from .schemas import (
    LoginIn as LoginIn,
)
from .schemas import (
    MemberIn as MemberIn,
)
from .schemas import (
    MemoryCreatedOut as MemoryCreatedOut,
)
from .schemas import (
    MemoryHistoryOut as MemoryHistoryOut,
)
from .schemas import (
    MemoryIn as MemoryIn,
)
from .schemas import (
    MemoryOut as MemoryOut,
)
from .schemas import (
    MemoryPatch as MemoryPatch,
)
from .schemas import (
    MemorySearchOut as MemorySearchOut,
)
from .schemas import (
    MemorySourcesOut as MemorySourcesOut,
)
from .schemas import (
    MessageIn as MessageIn,
)
from .schemas import (
    MessageOut as MessageOut,
)
from .schemas import (
    MetricsOut as MetricsOut,
)
from .schemas import (
    OffsetPageOut as OffsetPageOut,
)
from .schemas import (
    PasswordChangeIn as PasswordChangeIn,
)
from .schemas import (
    PolicyIn as PolicyIn,
)
from .schemas import (
    ProfileIn as ProfileIn,
)
from .schemas import (
    ProfileOut as ProfileOut,
)
from .schemas import (
    ReadyOut as ReadyOut,
)
from .schemas import (
    ReplayIn as ReplayIn,
)
from .schemas import (
    ResolveIn as ResolveIn,
)
from .schemas import (
    RetrievalRunFeedbackIn as RetrievalRunFeedbackIn,
)
from .schemas import (
    ReviewIn as ReviewIn,
)
from .schemas import (
    SearchIn as SearchIn,
)
from .schemas import (
    SessionMessagesOut as SessionMessagesOut,
)
from .schemas import (
    SessionOut as SessionOut,
)
from .schemas import (
    StrictModel as StrictModel,
)
from .schemas import (
    UserIn as UserIn,
)
from .schemas import (
    UserPatch as UserPatch,
)

logger = logging.getLogger(__name__)


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
    if not settings.jev_api_key and any(
        mode != "off"
        for mode in (
            settings.semantic_dedup,
            settings.semantic_retrieval,
            settings.semantic_support,
            settings.semantic_context,
        )
    ):
        raise RuntimeError("enabled semantic blocks require JEV or TYPESAFE_API_KEY")


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
    from .semantic_runtime import from_settings

    app.state.semantic = from_settings(settings)
    app.state.reranker = app.state.semantic
    _start_durable_worker(app)
    yield
    app.state.worker.stop()
    if app.state.semantic is not None:
        app.state.semantic.client.close()
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


@app.exception_handler(maintenance.MaintenanceBusy)
async def maintenance_unavailable(request: Request, exc: maintenance.MaintenanceBusy):
    return JSONResponse(status_code=503, content={"detail": str(exc)}, headers={"Retry-After": "5"})


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


def _dispatch_job(job_id: str, kind: str) -> None:
    job_runner.run(app, job_id)


# Internal compatibility entrypoints used by operator integrations and tests.
def _run_extraction(job_id: str) -> None:
    job_runner.run(app, job_id)


def _run_export(job_id: str) -> None:
    job_runner.run(app, job_id)


def _run_erase(job_id: str) -> None:
    job_runner.run(app, job_id)


def _run_reindex(job_id: str) -> None:
    job_runner.run(app, job_id)


def _run_consolidation(job_id: str) -> None:
    job_runner.run(app, job_id)


def _run_reextract_report(job_id: str) -> None:
    job_runner.run(app, job_id)


_queue_extraction = job_runner.queue_extraction


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
