"""User records, and the entity every user needs to have memory at all."""

from __future__ import annotations

import uuid

import psycopg

from . import auth, entities
from .db import Row


def create(
    conn: psycopg.Connection,
    *,
    handle: str,
    display_name: str,
    password: str,
    role: str = "member",
    email: str | None = None,
) -> Row:
    """Create a user together with their private scope and team membership.

    One function, because a user without an entity has nowhere to put a memory
    and would fail on their first write. There is no state where one exists
    without the other.
    """
    handle = handle.strip().casefold()
    if role not in {"admin", "member"}:
        raise ValueError("role must be 'admin' or 'member'")
    row = conn.execute(
        """INSERT INTO users (id,handle,display_name,email,password_hash,role)
           VALUES (%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            str(uuid.uuid4()),
            handle,
            display_name.strip(),
            (email or "").strip().casefold() or None,
            auth.hash_password(password),
            role,
        ),
    ).fetchone()
    if row is None:  # pragma: no cover - RETURNING cannot be empty here
        raise RuntimeError("user insert returned no row")
    entities.ensure_user_entity(conn, user_id=str(row["id"]), display_name=str(row["display_name"]))
    return row


def by_handle(conn: psycopg.Connection, handle: str) -> Row | None:
    return conn.execute(
        "SELECT * FROM users WHERE handle=%s", (handle.strip().casefold(),)
    ).fetchone()


def by_id(conn: psycopg.Connection, user_id: str) -> Row | None:
    return conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()


def listing(conn: psycopg.Connection) -> list[Row]:
    return list(
        conn.execute(
            """SELECT u.id,u.handle,u.display_name,u.email,u.role,u.created_at,u.disabled_at,
                      e.id AS own_entity_id,
                      (SELECT max(last_used_at) FROM api_keys k WHERE k.user_id=u.id)
                        AS key_last_used_at
                 FROM users u LEFT JOIN entities e ON e.user_id = u.id
                ORDER BY u.handle"""
        )
    )


def set_password(conn: psycopg.Connection, *, user_id: str, password: str) -> None:
    conn.execute(
        "UPDATE users SET password_hash=%s WHERE id=%s",
        (auth.hash_password(password), user_id),
    )


def update(
    conn: psycopg.Connection,
    *,
    user_id: str,
    display_name: str | None = None,
    role: str | None = None,
    disabled: bool | None = None,
) -> Row | None:
    """Patch the fields an admin may change.

    Disabling rather than deleting: a user's memories cite their messages and
    carry them as author, so removing the row would take evidence with it.
    """
    if role is not None and role not in {"admin", "member"}:
        raise ValueError("role must be 'admin' or 'member'")
    # Every nullable parameter is cast. An untyped NULL in a comparison or a
    # CASE leaves Postgres unable to infer the type and the statement fails, so
    # patching anything *except* `disabled` used to raise -- promoting a member
    # to administrator among them.
    row = conn.execute(
        """UPDATE users SET
              display_name = COALESCE(%s::text, display_name),
              role = COALESCE(%s::text, role),
              disabled_at = CASE
                  WHEN %s::boolean IS NULL THEN disabled_at
                  WHEN %s::boolean THEN COALESCE(disabled_at, now())
                  ELSE NULL END
            WHERE id=%s RETURNING *""",
        (
            display_name.strip() if display_name else None,
            role,
            disabled,
            disabled,
            user_id,
        ),
    ).fetchone()
    if row is not None and disabled:
        conn.execute(
            "UPDATE auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL",
            (user_id,),
        )
    return row


def count_admins(conn: psycopg.Connection, *, excluding: str | None = None) -> int:
    """Enabled admins, so the last one cannot lock everyone out."""
    # The casts are required: an untyped NULL parameter in a comparison leaves
    # Postgres unable to infer the type and the statement fails outright, which
    # turned the last-administrator guard into a 500.
    row = conn.execute(
        """SELECT count(*) AS n FROM users
            WHERE role='admin' AND disabled_at IS NULL
              AND (%s::uuid IS NULL OR id <> %s::uuid)""",
        (excluding, excluding),
    ).fetchone()
    return int(row["n"]) if row else 0
