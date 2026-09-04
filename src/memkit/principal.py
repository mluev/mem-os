"""Who is asking, and what they may reach.

Every request resolves to exactly one `Principal`, and every query that touches
memory takes its scope set from that object rather than from configuration. The
service this replaces read the owner from settings in some forty handlers, which
meant a request could not name anyone: fine for one person, unusable for a team.

The rule for a scope the principal does not belong to is **403, not silence**.
Filtering it away looks safer and is worse: the caller cannot tell an empty
result from a forbidden one, and neither can a test.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import psycopg

from . import entities


class ScopeForbidden(Exception):
    """A scope outside the principal's set was named explicitly."""

    def __init__(self, scope: str) -> None:
        super().__init__(f"scope is not accessible: {scope}")
        self.scope = scope


class UnknownScope(Exception):
    """No entity has that slug or id."""

    def __init__(self, scope: str) -> None:
        super().__init__(f"unknown scope: {scope}")
        self.scope = scope


@dataclass(frozen=True)
class Principal:
    user_id: str
    handle: str
    display_name: str
    role: str
    auth_kind: str
    own_entity_id: str
    team_entity_id: str | None
    allowed_scope_ids: frozenset[str] = field(default_factory=frozenset)
    writable_scope_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def may_read(self, scope_id: str) -> bool:
        return scope_id in self.allowed_scope_ids

    def may_write(self, scope_id: str) -> bool:
        return scope_id in self.writable_scope_ids

    def require_read(self, scope_id: str) -> str:
        if not self.may_read(scope_id):
            raise ScopeForbidden(scope_id)
        return scope_id

    def require_write(self, scope_id: str) -> str:
        if not self.may_write(scope_id):
            raise ScopeForbidden(scope_id)
        return scope_id

    def scopes(self) -> list[str]:
        """The read set as a sorted list, for SQL and Qdrant filters."""
        return sorted(self.allowed_scope_ids)


def load(conn: psycopg.Connection, user_id: str, *, auth_kind: str = "api_key") -> Principal:
    """Build the principal for a user in one pass over entities and memberships."""
    user = conn.execute(
        "SELECT * FROM users WHERE id=%s AND disabled_at IS NULL", (user_id,)
    ).fetchone()
    if user is None:
        raise LookupError(f"unknown or disabled user: {user_id}")
    own = entities.ensure_user_entity(conn, user_id=user_id, display_name=str(user["display_name"]))
    team = entities.team(conn)
    visible = entities.visible_to(conn, user_id)
    writable = entities.writable_by(conn, user_id)
    return Principal(
        user_id=str(user["id"]),
        handle=str(user["handle"]),
        display_name=str(user["display_name"]),
        role=str(user["role"]),
        auth_kind=auth_kind,
        own_entity_id=str(own["id"]),
        team_entity_id=str(team["id"]) if team else None,
        allowed_scope_ids=frozenset(str(row["id"]) for row in visible),
        writable_scope_ids=frozenset(writable),
    )


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def resolve_scope(
    conn: psycopg.Connection,
    principal: Principal,
    scope: str | None,
    *,
    write: bool = False,
) -> str:
    """Turn a caller-supplied scope into an id it is allowed to use.

    Accepts a slug, an entity id, or the words `private` and `team`, because a
    hook config and a dashboard select should not have to agree on a format.
    A missing scope means the principal's own private space -- the safe default,
    since a fact that should have been shared can be moved, while one that
    should not have been cannot be unshared.
    """
    if not scope or scope == "private":
        return principal.own_entity_id
    if scope == "team":
        if principal.team_entity_id is None:
            raise UnknownScope("team")
        scope_id = principal.team_entity_id
    else:
        row = (
            entities.by_id(conn, scope)
            if _looks_like_uuid(scope)
            else entities.by_slug(conn, scope)
        )
        if row is None:
            raise UnknownScope(scope)
        scope_id = str(row["id"])
    return principal.require_write(scope_id) if write else principal.require_read(scope_id)


def resolve_subject(
    conn: psycopg.Connection, principal: Principal, subject: str | None
) -> str | None:
    """Turn a caller-supplied subject into an entity id.

    A subject is attribution, not permission, so any entity the principal can
    see may be named -- including a teammate, whose private scope stays closed.
    """
    if not subject:
        return None
    row = (
        entities.by_id(conn, subject)
        if _looks_like_uuid(subject)
        else entities.by_slug(conn, subject)
    )
    if row is None:
        raise UnknownScope(subject)
    subject_id = str(row["id"])
    if row["kind"] == "user" or subject_id in principal.allowed_scope_ids:
        return subject_id
    raise ScopeForbidden(subject)


def describe(principal: Principal, scopes: list[dict[str, Any]]) -> dict[str, Any]:
    """The `/v1/auth/me` payload."""
    return {
        "id": principal.user_id,
        "handle": principal.handle,
        "display_name": principal.display_name,
        "role": principal.role,
        "auth_kind": principal.auth_kind,
        "own_entity_id": principal.own_entity_id,
        "team_entity_id": principal.team_entity_id,
        "scopes": scopes,
    }
