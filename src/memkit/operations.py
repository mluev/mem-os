"""Backups, diagnostics, setup, and macOS service management."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from . import judge, outbox, reindex, vectors
from .config import DEFAULT_CONFIG_DIR, DEFAULT_DATA_DIR, Settings
from .db import connect, ensure_owner, init_db, transaction, utcnow
from .embed import get_embedder

BackupKind = Literal["daily", "weekly", "pre-migration", "pre-promotion", "emergency"]
SERVICE_LABEL = "ai.memkit.service"
BACKUP_SERVICE_LABEL = "ai.memkit.backup"
QDRANT_CONTAINER = "memkit-qdrant"


def _authenticated_http_check(base_url: str, api_key: str) -> int:
    request = urllib.request.Request(  # noqa: S310 -- doctor restricts this to the local service
        f"{base_url.rstrip('/')}/v1/jobs?limit=1",
        headers={"X-API-Key": api_key},
    )
    with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310
        return int(response.status)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    checksum = _sha256(path)
    if expected_sha256 is not None and not secrets.compare_digest(checksum, expected_sha256):
        raise RuntimeError("backup checksum mismatch")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        quick = [row[0] for row in conn.execute("PRAGMA quick_check").fetchall()]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        if quick != ["ok"] or foreign_keys:
            raise RuntimeError(
                f"backup integrity failed (quick_check={quick[:3]}, foreign_keys={len(foreign_keys)})"
            )
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()
    return {
        "path": str(path),
        "sha256": checksum,
        "size_bytes": path.stat().st_size,
        "schema_version": version,
        "verified_at": utcnow(),
    }


def create_backup(
    settings: Settings,
    *,
    kind: BackupKind | Literal["auto"] = "auto",
    protected: bool = False,
) -> dict[str, Any]:
    init_db(settings.db_path)
    if kind == "auto":
        kind = "weekly" if datetime.now(UTC).weekday() == 6 else "daily"
    backup_dir = settings.backup_dir.expanduser().resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = backup_dir / f"memkit-{kind}-{stamp}-{uuid.uuid4().hex[:8]}.db"
    temporary = path.with_suffix(".db.tmp")
    source = connect(settings.db_path)
    target = sqlite3.connect(temporary)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    os.chmod(temporary, 0o600)
    result = verify_backup(temporary)
    temporary.replace(path)
    result["path"] = str(path)
    artifact_id = str(uuid.uuid4())
    conn = connect(settings.db_path)
    try:
        with transaction(conn):
            conn.execute(
                """INSERT INTO backup_artifacts
                   (id,kind,path,sha256,size_bytes,verified_at,protected,created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    artifact_id,
                    kind,
                    str(path),
                    result["sha256"],
                    result["size_bytes"],
                    result["verified_at"],
                    int(protected or kind in {"pre-migration", "pre-promotion"}),
                    utcnow(),
                ),
            )
    finally:
        conn.close()
    result.update({"id": artifact_id, "kind": kind, "protected": protected})
    return result


def list_backups(settings: Settings) -> list[dict[str, Any]]:
    init_db(settings.db_path)
    conn = connect(settings.db_path)
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
    rows = list_backups(settings)
    keep: set[str] = set()
    for kind, count in (("daily", keep_daily), ("weekly", keep_weekly)):
        keep.update(str(row["id"]) for row in [r for r in rows if r["kind"] == kind][:count])
    removed: list[str] = []
    conn = connect(settings.db_path)
    try:
        with transaction(conn):
            for row in rows:
                if row["protected"] or row["kind"] not in {"daily", "weekly"}:
                    continue
                if row["id"] in keep:
                    continue
                Path(row["path"]).unlink(missing_ok=True)
                conn.execute("DELETE FROM backup_artifacts WHERE id=?", (row["id"],))
                removed.append(str(row["path"]))
    finally:
        conn.close()
    return {"removed": removed, "kept_daily": keep_daily, "kept_weekly": keep_weekly}


def restore_backup(settings: Settings, *, artifact_id: str, confirm: str) -> dict[str, Any]:
    if confirm != "RESTORE":
        raise ValueError('restore requires confirm="RESTORE"')
    artifacts = {str(row["id"]): row for row in list_backups(settings)}
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        raise LookupError("unknown backup artifact")
    selected = Path(str(artifact["path"]))
    verify_backup(selected, expected_sha256=str(artifact["sha256"]))
    emergency = create_backup(settings, kind="emergency", protected=True)
    staged = settings.db_path.with_suffix(
        f"{settings.db_path.suffix}.restore-{uuid.uuid4().hex}.tmp"
    )
    shutil.copy2(selected, staged)
    os.chmod(staged, 0o600)
    verify_backup(staged, expected_sha256=str(artifact["sha256"]))
    old_sidecars = [
        settings.db_path.with_name(settings.db_path.name + suffix) for suffix in ("-wal", "-shm")
    ]
    try:
        staged.replace(settings.db_path)
        for sidecar in old_sidecars:
            sidecar.unlink(missing_ok=True)
        init_db(settings.db_path)
        conn = connect(settings.db_path)
        try:
            ensure_owner(conn, settings.owner_id, settings.owner_name)
            client = vectors.get_client(settings.qdrant_url)
            vectors.ensure_collections(client)
            generation = reindex.rebuild(conn, client, get_embedder())
            with transaction(conn):
                conn.execute(
                    """INSERT OR IGNORE INTO backup_artifacts
                       (id,kind,path,sha256,size_bytes,verified_at,protected,created_at)
                       VALUES (?,'emergency',?,?,?,?,1,?)""",
                    (
                        emergency["id"],
                        emergency["path"],
                        emergency["sha256"],
                        emergency["size_bytes"],
                        emergency["verified_at"],
                        utcnow(),
                    ),
                )
        finally:
            conn.close()
    except Exception:
        rollback = Path(str(emergency["path"]))
        shutil.copy2(rollback, staged)
        staged.replace(settings.db_path)
        for sidecar in old_sidecars:
            sidecar.unlink(missing_ok=True)
        raise
    return {"restored": artifact_id, "emergency": emergency, "index": generation}


def _check(name: str, fn: Any) -> dict[str, Any]:
    try:
        detail = fn()
        return {"name": name, "ok": True, "detail": detail}
    except Exception as exc:
        return {"name": name, "ok": False, "detail": str(exc)}


def doctor(settings: Settings, *, load_model: bool = False) -> dict[str, Any]:
    def configuration() -> dict[str, Any]:
        if settings.api_key == "change-me" or len(settings.api_key) < 32:
            raise RuntimeError("secure API key is not configured")
        return {"host": settings.host, "port": settings.port, "database": str(settings.db_path)}

    def permissions() -> str:
        paths = [p for p in (settings.api_key_file,) if p is not None]
        for path in paths:
            if os.stat(path).st_mode & 0o077:
                raise RuntimeError(f"permissions are not 0600: {path}")
        return "restricted"

    def sqlite_health() -> dict[str, Any]:
        init_db(settings.db_path)
        conn = connect(settings.db_path)
        try:
            quick = conn.execute("PRAGMA quick_check").fetchone()[0]
            foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
            if quick != "ok" or foreign_keys:
                raise RuntimeError(f"quick_check={quick}, foreign_keys={foreign_keys}")
            return {"schema": conn.execute("PRAGMA user_version").fetchone()[0]}
        finally:
            conn.close()

    def fts5() -> int:
        conn = connect(settings.db_path)
        try:
            conn.execute("CREATE VIRTUAL TABLE temp.doctor_fts USING fts5(value)")
            return int(conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0])
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
        conn = connect(settings.db_path)
        client = vectors.get_client(settings.qdrant_url)
        try:
            sqlite_count = int(
                conn.execute("SELECT COUNT(*) FROM memories WHERE status='active'").fetchone()[0]
            )
            qdrant_count = vectors.count(client, vectors.MEMORIES)
            if sqlite_count != qdrant_count or outbox.pending_count(conn):
                raise RuntimeError(
                    f"sqlite={sqlite_count}, qdrant={qdrant_count}, outbox={outbox.pending_count(conn)}"
                )
            return {"sqlite": sqlite_count, "qdrant": qdrant_count}
        finally:
            conn.close()

    def embedder() -> dict[str, Any]:
        model = get_embedder()
        if load_model:
            vector = model.encode_one("memkit doctor")
            return {"ready": model.ready, "dimensions": len(vector), "device": model.device}
        return {"configured_device": settings.embed_device, "revision": settings.embed_revision}

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
        verify_backup(Path(newest["path"]), expected_sha256=newest["sha256"])
        return {"count": len(items), "newest": newest["created_at"]}

    def worker_state() -> dict[str, int]:
        conn = connect(settings.db_path)
        try:
            return {
                "queued_jobs": int(
                    conn.execute("SELECT COUNT(*) FROM jobs WHERE status='queued'").fetchone()[0]
                ),
                "outbox_pending": outbox.pending_count(conn),
            }
        finally:
            conn.close()

    def hermes() -> dict[str, Any]:
        home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
        path = home / "plugins" / "memkit"
        if not path.is_dir():
            raise RuntimeError("Hermes provider is not installed")
        config_path = home / "config.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig")) or {}
        if (config.get("memory") or {}).get("provider") != "memkit":
            raise RuntimeError("Hermes is not using the memkit provider")
        plugin = (config.get("plugins") or {}).get("memkit") or {}
        key_path = Path(str(plugin.get("api_key_file") or "")).expanduser()
        if not key_path.is_file() or key_path.stat().st_mode & 0o077:
            raise RuntimeError("Hermes API key file is missing or not 0600")
        hermes_key = key_path.read_text(encoding="utf-8").strip()
        if not secrets.compare_digest(hermes_key, settings.api_key):
            raise RuntimeError("Hermes API key does not match the service")
        expected_url = f"http://{settings.host}:{settings.port}"
        base_url = str(plugin.get("base_url") or expected_url).rstrip("/")
        if base_url != expected_url:
            raise RuntimeError("Hermes base URL does not match the local service")
        if _authenticated_http_check(base_url, hermes_key) != 200:
            raise RuntimeError("Hermes authenticated service check failed")
        return {"path": str(path), "authenticated": True}

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
                "hint": f"run `memkit setup` to write {client_path}",
            }
        raise RuntimeError(
            f"no client config: run `memkit setup` to write {client_path}, "
            "or agents and hooks will have no key"
        )

    checks = [
        _check("configuration", configuration),
        _check("client_config", client_config),
        _check("permissions", permissions),
        _check("database", sqlite_health),
        _check("fts5", fts5),
        _check("backups", backups),
        _check("qdrant", qdrant),
        _check("embedder", embedder),
        _check("provider", provider),
        _check("index_parity", parity),
        _check("worker", worker_state),
        _check("hermes", hermes),
    ]
    return {"ok": all(check["ok"] for check in checks), "checks": checks, "checked_at": utcnow()}


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)  # noqa: S603


def ensure_qdrant(settings: Settings, *, wait_seconds: int = 120) -> dict[str, Any]:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker is required")
    if _run([docker, "info"], check=False).returncode != 0 and sys.platform == "darwin":
        _run(["open", "-a", "Docker"])
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if _run([docker, "info"], check=False).returncode == 0:
                break
            time.sleep(2)
    if _run([docker, "info"], check=False).returncode != 0:
        raise RuntimeError("Docker daemon is unavailable")
    inspected = _run([docker, "inspect", QDRANT_CONTAINER], check=False)
    image = f"qdrant/qdrant:v{settings.qdrant_version}"
    if inspected.returncode == 0:
        info = json.loads(inspected.stdout)[0]
        if info["Config"]["Image"] != image:
            raise RuntimeError(
                f"{QDRANT_CONTAINER} uses {info['Config']['Image']}; expected pinned {image}"
            )
        _run([docker, "start", QDRANT_CONTAINER], check=False)
    else:
        storage = DEFAULT_DATA_DIR / "qdrant"
        storage.mkdir(parents=True, exist_ok=True)
        _run(
            [
                docker,
                "run",
                "-d",
                "--name",
                QDRANT_CONTAINER,
                "--restart",
                "unless-stopped",
                "-p",
                "127.0.0.1:6333:6333",
                "-p",
                "127.0.0.1:6334:6334",
                "-v",
                f"{storage}:/qdrant/storage",
                image,
            ]
        )
    deadline = time.monotonic() + wait_seconds
    client = vectors.get_client(settings.qdrant_url)
    while time.monotonic() < deadline:
        try:
            vectors.ensure_collections(client)
            return {"container": QDRANT_CONTAINER, "image": image, "ready": True}
        except Exception:
            time.sleep(2)
    raise RuntimeError("Qdrant did not become ready")


def service_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_LABEL}.plist"


def backup_service_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{BACKUP_SERVICE_LABEL}.plist"


def _program_arguments(*arguments: str) -> list[str]:
    executable = shutil.which("memkit")
    return (
        [executable, *arguments] if executable else [sys.executable, "-m", "memkit.cli", *arguments]
    )


def install_service(settings: Settings) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("automatic service installation is supported on macOS only")
    plist_path = service_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    arguments = _program_arguments("serve")
    logs = DEFAULT_DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": SERVICE_LABEL,
        "ProgramArguments": arguments,
        "WorkingDirectory": str(Path.cwd()),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 60,
        "ProcessType": "Interactive",
        "StandardOutPath": str(logs / "service.log"),
        "StandardErrorPath": str(logs / "service.error.log"),
    }
    temporary = plist_path.with_suffix(".plist.tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    os.chmod(temporary, 0o600)
    temporary.replace(plist_path)
    return plist_path


def install_backup_service() -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("automatic backup scheduling is supported on macOS only")
    path = backup_service_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    logs = DEFAULT_DATA_DIR / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": BACKUP_SERVICE_LABEL,
        "ProgramArguments": _program_arguments("backup", "create"),
        "StartCalendarInterval": {"Hour": 3, "Minute": 0},
        "ProcessType": "Background",
        "StandardOutPath": str(logs / "backup.log"),
        "StandardErrorPath": str(logs / "backup.error.log"),
    }
    temporary = path.with_suffix(".plist.tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return path


def service_action(action: str, settings: Settings) -> dict[str, Any]:
    if sys.platform != "darwin":
        raise RuntimeError("Linux uses documented manual startup in this release")
    launchctl = "/bin/launchctl"
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{SERVICE_LABEL}"
    path = service_plist_path()
    if action == "install":
        install_service(settings)
        backup_path = install_backup_service()
        _run([launchctl, "bootout", target], check=False)
        result = _run([launchctl, "bootstrap", domain, str(path)], check=False)
        backup_target = f"{domain}/{BACKUP_SERVICE_LABEL}"
        _run([launchctl, "bootout", backup_target], check=False)
        backup_result = _run([launchctl, "bootstrap", domain, str(backup_path)], check=False)
        if backup_result.returncode != 0 and result.returncode == 0:
            result = backup_result
    elif action == "start":
        result = _run([launchctl, "kickstart", "-k", target], check=False)
    elif action == "stop":
        result = _run([launchctl, "bootout", target], check=False)
    elif action == "restart":
        _run([launchctl, "bootout", target], check=False)
        # launchd can report EIO when bootstrap races the asynchronous unload.
        for _ in range(50):
            if _run([launchctl, "print", target], check=False).returncode != 0:
                break
            time.sleep(0.1)
        result = _run([launchctl, "bootstrap", domain, str(path)], check=False)
    elif action == "status":
        result = _run([launchctl, "print", target], check=False)
    elif action == "uninstall":
        _run([launchctl, "bootout", target], check=False)
        _run([launchctl, "bootout", f"{domain}/{BACKUP_SERVICE_LABEL}"], check=False)
        path.unlink(missing_ok=True)
        backup_service_plist_path().unlink(missing_ok=True)
        return {"action": action, "ok": True, "path": str(path)}
    else:
        raise ValueError(f"unknown service action: {action}")
    return {
        "action": action,
        "ok": result.returncode == 0,
        "output": (result.stdout or result.stderr).strip(),
        "path": str(path),
    }


def setup(settings: Settings, *, install_hermes: Any) -> dict[str, Any]:
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(DEFAULT_CONFIG_DIR, 0o700)
    os.chmod(DEFAULT_DATA_DIR, 0o700)
    key_path = DEFAULT_CONFIG_DIR / "api-key"
    if not key_path.exists():
        key_path.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
    os.chmod(key_path, 0o600)
    config_path = DEFAULT_CONFIG_DIR / "config.env"
    if not config_path.exists():
        configured_secrets = []
        if settings.gemini_api_key:
            configured_secrets.append(f"GEMINI_API_KEY={json.dumps(settings.gemini_api_key)}")
        if settings.anthropic_api_key:
            configured_secrets.append(f"ANTHROPIC_API_KEY={json.dumps(settings.anthropic_api_key)}")
        config_path.write_text(
            "\n".join(
                [
                    f"MEMKIT_API_KEY_FILE={json.dumps(str(key_path))}",
                    f"MEMKIT_DB_PATH={json.dumps(str(DEFAULT_DATA_DIR / 'memkit.db'))}",
                    f"MEMKIT_BACKUP_DIR={json.dumps(str(DEFAULT_DATA_DIR / 'backups'))}",
                    f"MEMKIT_EXPORT_DIR={json.dumps(str(DEFAULT_DATA_DIR / 'exports'))}",
                    "MEMKIT_QDRANT_URL=http://127.0.0.1:6333",
                    f"MEMKIT_JUDGE_MODEL={json.dumps(settings.judge_model)}",
                    *configured_secrets,
                    "",
                ]
            ),
            encoding="utf-8",
        )
    os.chmod(config_path, 0o600)
    # The service reads config.env; agents and hooks read client.env. They are
    # separate files because the first holds provider secrets and a path to the
    # key, while the second holds the key value itself and is what a client
    # needs. Onboarding used to stop after config.env and tell people to
    # hand-copy a key into ~/.memkit, which nothing created, so every hook
    # failed open and stayed silent.
    client_path = DEFAULT_CONFIG_DIR / "client.env"
    if not client_path.exists():
        client_path.write_text(
            "\n".join(
                [
                    f"MEMKIT_BASE_URL=http://{settings.host}:{settings.port}",
                    f"MEMKIT_API_KEY={key_path.read_text(encoding='utf-8').strip()}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    os.chmod(client_path, 0o600)
    production = Settings(_env_file=config_path)
    qdrant = ensure_qdrant(production)
    init_db(production.db_path)
    conn = connect(production.db_path)
    try:
        with transaction(conn):
            ensure_owner(conn, production.owner_id, production.owner_name)
    finally:
        conn.close()
    hermes_path = install_hermes(force=True, settings=production)
    get_embedder().encode_one("memkit warmup")
    first_backup = create_backup(production, kind="daily")
    service = service_action("install", production)
    report = doctor(production, load_model=False)
    return {
        "config": str(config_path),
        "key_file": str(key_path),
        "qdrant": qdrant,
        "hermes": str(hermes_path),
        "backup": first_backup,
        "service": service,
        "doctor": report,
    }
