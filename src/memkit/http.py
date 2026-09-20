"""Shared HTTP authentication, resource ownership and response helpers."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Annotated, Any

import psycopg
from fastapi import Cookie, Depends, Header, HTTPException, Request
from fastapi.security import APIKeyHeader

from . import (
    auth,
    maintenance,
    outbox,
)
from . import (
    principal as principal_module,
)
from .config import Settings, get_settings
from .db import iso
from .principal import Principal

SESSION_COOKIE = "memkit_session"
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
logger = logging.getLogger(__name__)


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.db.borrow() as conn:
        yield conn


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


def _drain(
    request: Request,
) -> None:
    if not getattr(request.app.state, "index_ready", False):
        return
    try:
        with request.app.state.db.borrow() as conn:
            outbox.drain(conn, request.app.state.qdrant, request.app.state.embedder, limit=100)
    except maintenance.MaintenanceBusy:
        return  # The worker retries after the stable generation is activated.
    except Exception:
        request.app.state.index_ready = False
        logger.warning("inline index drain failed; worker will retry")


def _wake_worker(
    request: Request,
) -> None:
    running = getattr(request.app.state, "worker", None)
    if running is not None:
        running.wake()


def _memory_summary(row: Any) -> dict[str, Any]:
    """The shape every list and panel reports a memory in.

    It carries the slugs as well as the names because a name is not a link: a
    predecessor revision or an entity panel has to be able to navigate to the
    scope or subject it mentions.
    """
    data = dict(row)
    return {
        "id": str(data["id"]),
        "text": data["text"],
        "kind": data["kind"],
        "importance": float(data["importance"]),
        "confidence": float(data["confidence"]),
        "review_status": data["review_status"],
        "source_role": data["source_role"],
        "status": data.get("status"),
        "scope": data.get("scope_name"),
        "scope_slug": data.get("scope_slug"),
        "subject": data.get("subject_name"),
        "subject_slug": data.get("subject_slug"),
        "tags": list(data.get("tags") or []),
        "created_at": iso(data.get("created_at")),
        "updated_at": iso(data["updated_at"]),
        "revision": int(data["revision"]),
    }
