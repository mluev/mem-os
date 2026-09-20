"""Backups and diagnostics.

Both are now Postgres operations rather than filesystem ones. A SQLite backup
was a copy of one file, so the service could take it, verify it, and swap it
back in by itself; a Postgres backup is `pg_dump` against a server that other
processes are also connected to. Taking one is still safe from inside the
service. Putting one back is not, which is why `restore_backup` documents the
procedure instead of performing it.

Service management, Docker orchestration and first-run setup are gone with the
single-machine deployment they belonged to: the instance runs as a container
with a database and a Qdrant beside it, and its lifecycle belongs to whatever
starts them.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import psycopg

from . import db, entities, judge, outbox, vectors
from .config import DEFAULT_CONFIG_DIR, Settings
from .db import connect, init_db, transaction, utcnow
from .embed import get_embedder

BackupKind = Literal["daily", "weekly", "pre-migration", "pre-promotion", "emergency"]

# Kinds taken before something irreversible. Retention never removes them.
PROTECTED_KINDS = frozenset({"pre-migration", "pre-promotion"})


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)  # noqa: S603


def _tool(name: str) -> str:
    """The path to a Postgres client binary, or a legible failure.

    `pg_dump` must match the server's major version or it refuses to run, so it
    is deliberately not vendored: the operator installs the client that goes
    with their server.
    """
    found = shutil.which(name)
    if found is None:
        raise RuntimeError(f"{name} is not on PATH; install the Postgres client tools")
    return found


def _dsn(settings: Settings) -> str:
    if not settings.database_url.strip():
        raise RuntimeError("MEMKIT_DATABASE_URL is not configured")
    return settings.database_url


def _redacted(dsn: str) -> str:
    """A DSN without its password: doctor output gets pasted into bug reports."""
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


def _open(settings: Settings) -> psycopg.Connection:
    """A connection with the schema guaranteed to exist."""
    dsn = _dsn(settings)
    init_db(dsn)
    return connect(dsn)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    """Checksum the archive and read its table of contents.

    `pg_restore --list` parses every object header in the dump, so a truncated
    or corrupted archive fails here rather than half-way through a restore. It
    is the closest available equivalent to the `PRAGMA quick_check` this
    replaces, which could inspect page structure only because a SQLite backup
    *was* a database.
    """
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    checksum = _sha256(path)
    if expected_sha256 is not None and not secrets.compare_digest(checksum, expected_sha256):
        raise RuntimeError("backup checksum mismatch")
    listing = _run([_tool("pg_restore"), "--list", str(path)])
    entries = [
        line for line in listing.stdout.splitlines() if line.strip() and not line.startswith(";")
    ]
    if not entries:
        raise RuntimeError("backup archive lists no restorable entries")
    return {
        "path": str(path),
        "sha256": checksum,
        "bytes": path.stat().st_size,
        "entries": len(entries),
        "verified_at": utcnow(),
    }


def create_backup(
    settings: Settings,
    *,
    kind: BackupKind | Literal["auto"] = "auto",
    protected: bool = False,
) -> dict[str, Any]:
    """Dump the database to a verified, registered archive.

    Custom format rather than plain SQL: it is the only format `pg_restore` can
    replay selectively, and the only one that can be inspected without a
    database to restore into.
    """
    dsn = _dsn(settings)
    init_db(dsn)
    if kind == "auto":
        kind = "weekly" if datetime.now(UTC).weekday() == 6 else "daily"
    backup_dir = settings.backup_dir.expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"memkit-{kind}-{stamp}-{uuid.uuid4().hex[:8]}.dump"
    temporary = path.with_suffix(".dump.tmp")
    # The DSN is visible in this process's command line while the dump runs, so
    # a shared host wants a .pgpass or a service file rather than a password in
    # MEMKIT_DATABASE_URL.
    _run(
        [
            _tool("pg_dump"),
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            f"--dbname={dsn}",
            f"--file={temporary}",
        ]
    )
    os.chmod(temporary, 0o600)
    result = verify_backup(temporary)
    temporary.replace(path)
    result["path"] = str(path)
    artifact_id = str(uuid.uuid4())
    protected = bool(protected or kind in PROTECTED_KINDS)
    conn = connect(dsn)
    try:
        with transaction(conn):
            conn.execute(
                """INSERT INTO backup_artifacts
                   (id,kind,path,sha256,bytes,verified_at,protected,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    artifact_id,
                    kind,
                    str(path),
                    result["sha256"],
                    result["bytes"],
                    result["verified_at"],
                    protected,
                    utcnow(),
                ),
            )
    finally:
        conn.close()
    result.update({"id": artifact_id, "kind": kind, "protected": protected})
    return result


def list_backups(settings: Settings) -> list[dict[str, Any]]:
    conn = _open(settings)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM backup_artifacts ORDER BY created_at DESC,id DESC"
            ).fetchall()
        ]
    finally:
        conn.close()


def prune_backups(
    settings: Settings, *, keep_daily: int = 7, keep_weekly: int = 4
) -> dict[str, Any]:
    """Keep the newest daily and weekly archives; never touch a protected one."""
    rows = list_backups(settings)
    keep: set[str] = set()
    for kind, count in (("daily", keep_daily), ("weekly", keep_weekly)):
        keep.update(str(row["id"]) for row in [r for r in rows if r["kind"] == kind][:count])
    removed: list[str] = []
    conn = connect(_dsn(settings))
    try:
        with transaction(conn):
            for row in rows:
                if row["protected"] or row["kind"] not in {"daily", "weekly"}:
                    continue
                if str(row["id"]) in keep:
                    continue
                Path(str(row["path"])).unlink(missing_ok=True)
                conn.execute("DELETE FROM backup_artifacts WHERE id=%s", (row["id"],))
                removed.append(str(row["path"]))
    finally:
        conn.close()
    return {"removed": removed, "kept_daily": keep_daily, "kept_weekly": keep_weekly}


def restore_backup(settings: Settings, *, artifact_id: str, confirm: str = "") -> dict[str, Any]:
    """Always raises: restoring is an operator procedure, not an API call.

    `pg_restore --clean` drops and recreates every object the archive contains.
    Nothing else may hold a connection while it does, and this service cannot
    promise that about itself: its pool reconnects on demand, the index worker
    runs on a timer, and any other replica of the app is a writer it does not
    know about. A restore that ran anyway would leave a half-replaced schema
    with no way back. So the archive is verified here -- the part that can be
    done safely -- and the command is handed to whoever can stop the service.

    `confirm` is accepted and ignored: the callers that used to guard the
    destructive version still pass it, and there is nothing left to confirm.
    """
    artifacts = {str(row["id"]): row for row in list_backups(settings)}
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        raise LookupError("unknown backup artifact")
    path = Path(str(artifact["path"]))
    verify_backup(path, expected_sha256=str(artifact["sha256"]))
    raise NotImplementedError(
        "restore is deliberately manual. Stop every memkit process, then run:\n"
        f"  pg_restore --clean --if-exists --no-owner --no-privileges "
        f"--dbname={_redacted(_dsn(settings))} {path}\n"
        "then run `memkit reindex` to rebuild Qdrant from the restored database."
    )


def _check(name: str, fn: Any) -> dict[str, Any]:
    try:
        detail = fn()
        return {"name": name, "ok": True, "detail": detail}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)}


def doctor(settings: Settings, *, load_model: bool = False) -> dict[str, Any]:
    def configuration() -> dict[str, Any]:
        return {
            "host": settings.host,
            "port": settings.port,
            "database": _redacted(_dsn(settings)),
        }

    def client_config() -> dict[str, Any]:
        """Where agents and hooks will find their key.

        Reported here rather than warned about from the hooks: a hook's whole
        contract is to stay silent and fail open, so a per-session stderr notice
        would be noise in the one place that promised none. Diagnostics belong
        in doctor.
        """
        client_path = DEFAULT_CONFIG_DIR / "client.env"
        legacy = Path.home() / ".memkit"
        if client_path.is_file():
            if client_path.stat().st_mode & 0o077:
                raise RuntimeError(f"permissions are not 0600: {client_path}")
            return {"path": str(client_path), "legacy_in_use": legacy.is_file()}
        if legacy.is_file():
            return {
                "path": str(legacy),
                "deprecated": True,
                "hint": f"move MEMKIT_BASE_URL and MEMKIT_API_KEY into {client_path}",
            }
        raise RuntimeError(
            f"no client config: write {client_path} with MEMKIT_BASE_URL and "
            "MEMKIT_API_KEY, or agents and hooks will have no key"
        )

    def database() -> dict[str, Any]:
        dsn = _dsn(settings)
        init_db(dsn)
        conn = connect(dsn)
        try:
            alive = conn.execute("SELECT 1 AS ok").fetchone()
            if alive is None or int(alive["ok"]) != 1:
                raise RuntimeError("the database did not answer SELECT 1")
            # An edited or skipped migration means the running code and the
            # schema disagree, which is a startup failure elsewhere; doctor
            # names it rather than letting the next query be the symptom.
            db._verify_migration_history(conn)
            row = conn.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
            return {
                "schema": int(row["version"]) if row and row["version"] is not None else 0,
                "expected": db.SCHEMA_VERSION,
            }
        finally:
            conn.close()

    def fulltext() -> dict[str, Any]:
        """The Russian text-search configuration the lexical arm depends on.

        `memories.search_tsv` is a generated column over `to_tsvector('russian',
        text)`, which stems Cyrillic and ASCII in the same column. Replaces the
        old fts5 probe, which tested a compile-time SQLite option; this tests
        that the server actually has the configuration the schema references.
        """
        conn = connect(_dsn(settings))
        try:
            row = conn.execute(
                "SELECT to_tsvector('russian',%s) AS lexemes", ("предпочитает pnpm",)
            ).fetchone()
            lexemes = str(row["lexemes"]) if row else ""
            if not lexemes:
                raise RuntimeError("the russian configuration produced no lexemes")
            return {"lexemes": lexemes}
        finally:
            conn.close()

    def qdrant() -> dict[str, int]:
        client = vectors.get_client(settings.qdrant_url)
        vectors.ensure_collections(client)
        return {
            "memories": vectors.count(client, vectors.MEMORIES),
            "raw": vectors.count(client, vectors.RAW),
        }

    def parity() -> dict[str, Any]:
        conn = connect(_dsn(settings))
        client = vectors.get_client(settings.qdrant_url)
        try:
            active = int(
                conn.execute("SELECT count(*) AS n FROM memories WHERE status='active'").fetchone()[
                    "n"
                ]
            )
            indexed = vectors.count(client, vectors.MEMORIES)
            pending = outbox.pending_count(conn)
            if active != indexed or pending:
                raise RuntimeError(f"postgres={active}, qdrant={indexed}, outbox={pending}")
            return {"postgres": active, "qdrant": indexed}
        finally:
            conn.close()

    def embedder() -> dict[str, Any]:
        model = get_embedder()
        if load_model:
            vector = model.encode_one("memkit doctor")
            return {"ready": model.ready, "dimensions": len(vector), "device": model.device}
        return {
            "configured_device": settings.embed_device,
            "backend": settings.embed_backend,
            "dimensions": settings.embed_dim,
            "revision": settings.embed_revision,
        }

    def provider() -> str:
        selected = judge.provider_of(settings.judge_model)
        configured = (
            bool(settings.gemini_api_key or settings.vertex_project)
            if selected == "gemini"
            else bool(settings.anthropic_api_key)
        )
        if not configured:
            raise RuntimeError(f"{selected} credentials are not configured")
        return f"{selected}:{settings.judge_model}"

    def backups() -> dict[str, Any]:
        items = list_backups(settings)
        if not items:
            raise RuntimeError("no verified backup is registered")
        newest = items[0]
        verify_backup(Path(str(newest["path"])), expected_sha256=str(newest["sha256"]))
        return {"count": len(items), "newest": db.iso(newest["created_at"])}

    def worker_state() -> dict[str, int]:
        conn = connect(_dsn(settings))
        try:
            return {
                "queued_jobs": int(
                    conn.execute("SELECT count(*) AS n FROM jobs WHERE status='queued'").fetchone()[
                        "n"
                    ]
                ),
                "outbox_pending": outbox.pending_count(conn),
            }
        finally:
            conn.close()

    def accounts() -> dict[str, Any]:
        """Someone must be able to administer the instance, and the team must exist.

        The team entity is where shared facts live and every user is a member of
        it, so an instance without one has no shared scope at all -- and the
        first user's own scope would be their only one.
        """
        conn = connect(_dsn(settings))
        try:
            admins = int(
                conn.execute(
                    "SELECT count(*) AS n FROM users WHERE role='admin' AND disabled_at IS NULL"
                ).fetchone()["n"]
            )
            if not admins:
                raise RuntimeError("no enabled admin user exists")
            team = entities.team(conn)
            if team is None:
                raise RuntimeError("the team entity does not exist")
            return {"admins": admins, "team": str(team["slug"])}
        finally:
            conn.close()

    checks = [
        _check("configuration", configuration),
        _check("client_config", client_config),
        _check("database", database),
        _check("fulltext", fulltext),
        _check("backups", backups),
        _check("qdrant", qdrant),
        _check("embedder", embedder),
        _check("provider", provider),
        _check("index_parity", parity),
        _check("worker", worker_state),
        _check("users", accounts),
    ]
    return {"ok": all(check["ok"] for check in checks), "checks": checks, "checked_at": utcnow()}
