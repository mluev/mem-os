"""HTTP surface. Agents never touch SQLite or Qdrant directly, only this.

Stage 1 implements the write path, a pure-cosine read path and reindex. The
score formula, scope filtering and the judge arrive in later stages; endpoints
are shaped now so those additions do not change the contract.

Kept in one module deliberately: it is small, and splitting 200 lines across
four route files costs more than it explains. It splits when stage 2 adds the
judge endpoints.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyHeader
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from . import admin, extract, judge, retrieval, store, taskboard, vectors
from .config import Settings, get_settings
from .db import connect, init_db, transaction, utcnow
from .embed import get_embedder

logger = logging.getLogger(__name__)

MEMORY_TYPES = Literal[
    "preference", "fact", "skill", "relation", "project", "decision", "task"
]
SCOPES = Literal["user", "project", "task"]


class MessageIn(BaseModel):
    session_id: str
    owner_id: str | None = None
    agent_id: str = "chat"
    role: Literal["user", "assistant"]
    content: str
    external_source: str | None = None
    external_id: str | None = None


class MessageOut(BaseModel):
    message_id: int
    extraction_queued: bool = False
    deduplicated: bool = False


class SearchIn(BaseModel):
    query: str
    owner_id: str | None = None
    agent_id: str | None = None
    # scope_key is present from stage 1 even though filtering lands in stage 3:
    # docs/05-retrieval.md requires dropping facts from a non-matching project,
    # which is impossible with the request body as docs/03-api.md defines it.
    scopes: list[SCOPES] | None = None
    scope_key: str | None = None
    # Current task, for the task-scope match. Separate from scope_key because a
    # request is usually inside a project *and* a task at once.
    task_key: str | None = None
    types: list[MEMORY_TYPES] | None = None
    project: str | None = None
    budget_tokens: int = Field(default=800, ge=0, le=20000)
    limit: int = Field(default=30, ge=1, le=200)
    # Raw turns are the stage-1 baseline, kept queryable so the eval can compare
    # extracted facts against the messages they came from.
    include_raw: bool = False


class MemoryIn(BaseModel):
    text: str
    type: MEMORY_TYPES
    owner_id: str | None = None
    scope: SCOPES = "user"
    scope_key: str | None = None
    agent_id: str | None = None
    importance: float = Field(default=0.6, ge=0.0, le=1.0)
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    init_db(s.db_path)
    app.state.conn = connect(s.db_path)
    app.state.qdrant = vectors.get_client(s.qdrant_url)
    vectors.ensure_collections(app.state.qdrant)
    app.state.embedder = get_embedder()
    app.state.reindex_lock = threading.Lock()
    app.state.reindex_job = {"status": "idle"}
    app.state.index_dirty = False
    # Load the model before accepting traffic. Costs ~11s at startup and saves a
    # ~15s first request: docs/07-hermes-adapter.md gives prefetch a 150ms
    # timeout, so a lazily-loaded model means the first turn after every restart
    # silently has no memory at all.
    app.state.embedder.load()
    yield
    app.state.conn.close()


_startup_settings = get_settings()
app = FastAPI(
    title="memkit",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _startup_settings.expose_docs else None,
    redoc_url="/redoc" if _startup_settings.expose_docs else None,
)
if _startup_settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_startup_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def judge_configured(s: Settings) -> bool:
    """Whether the configured judge model has credentials available."""
    if judge.provider_of(s.judge_model) == "gemini":
        return bool(s.gemini_api_key or s.vertex_project)
    return bool(s.anthropic_api_key)


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_key(
    x_api_key: Annotated[str | None, Depends(_api_key_header)] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")


app.include_router(admin.router, dependencies=[Depends(require_key)])
app.include_router(taskboard.router, dependencies=[Depends(require_key)])


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    s = get_settings()
    try:
        qdrant_ok = bool(app.state.qdrant.get_collections())
    except Exception:
        qdrant_ok = False
    emb = app.state.embedder
    return {
        "ok": qdrant_ok,
        "qdrant": qdrant_ok,
        "embedder": emb.ready,
        "embedder_device": emb.device,
        "memories": vectors.count(app.state.qdrant, vectors.MEMORIES),
        "raw": vectors.count(app.state.qdrant, vectors.RAW),
        "db": str(s.db_path),
        "index_dirty": bool(getattr(app.state, "index_dirty", False)),
        "reindex": getattr(app.state, "reindex_job", {"status": "idle"}),
    }


def _extract_now(session_id: str, owner_id: str, agent_id: str, force: bool) -> None:
    """Background extraction. Never raises into the request path."""
    s = get_settings()
    conn = app.state.conn
    try:
        with transaction(conn):
            outcome = extract.run_extraction(
                conn, app.state.qdrant, app.state.embedder,
                session_id=session_id, owner_id=owner_id, agent_id=agent_id,
                api_key=s.anthropic_api_key,
                gemini_api_key=s.gemini_api_key,
                project=s.vertex_project, location=s.vertex_location,
                monthly_limit_usd=s.monthly_cost_limit_usd,
                force=force, model=s.judge_model,
            )
        if outcome.applied or outcome.error:
            logger.info("extraction %s: %s", session_id, outcome.as_dict())
    except Exception:  # noqa: BLE001 - a failed extraction must not lose the message
        logger.exception("extraction failed for session %s", session_id)


@app.post("/v1/messages", dependencies=[Depends(require_key)], status_code=201)
def post_message(body: MessageIn, background: BackgroundTasks) -> MessageOut:
    s = get_settings()
    conn = app.state.conn
    owner = body.owner_id or s.owner_id
    with transaction(conn):
        message_id, dedup = store.add_message(
            conn,
            session_id=body.session_id,
            owner_id=owner,
            agent_id=body.agent_id,
            role=body.role,
            content=body.content,
            external_source=body.external_source,
            external_id=body.external_id,
        )
    if dedup:
        return MessageOut(message_id=message_id, deduplicated=True)

    store.index_raw(conn, app.state.qdrant, app.state.embedder, [message_id])

    # The gate is the main cost lever, and grouping is also what makes the
    # extraction good: a ten-message window resolves pronouns a single line
    # cannot. An explicit "remember this" bypasses the counter.
    pending = extract.messages_since_last(conn, body.session_id)
    queued = judge_configured(s) and judge.should_extract(
        messages_since_last=pending, session_closed=False, text=body.content
    )
    if queued:
        background.add_task(_extract_now, body.session_id, owner, body.agent_id, True)
    return MessageOut(message_id=message_id, extraction_queued=queued)


@app.post("/v1/sessions/{session_id}/close", dependencies=[Depends(require_key)])
def close_session(session_id: str, owner_id: str | None = None) -> dict[str, Any]:
    """Close a session and force extraction from whatever is left in the tail."""
    s = get_settings()
    conn = app.state.conn
    row = conn.execute(
        "SELECT agent_id FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown session")

    with transaction(conn):
        conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (utcnow(), session_id),
        )

    if not judge_configured(s):
        return {"extracted": 0, "cost_usd": 0.0,
                "error": "no judge configured: set GEMINI_API_KEY (gemini) "
                         "or ANTHROPIC_API_KEY (claude)"}

    total = extract.ExtractionOutcome()
    # Drain the tail: a long session can hold several windows' worth.
    while True:
        with transaction(conn):
            outcome = extract.run_extraction(
                conn, app.state.qdrant, app.state.embedder,
                session_id=session_id, owner_id=owner_id or s.owner_id,
                agent_id=row["agent_id"], api_key=s.anthropic_api_key,
                gemini_api_key=s.gemini_api_key,
                project=s.vertex_project, location=s.vertex_location,
                monthly_limit_usd=s.monthly_cost_limit_usd, force=True,
                model=s.judge_model,
            )
        total.added += outcome.added
        total.updated += outcome.updated
        total.deleted += outcome.deleted
        total.skipped += outcome.skipped
        total.fast_forwarded += outcome.fast_forwarded
        total.cost_usd += outcome.cost_usd
        if outcome.error:
            total.error = outcome.error
            break
        if outcome.judge_run_id is None and outcome.fast_forwarded == 0:
            break  # drained
    return {"extracted": total.applied, **total.as_dict()}


@app.get("/v1/memories/{memory_id}/sources", dependencies=[Depends(require_key)])
def memory_sources(memory_id: str) -> dict[str, Any]:
    """Where a fact came from.

    This endpoint looks optional and is not: the first time the service
    remembers something absurd about you, the only useful question is which
    messages produced it and which judge run agreed.
    """
    conn = app.state.conn
    mem = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if mem is None:
        raise HTTPException(status_code=404, detail="unknown memory")
    messages = conn.execute(
        """SELECT m.id, m.session_id, m.role, m.content, m.created_at
             FROM memory_sources ms JOIN messages m ON m.id = ms.message_id
            WHERE ms.memory_id = ? ORDER BY m.id""",
        (memory_id,),
    ).fetchall()
    run = None
    if mem["judge_run_id"] is not None:
        r = conn.execute(
            """SELECT id, model, prompt_version, error, input_tokens,
                      output_tokens, cost_usd, latency_ms, created_at, output_json
                 FROM judge_runs WHERE id = ?""",
            (mem["judge_run_id"],),
        ).fetchone()
        run = dict(r) if r else None
    operations = admin._ops(run.get("output_json") if run else None)
    for operation in operations:
        operation["matches_this_memory"] = (
            operation.get("id") == memory_id
            or operation.get("text") == mem["text"]
        )
    supersedes = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM memories WHERE superseded_by=? ORDER BY updated_at DESC",
            (memory_id,),
        ).fetchall()
    ]
    successor = None
    if mem["superseded_by"]:
        row = conn.execute(
            "SELECT * FROM memories WHERE id=?", (mem["superseded_by"],)
        ).fetchone()
        successor = dict(row) if row else None
    return {
        "memory": dict(mem),
        "task_board": (
            dict(board)
            if (
                board := conn.execute(
                    "SELECT * FROM task_board WHERE memory_id = ?", (memory_id,)
                ).fetchone()
            )
            else None
        ),
        "messages": [dict(m) for m in messages],
        "judge_run": run,
        "judge_ops": operations,
        "superseded_by": successor,
        "supersedes": supersedes,
    }


@app.post("/v1/search", dependencies=[Depends(require_key)])
def post_search(body: SearchIn) -> dict[str, Any]:
    s = get_settings()
    t0 = time.perf_counter()
    owner = body.owner_id or s.owner_id

    # Full read path: overfetch 50, rescore, drop foreign-project facts, dedup,
    # then fill the budget. No LLM is involved — reading must stay fast and free.
    scored, used = retrieval.search(
        app.state.qdrant,
        app.state.embedder,
        query=body.query,
        owner_id=owner,
        project=body.scope_key or body.project,
        task=body.task_key,
        types=list(body.types) if body.types else None,
        limit=body.limit,
        budget_tokens=body.budget_tokens,
    )
    out = [s.as_dict() for s in scored]

    if out:
        store.record_retrieval(app.state.conn, [m["id"] for m in out])

    raw: list[dict[str, Any]] = []
    if body.include_raw:
        raw = store.search_raw(
            app.state.qdrant, app.state.embedder,
            query=body.query, owner_id=owner, limit=body.limit,
            project=body.project,
        )

    return {
        "memories": out,
        "raw": raw,
        "used_tokens": used,
        "took_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


@app.post("/v1/memories", dependencies=[Depends(require_key)], status_code=201)
def post_memory(body: MemoryIn) -> dict[str, str]:
    if getattr(app.state, "reindex_job", {}).get("status") == "running":
        raise HTTPException(409, "memory mutations are disabled while reindex runs")
    s = get_settings()
    conn = app.state.conn
    with transaction(conn):
        mem_id = store.add_memory(
            conn,
            app.state.qdrant,
            app.state.embedder,
            owner_id=body.owner_id or s.owner_id,
            text=body.text,
            type=body.type,
            scope=body.scope,
            scope_key=body.scope_key,
            agent_id=body.agent_id,
            importance=body.importance,
            confidence=body.confidence,
        )
    return {"id": mem_id}


@app.get("/v1/memories", dependencies=[Depends(require_key)])
def list_memories(
    owner_id: str | None = None,
    type: str | None = None,
    status: str = "active",
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    scope: str | None = None,
    scope_key: str | None = None,
    agent_id: str | None = None,
    sort: str = "updated_at",
    order: Literal["asc", "desc"] = "desc",
    never_retrieved: bool | None = None,
    min_importance: float | None = Query(None, ge=0, le=1),
    max_importance: float | None = Query(None, ge=0, le=1),
    expired_validity: bool | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> dict[str, Any]:
    s = get_settings()
    return admin.list_memories_data(
        app.state.conn,
        owner_id=owner_id or s.owner_id,
        type=type,
        status=status,
        limit=limit,
        offset=offset,
        q=q,
        scope=scope,
        scope_key=scope_key,
        agent_id=agent_id,
        sort=sort,
        order=order,
        never_retrieved=never_retrieved,
        min_importance=min_importance,
        max_importance=max_importance,
        expired_validity=expired_validity,
        created_after=created_after,
        created_before=created_before,
    )


@app.post("/v1/admin/reindex", dependencies=[Depends(require_key)])
def admin_reindex() -> dict[str, Any]:
    t0 = time.perf_counter()
    counts = store.reindex(app.state.conn, app.state.qdrant, app.state.embedder)
    return {**counts, "took_ms": round((time.perf_counter() - t0) * 1000)}


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
