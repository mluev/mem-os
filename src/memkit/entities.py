"""Entities, memberships, and the aliases that let a name resolve to one.

An entity is anything a memory can belong to or be about: a person, the team, a
product, a project, a company. Two entity kinds are special and created by the
system rather than by a request:

* `user` -- exactly one per user, and that user's private scope. Deleting it
  would orphan their memory, so it is created with them.
* `team` -- exactly one per instance, holding the rules everyone shares. Every
  user is a member.

Aliases exist because conversation does not use slugs. Someone says "Саша" or
"the shop", and routing a fact to the right scope depends on turning that into
an entity. The normalised form is case-folded, which Cyrillic needs.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from .db import Row, normalise_alias, slugify

SYSTEM_KINDS = frozenset({"user", "team"})
CREATABLE_KINDS = frozenset({"project", "product", "company", "person", "custom"})
MEMBER_ROLES = frozenset({"owner", "member", "viewer"})
WRITER_ROLES = frozenset({"owner", "member"})


def _unique_slug(conn: psycopg.Connection, base: str) -> str:
    """A free slug near `base`, suffixed only when it collides."""
    slug = slugify(base)
    for attempt in range(200):
        candidate = slug if attempt == 0 else f"{slug[:57]}-{attempt + 1}"
        taken = conn.execute("SELECT 1 FROM entities WHERE slug=%s", (candidate,)).fetchone()
        if taken is None:
            return candidate
    raise ValueError(f"cannot find a free slug for {base!r}")


def create(
    conn: psycopg.Connection,
    *,
    kind: str,
    name: str,
    slug: str | None = None,
    description: str = "",
    visibility: str = "members",
    user_id: str | None = None,
    created_by: str | None = None,
    aliases: list[str] | None = None,
) -> Row:
    """Create an entity. `user` and `team` are for the system, not for requests."""
    name = name.strip()
    if not name:
        raise ValueError("entity name is required")
    if kind not in CREATABLE_KINDS | SYSTEM_KINDS:
        raise ValueError(f"unknown entity kind: {kind!r}")
    if visibility not in {"members", "team"}:
        raise ValueError("visibility must be 'members' or 'team'")
    entity_id = str(uuid.uuid4())
    row = conn.execute(
        """INSERT INTO entities (id,kind,name,slug,description,visibility,user_id,created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            entity_id,
            kind,
            name,
            slug or _unique_slug(conn, name),
            description.strip(),
            visibility,
            user_id,
            created_by,
        ),
    ).fetchone()
    if row is None:  # pragma: no cover - RETURNING cannot be empty here
        raise RuntimeError("entity insert returned no row")
    add_aliases(conn, entity_id=entity_id, aliases=[name, *(aliases or [])])
    if created_by is not None and kind in CREATABLE_KINDS:
        set_member(conn, entity_id=entity_id, user_id=created_by, role="owner")
    return row


def add_aliases(conn: psycopg.Connection, *, entity_id: str, aliases: list[str]) -> list[str]:
    """Register alternate names, ignoring any already claimed.

    An alias is globally unique: if two entities answered to "Саша" the
    extractor could not route a fact about either, so the first claim wins and
    the caller can see what was skipped.
    """
    added: list[str] = []
    for alias in aliases:
        norm = normalise_alias(alias)
        if not norm:
            continue
        result = conn.execute(
            """INSERT INTO entity_aliases (entity_id,alias_norm,alias) VALUES (%s,%s,%s)
               ON CONFLICT (alias_norm) DO NOTHING""",
            (entity_id, norm, alias.strip()),
        )
        if result.rowcount:
            added.append(alias.strip())
    return added


def remove_alias(conn: psycopg.Connection, *, entity_id: str, alias: str) -> bool:
    result = conn.execute(
        "DELETE FROM entity_aliases WHERE entity_id=%s AND alias_norm=%s",
        (entity_id, normalise_alias(alias)),
    )
    return bool(result.rowcount)


def aliases_of(conn: psycopg.Connection, entity_id: str) -> list[str]:
    return [
        str(row["alias"])
        for row in conn.execute(
            "SELECT alias FROM entity_aliases WHERE entity_id=%s ORDER BY alias", (entity_id,)
        )
    ]


def resolve_alias(conn: psycopg.Connection, name: str) -> Row | None:
    """The entity that answers to this name, or None.

    Exact normalised match only. A fuzzy match here would route a fact about one
    person into another person's profile, which is worse than not routing it:
    an unresolved name becomes a needs-attention item a human can fix.
    """
    norm = normalise_alias(name)
    if not norm:
        return None
    return conn.execute(
        """SELECT e.* FROM entities e JOIN entity_aliases a ON a.entity_id = e.id
            WHERE a.alias_norm=%s AND e.archived_at IS NULL""",
        (norm,),
    ).fetchone()


def by_slug(conn: psycopg.Connection, slug: str) -> Row | None:
    return conn.execute("SELECT * FROM entities WHERE slug=%s", (slug,)).fetchone()


def by_id(conn: psycopg.Connection, entity_id: str) -> Row | None:
    return conn.execute("SELECT * FROM entities WHERE id=%s", (entity_id,)).fetchone()


def team(conn: psycopg.Connection) -> Row | None:
    return conn.execute("SELECT * FROM entities WHERE kind='team'").fetchone()


def own_entity(conn: psycopg.Connection, user_id: str) -> Row | None:
    return conn.execute("SELECT * FROM entities WHERE user_id=%s", (user_id,)).fetchone()


def set_member(
    conn: psycopg.Connection, *, entity_id: str, user_id: str, role: str = "member"
) -> None:
    if role not in MEMBER_ROLES:
        raise ValueError(f"unknown membership role: {role!r}")
    conn.execute(
        """INSERT INTO memberships (entity_id,user_id,role) VALUES (%s,%s,%s)
           ON CONFLICT (entity_id,user_id) DO UPDATE SET role=EXCLUDED.role""",
        (entity_id, user_id, role),
    )


def remove_member(conn: psycopg.Connection, *, entity_id: str, user_id: str) -> bool:
    result = conn.execute(
        "DELETE FROM memberships WHERE entity_id=%s AND user_id=%s", (entity_id, user_id)
    )
    return bool(result.rowcount)


def members(conn: psycopg.Connection, entity_id: str) -> list[Row]:
    return list(
        conn.execute(
            """SELECT m.user_id, m.role, u.handle, u.display_name
                 FROM memberships m JOIN users u ON u.id = m.user_id
                WHERE m.entity_id=%s ORDER BY u.handle""",
            (entity_id,),
        )
    )


def ensure_team(conn: psycopg.Connection, *, name: str) -> Row:
    """The one team entity, created on first start."""
    existing = team(conn)
    if existing is not None:
        return existing
    return create(conn, kind="team", name=name, slug=slugify(name, fallback="team"))


def ensure_user_entity(conn: psycopg.Connection, *, user_id: str, display_name: str) -> Row:
    """A user's private scope, created with the user.

    Also joins them to the team, because the shared rules are not optional: a
    user who could not read them would get different behaviour from everyone
    else for no stated reason.
    """
    existing = own_entity(conn, user_id)
    if existing is None:
        existing = create(
            conn,
            kind="user",
            name=display_name,
            user_id=user_id,
            created_by=user_id,
        )
        set_member(conn, entity_id=str(existing["id"]), user_id=user_id, role="owner")
    team_row = team(conn)
    if team_row is not None:
        set_member(conn, entity_id=str(team_row["id"]), user_id=user_id, role="member")
    return existing


def visible_to(conn: psycopg.Connection, user_id: str) -> list[Row]:
    """Every entity this user may read.

    Their own, everything they are a member of, and anything marked visible to
    the whole team. Teammates' user entities are *not* included: a private scope
    is private, even though the person is visible as a subject.
    """
    return list(
        conn.execute(
            """SELECT DISTINCT e.* FROM entities e
                 LEFT JOIN memberships m ON m.entity_id = e.id AND m.user_id = %s
                WHERE e.archived_at IS NULL
                  AND (e.user_id = %s OR m.user_id IS NOT NULL OR e.visibility = 'team')
                ORDER BY e.kind, e.name""",
            (user_id, user_id),
        )
    )


def writable_by(conn: psycopg.Connection, user_id: str) -> set[str]:
    """Scopes this user may write to: their own, plus memberships above viewer."""
    rows = conn.execute(
        """SELECT e.id FROM entities e
             LEFT JOIN memberships m ON m.entity_id = e.id AND m.user_id = %s
            WHERE e.archived_at IS NULL
              AND (e.user_id = %s OR m.role = ANY(%s))""",
        (user_id, user_id, sorted(WRITER_ROLES)),
    ).fetchall()
    return {str(row["id"]) for row in rows}


def teammates(conn: psycopg.Connection, user_id: str) -> list[Row]:
    """User entities of everyone else on the team.

    These are the people a fact can be *about*. Their private scopes stay
    invisible; only their identity is shared.
    """
    return list(
        conn.execute(
            """SELECT e.* FROM entities e JOIN users u ON u.id = e.user_id
                WHERE e.kind='user' AND e.user_id <> %s AND u.disabled_at IS NULL
                  AND e.archived_at IS NULL
                ORDER BY e.name""",
            (user_id,),
        )
    )


def for_prompt(conn: psycopg.Connection, *, user_id: str, limit: int = 40) -> list[dict[str, Any]]:
    """The entity block the extractor sees, in a stable order.

    Order matters twice: the numbers are what operations refer to, and the cap
    means the tail is dropped, so the speaker, the team, and their projects must
    come before other people. Every entry carries its aliases, since that is how
    a name in conversation becomes a scope.
    """
    own = own_entity(conn, user_id)
    team_row = team(conn)
    ordered: list[Row] = []
    seen: set[str] = set()

    def push(row: Row | None) -> None:
        if row is None:
            return
        key = str(row["id"])
        if key not in seen:
            seen.add(key)
            ordered.append(row)

    push(own)
    push(team_row)
    for row in visible_to(conn, user_id):
        if row["kind"] not in SYSTEM_KINDS:
            push(row)
    for row in teammates(conn, user_id):
        push(row)

    described: list[dict[str, Any]] = []
    for row in ordered[:limit]:
        entity_id = str(row["id"])
        if own is not None and entity_id == str(own["id"]):
            label = "you, the speaker"
        elif row["kind"] == "user":
            label = "teammate"
        else:
            label = str(row["kind"])
        described.append(
            {
                "id": entity_id,
                "slug": row["slug"],
                "kind": row["kind"],
                "label": label,
                "name": row["name"],
                "aliases": [a for a in aliases_of(conn, entity_id) if a != row["name"]],
            }
        )
    return described
