"""Credentials: passwords, API keys, and dashboard sessions.

Two ways in, deliberately different.

An **API key** is what an agent or hook carries. It is shown once, stored only
as a sha256 of the secret, and identifies exactly one user. Because it is sent
explicitly on every request it needs no CSRF defence.

A **session cookie** is what the dashboard carries. The browser attaches it to
any request to this origin, including one a hostile page provokes, so
cookie-authenticated mutations additionally require a header the browser will
not send cross-origin.

Passwords are hashed with argon2id, which is memory-hard: the point is that a
stolen database does not yield a list of plausible passwords.
"""

from __future__ import annotations

import ipaddress
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from typing import Any

import psycopg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .db import utcnow

# The header a cookie-authenticated mutation must carry. A cross-origin form
# post or image load cannot set it, and CORS is closed, so its presence is
# enough: no token round-trip is needed.
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "memkit"

KEY_PREFIX = "mk"
_PREFIX_BYTES = 6
_SECRET_BYTES = 32

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    return _hasher.hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        _hasher.verify(stored, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False
    return True


def needs_rehash(stored: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored)
    except (InvalidHashError, ValueError):
        return False


@dataclass(frozen=True)
class MintedKey:
    """A new API key. `secret` exists only here and in the caller's response."""

    id: str
    prefix: str
    secret: str

    @property
    def token(self) -> str:
        return f"{KEY_PREFIX}_{self.prefix}_{self.secret}"


def _token_hash(secret: str) -> str:
    return sha256(secret.encode()).hexdigest()


def mint_api_key(conn: psycopg.Connection, *, user_id: str, name: str) -> MintedKey:
    """Create a key and return the one copy of its secret that will ever exist.

    The prefix is stored in the clear so a key can be identified in a list, and
    revoked, without keeping anything that would let it be used.
    """
    prefix = secrets.token_hex(_PREFIX_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    key_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO api_keys (id,user_id,name,key_prefix,key_hash)
           VALUES (%s,%s,%s,%s,%s)""",
        (key_id, user_id, name.strip(), prefix, _token_hash(secret)),
    )
    return MintedKey(id=key_id, prefix=prefix, secret=secret)


def resolve_api_key(conn: psycopg.Connection, token: str) -> str | None:
    """The user this key belongs to, or None.

    Looks the row up by its prefix and then compares the hash in constant time,
    so a wrong secret costs the same as a right one.
    """
    # Split only on the two structural separators: the secret is base64url and
    # contains underscores of its own, so an unbounded split silently rejected
    # about a third of all issued keys.
    parts = (token or "").split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        return None
    _, prefix, secret = parts
    row = conn.execute(
        """SELECT k.id, k.user_id, k.key_hash
             FROM api_keys k JOIN users u ON u.id = k.user_id
            WHERE k.key_prefix = %s AND k.revoked_at IS NULL AND u.disabled_at IS NULL""",
        (prefix,),
    ).fetchone()
    if row is None:
        return None
    if not secrets.compare_digest(str(row["key_hash"]), _token_hash(secret)):
        return None
    conn.execute("UPDATE api_keys SET last_used_at=now() WHERE id=%s", (row["id"],))
    return str(row["user_id"])


def revoke_api_key(conn: psycopg.Connection, *, key_id: str, user_id: str | None = None) -> bool:
    """Revoke a key. With `user_id`, only that user's own key."""
    clause = " AND user_id=%s" if user_id else ""
    args: tuple[Any, ...] = (key_id, user_id) if user_id else (key_id,)
    result = conn.execute(
        f"UPDATE api_keys SET revoked_at=now() WHERE id=%s AND revoked_at IS NULL{clause}",
        args,
    )
    return bool(result.rowcount)


def _as_ip(value: str | None) -> str | None:
    """An address the `inet` column will accept, or nothing.

    Behind a proxy this can arrive as a hostname, and a test client sends a
    literal name. A session record is an audit convenience; refusing to log
    somebody in because their address did not parse would be the wrong trade.
    """
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def start_session(
    conn: psycopg.Connection,
    *,
    user_id: str,
    ttl_days: int,
    ip: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Create a dashboard session and return its bearer token.

    Only the hash is stored, for the same reason as API keys: the session table
    must not be a list of usable credentials.
    """
    token = secrets.token_urlsafe(32)
    conn.execute(
        """INSERT INTO auth_sessions (id,user_id,token_hash,expires_at,ip,user_agent)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (
            str(uuid.uuid4()),
            user_id,
            _token_hash(token),
            utcnow() + timedelta(days=ttl_days),
            _as_ip(ip),
            (user_agent or "")[:500] or None,
        ),
    )
    return token


def resolve_session(conn: psycopg.Connection, token: str, *, ttl_days: int) -> str | None:
    """The user this session belongs to, sliding its expiry forward."""
    if not token:
        return None
    row = conn.execute(
        """SELECT s.id, s.user_id FROM auth_sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.expires_at > now()
              AND u.disabled_at IS NULL""",
        (_token_hash(token),),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE auth_sessions SET last_seen_at=now(), expires_at=%s WHERE id=%s",
        (utcnow() + timedelta(days=ttl_days), row["id"]),
    )
    return str(row["user_id"])


def revoke_session(conn: psycopg.Connection, token: str) -> None:
    conn.execute(
        "UPDATE auth_sessions SET revoked_at=now() WHERE token_hash=%s AND revoked_at IS NULL",
        (_token_hash(token),),
    )


def revoke_all_sessions(conn: psycopg.Connection, *, user_id: str, keep: str | None = None) -> None:
    """Sign a user out everywhere. Used after a password change."""
    # The cast is required, not cosmetic: an untyped NULL parameter in a
    # comparison leaves Postgres unable to infer the type and the whole
    # statement fails, which made every password change a 500.
    kept = _token_hash(keep) if keep else None
    conn.execute(
        """UPDATE auth_sessions SET revoked_at=now()
            WHERE user_id=%s AND revoked_at IS NULL
              AND (%s::text IS NULL OR token_hash <> %s::text)""",
        (user_id, kept, kept),
    )


class RateLimiter:
    """Fixed-window attempt counter, in process.

    Deliberately not in the database: a login flood should not become a write
    workload. Single-replica, which is what this deployment is; a second replica
    would need a shared counter and that is a real change, not a config switch.
    """

    def __init__(self, *, limit: int = 5, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, *keys: str) -> bool:
        """True when every key is under its limit. Does not record."""
        now = time.monotonic()
        with self._lock:
            for key in keys:
                hits = self._hits.get(key)
                if hits is None:
                    continue
                while hits and now - hits[0] > self.window:
                    hits.popleft()
                if len(hits) >= self.limit:
                    return False
        return True

    def record(self, *keys: str) -> None:
        """Count one failed attempt against every key."""
        now = time.monotonic()
        with self._lock:
            for key in keys:
                self._hits.setdefault(key, deque()).append(now)

    def reset(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._hits.pop(key, None)
