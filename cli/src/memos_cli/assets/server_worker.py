"""Executed over SSH on the server, never imported or executed by the client."""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

# OPERATIONS and forwarded_args are prepended from server_operations.py by the client.
if __name__ != "__main__":
    from memos_cli.server_operations import OPERATIONS, forwarded_args


class DiagnosticFailure(RuntimeError):
    def __init__(self, report):
        self.report = report
        super().__init__("Server diagnostics failed: " + json.dumps(report))


def run(argv, *, input=None, timeout=900, diagnostic_secrets=None):
    result = subprocess.run(argv, input=input, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        if diagnostic_secrets is not None:
            try:
                report = json.loads(result.stdout)
            except ValueError:
                report = None
            if isinstance(report, dict) and isinstance(report.get("checks"), list):
                # Retain check outcomes, never arbitrary subprocess output or DSNs.
                checks = [
                    {
                        "name": check.get("name"),
                        "ok": check.get("ok"),
                        "detail": check.get("detail", {}),
                    }
                    for check in report["checks"]
                    if isinstance(check, dict)
                ]
                text = json.dumps({"ok": False, "checks": checks}, default=str)
                for secret in diagnostic_secrets:
                    if secret:
                        text = text.replace(secret, "[REDACTED]")
                text = re.sub(r"(\w+://)[^\s\"/]*@", r"\1[REDACTED]@", text)
                text = re.sub(
                    r"(?i)(password|secret|token|api[_-]?key)([\"\s:=]+)[^\s,}\"]+",
                    r"\1\2[REDACTED]",
                    text,
                )
                raise DiagnosticFailure(json.loads(text))
        raise RuntimeError(
            f"Remote {Path(argv[0]).name} operation failed (exit {result.returncode}); inspect server logs."
        )
    return result.stdout


def write(path, content):
    fd, temporary = tempfile.mkstemp(dir=Path(path).parent, prefix=".memos-")
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def image_check(image):
    if not image or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]+", image):
        raise RuntimeError("Supply a versioned container image or sha256 digest.")
    tail = image.rsplit("/", 1)[-1]
    if ":" not in tail or tail.endswith(":latest"):
        raise RuntimeError("Pin an image version or digest; latest is not accepted.")


def compose_config(image, port, secure):
    return {
        "services": {
            "app": {
                "image": image,
                "restart": "unless-stopped",
                "user": f"{os.getuid() or 10001}:{os.getgid() or 10001}",
                "depends_on": {
                    "postgres": {"condition": "service_healthy"},
                    "qdrant": {"condition": "service_started"},
                },
                "environment": {
                    "MEMKIT_DATABASE_URL": "postgresql://memkit:${POSTGRES_PASSWORD}@postgres:5432/memkit",
                    "MEMKIT_QDRANT_URL": "http://qdrant:6333",
                    "MEMKIT_HOST": "0.0.0.0",
                    "MEMKIT_ALLOW_REMOTE": "true",
                    "MEMKIT_COOKIE_SECURE": "true" if secure else "false",
                    "MEMKIT_TELEMETRY_HMAC_KEY": "${MEMKIT_TELEMETRY_HMAC_KEY}",
                    "MEMKIT_EMBED_DEVICE": "cpu",
                    "MEMKIT_BACKUP_DIR": "/backups",
                    "MEMKIT_EXPORT_DIR": "/exports",
                    "GEMINI_API_KEY": "${GEMINI_API_KEY:-}",
                    "HF_HOME": "/models",
                },
                "ports": [f"127.0.0.1:{port}:8077"],
                "volumes": [
                    # Keep the ownership established below even while empty;
                    # Docker's copy-up would restore the image's UID (10001).
                    "models:/models:nocopy",
                    "./backups:/backups",
                    "./exports:/exports",
                    "./imports:/imports:ro",
                ],
            },
            "postgres": {
                "image": "postgres:16",
                "restart": "unless-stopped",
                "environment": {
                    "POSTGRES_USER": "memkit",
                    "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD}",
                    "POSTGRES_DB": "memkit",
                },
                "volumes": ["pgdata:/var/lib/postgresql/data"],
                "healthcheck": {
                    "test": ["CMD-SHELL", "pg_isready -U memkit -d memkit"],
                    "interval": "5s",
                    "timeout": "5s",
                    "retries": 30,
                },
            },
            "qdrant": {
                "image": "qdrant/qdrant:v1.18.2",
                "restart": "unless-stopped",
                "volumes": ["qdrant:/qdrant/storage"],
            },
        },
        "volumes": {name: {} for name in ("pgdata", "qdrant", "models")},
    }


BOOTSTRAP = """import json,sys
from memkit import auth,users,entities
from memkit.config import get_settings
from memkit.db import connect,init_db,transaction
p=json.load(sys.stdin); s=get_settings(); init_db(s.database_url); c=connect(s.database_url)
with transaction(c):
 entities.ensure_team(c,name=s.team_name)
 if users.listing(c):
  print(json.dumps({"existing":True}))
 else:
  u=users.create(c,handle=p["handle"],display_name=p["handle"],password=p["password"],role="admin")
  k=auth.mint_api_key(c,user_id=str(u["id"]),name="memos-initial-device")
  print(json.dumps({"key":k.token,"key_id":k.id}))
c.close()
"""


RESTORE = """import os,subprocess,sys
subprocess.run([
 'pg_restore','--dbname',os.environ['MEMKIT_DATABASE_URL'],
 '--clean','--if-exists','--no-owner','--no-privileges',
 '--single-transaction','--exit-on-error',sys.argv[1],
],check=True)
"""


def perform(payload):
    action = payload["action"]
    directory = Path(payload["directory"]).expanduser()
    if not directory.is_absolute():
        directory = Path.home() / directory
    directory = directory.resolve()
    marker = directory / ".memos-managed.json"
    if action == "install":
        if (
            directory.exists()
            and any(p.name != ".memos-lock" for p in directory.iterdir())
            and not marker.exists()
        ):
            raise RuntimeError(
                "Directory is not managed by memos; refusing to take over an existing deployment."
            )
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    elif not marker.is_file():
        raise RuntimeError(
            "This is not a CLI-managed deployment. Use its existing deployment operator."
        )
    with (directory / ".memos-lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return locked(payload, directory, marker)


def locked(p, directory, marker):
    action = p["action"]
    project = "memos-" + hashlib.sha256(str(directory).encode()).hexdigest()[:12]
    compose = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--project-directory",
        str(directory),
        "--env-file",
        str(directory / "server.env"),
        "-f",
        str(directory / "compose.json"),
    ]
    metadata = json.loads(marker.read_text()) if marker.exists() else {}

    def dc(*args, input=None, timeout=900):
        return run([*compose, *args], input=input, timeout=timeout)

    def op(*args):
        return json.loads(dc("exec", "-T", "app", "memkit", *args))

    def backup_op(*args):
        # Recovery must remain usable while the normal app is stopped.
        return json.loads(dc("run", "--rm", "--no-deps", "app", "memkit", "backup", *args))

    catalog_path = directory / "backup-catalog.json"
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {}

    def create_backup(*args):
        artifact = backup_op("create", *args)
        catalog[artifact["id"]] = artifact
        write(catalog_path, json.dumps(catalog))
        return artifact

    def list_backups():
        try:
            for artifact in backup_op("list"):
                catalog[artifact["id"]] = artifact
            write(catalog_path, json.dumps(catalog))
        except RuntimeError:
            if not catalog:
                raise
        return list(catalog.values())

    def ready():
        dc(
            "exec",
            "-T",
            "app",
            "python",
            "-c",
            "import json,urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8077/readyz',timeout=10); assert r.status==200",
        )

    if action in OPERATIONS:
        forwarded = forwarded_args(p)

    if action in {"install", "upgrade"}:
        image_check(p["image"])
        repeated_install = action == "install" and metadata and not metadata.get("provisioning")
        if action == "install" and metadata:
            if p.get("remote_port") is not None and p["remote_port"] != metadata["port"]:
                raise RuntimeError("--remote-port conflicts with the installed deployment")
            configuration = (
                json.loads((directory / "compose.json").read_text())
                if (directory / "compose.json").exists()
                else None
            )
            if configuration is not None and "https" in p:
                secure = (
                    configuration["services"]["app"]["environment"]["MEMKIT_COOKIE_SECURE"]
                    == "true"
                )
                if secure != bool(p["https"]):
                    raise RuntimeError("URL mode conflicts with the installed deployment")
        if repeated_install and metadata["image"] != p["image"]:
            raise RuntimeError("Already installed with another image; use memos server upgrade.")
        if action == "upgrade" and metadata["image"] == p["image"]:
            raise RuntimeError(
                "Upgrade needs a new versioned image reference; current version is unchanged."
            )
        run(["docker", "compose", "version"])
        if repeated_install:
            pass  # Re-running setup must not replace the image behind an existing tag.
        elif p.get("source"):
            source = Path(p["source"]).expanduser().resolve()
            if not (source / "Dockerfile").is_file():
                raise RuntimeError("--source must be a remote checkout containing Dockerfile")
            run(["docker", "build", "-t", p["image"], str(source)], timeout=1800)
        else:
            run(["docker", "pull", p["image"]], timeout=1800)
        if action == "install" and not (directory / "compose.json").exists():
            metadata = {
                "image": p["image"],
                "port": p.get("remote_port", 8077),
                "project": project,
                "version": 1,
                "provisioning": True,
            }
            write(marker, json.dumps(metadata))
            provider = p.get("provider_key", "")
            if any(c in provider for c in "\n\r\x00"):
                raise RuntimeError("Invalid provider key")
            write(
                directory / "server.env",
                "POSTGRES_PASSWORD="
                + secrets.token_hex(32)
                + "\nMEMKIT_TELEMETRY_HMAC_KEY="
                + secrets.token_hex(32)
                + "\nGEMINI_API_KEY="
                + provider
                + "\n",
            )
            config = compose_config(p["image"], p.get("remote_port", 8077), bool(p.get("https")))
            write(directory / "compose.json", json.dumps(config, indent=2))
            for name in ("backups", "exports", "imports"):
                folder = directory / name
                folder.mkdir(mode=0o700, exist_ok=True)
        elif action == "install" and metadata["image"] != p["image"]:
            raise RuntimeError("Already installed with another image; use memos server upgrade.")
        if action == "install" and metadata.get("provisioning"):
            # Retry initialization after an interrupted install without rotating
            # credentials. Repair the empty-cache mount of older provisioners.
            config = json.loads((directory / "compose.json").read_text())
            volumes = config["services"]["app"]["volumes"]
            if "models:/models" in volumes:
                volumes[volumes.index("models:/models")] = "models:/models:nocopy"
                write(directory / "compose.json", json.dumps(config, indent=2))
            # Ownership adjustment happens on the remote Docker host only.
            dc(
                "run",
                "--rm",
                "--no-deps",
                "--user",
                "0",
                "app",
                "chown",
                "-R",
                f"{os.getuid() or 10001}:{os.getgid() or 10001}",
                "/backups",
                "/exports",
                "/models",
            )
        if action == "upgrade":
            old_image = metadata["image"]
            schema_command = [
                "python",
                "-c",
                "from memkit.db import SCHEMA_VERSION; print(SCHEMA_VERSION)",
            ]
            old_schema = run(["docker", "run", "--rm", old_image, *schema_command])
            new_schema = run(["docker", "run", "--rm", p["image"], *schema_command])
            if old_schema != new_schema:
                raise RuntimeError(
                    "Schema-changing upgrade requires a migration procedure; current deployment unchanged."
                )
            backup = create_backup("--protected")
            configuration = json.loads((directory / "compose.json").read_text())
            configuration["services"]["app"]["image"] = p["image"]
            write(directory / "compose.json", json.dumps(configuration, indent=2))
            try:
                dc("up", "-d", "--wait", "--wait-timeout", "600")
                ready()
            except Exception:
                configuration["services"]["app"]["image"] = old_image
                write(directory / "compose.json", json.dumps(configuration, indent=2))
                dc("up", "-d", "--wait", "--wait-timeout", "600")
                raise RuntimeError(
                    "Upgrade failed; previous image restored. Check server status."
                ) from None
            metadata.update(previous_image=old_image, image=p["image"], upgrade_backup=backup["id"])
            write(marker, json.dumps(metadata))
            return {"image": p["image"], "previous_image": old_image, "backup_id": backup["id"]}
        dc("up", "-d", "--wait", "--wait-timeout", "600")
        ready()
        identity = json.loads(
            dc(
                "exec",
                "-T",
                "app",
                "python",
                "-c",
                BOOTSTRAP,
                input=json.dumps({"handle": p["handle"], "password": p["password"]}),
            )
        )
        metadata.pop("provisioning", None)
        write(marker, json.dumps(metadata))
        return {
            "installed": True,
            "image": metadata["image"],
            "port": metadata["port"],
            "automatic_extraction": any(
                line.startswith("GEMINI_API_KEY=") and line.partition("=")[2]
                for line in (directory / "server.env").read_text().splitlines()
            ),
            **identity,
        }
    if action in {"start", "restart"}:
        if action == "restart":
            dc("restart", "app")
        dc("up", "-d", "--wait", "--wait-timeout", "600")
        ready()
        return {"ready": True}
    if action == "stop":
        dc("stop")
        return {"stopped": True, "data_preserved": True}
    if action == "status":
        return {"deployment": metadata, "containers": dc("ps", "--format", "json")}
    if action == "logs":
        text = dc("logs", "--no-color", "--tail", str(p.get("limit", 100)))
        # Remove known secrets before returning operator logs to the client.
        for line in (directory / "server.env").read_text().splitlines():
            secret = line.partition("=")[2]
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return {"logs": text}
    if action == "doctor":
        secrets_to_hide = [
            line.partition("=")[2] for line in (directory / "server.env").read_text().splitlines()
        ]
        return json.loads(
            run(
                [*compose, "exec", "-T", "app", "memkit", *forwarded],
                diagnostic_secrets=secrets_to_hide,
            )
        )
    if action in {"reindex", "bench", "drain-index", "consolidate", "reextract-report", "eval"}:
        return op(*forwarded)
    if action in {"import-claude-code", "import-sqlite"}:
        path = Path(p["path"]).expanduser().resolve()
        if not path.is_relative_to((directory / "imports").resolve()):
            raise RuntimeError(
                "Place import data under the deployment's imports directory; pass its remote path."
            )
        container_path = "/imports/" + str(path.relative_to(directory / "imports"))
        args = [
            action,
            *(["--root", container_path] if action == "import-claude-code" else [container_path]),
        ]
        if action == "import-claude-code" and not p.get("apply"):
            args += ["--dry-run"]
        args += forwarded[1:]
        return {"report": dc("exec", "-T", "app", "memkit", *args)}
    if action == "backup-create":
        return create_backup(*forwarded[1:])
    if action == "backup-list":
        return list_backups()
    if action == "backup-prune":
        result = backup_op("prune")
        removed = set(result.get("removed", []))
        catalog = {key: value for key, value in catalog.items() if value.get("path") not in removed}
        write(catalog_path, json.dumps(catalog))
        return result
    if action in {"backup-verify", "backup-download", "backup-restore"}:
        artifact = next((a for a in list_backups() if a["id"] == p["artifact_id"]), None)
        if not artifact:
            raise RuntimeError("Unknown backup artifact")
        container_path = Path(artifact["path"])
        if container_path.parent != Path("/backups"):
            raise RuntimeError("Backup is outside the managed backup directory")
        path = directory / "backups" / container_path.name
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != artifact["sha256"]:
            raise RuntimeError("Backup checksum mismatch")
        backup_op("verify", artifact["path"])
        if action == "backup-restore":
            if p.get("confirm") != "RESTORE":
                raise RuntimeError("Restore requires explicit confirmation")
            dc("stop", "app")
            # Refuse if another connection can write into this database.
            active = dc(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                "memkit",
                "-d",
                "memkit",
                "-Atc",
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'",
            )
            if int(active.strip()):
                raise RuntimeError(
                    "Other database clients remain; app left stopped. Disconnect them before restoring."
                )
            recovery = create_backup("--protected")
            stage = "database restore"
            try:
                dc("run", "--rm", "--no-deps", "app", "python", "-c", RESTORE, artifact["path"])
                stage = "index rebuild"
                dc("run", "--rm", "--no-deps", "app", "memkit", "reindex")
                stage = "service startup"
                dc("up", "-d", "--wait", "--wait-timeout", "600")
                ready()
            except Exception:
                with contextlib.suppress(RuntimeError):
                    dc("stop", "app")
                raise RuntimeError(
                    f"Restore failed during {stage}; app stop requested. Inspect server status before restarting. Recovery backup: {recovery['id']}"
                ) from None
            return {"restored": artifact["id"], "recovery_backup": recovery["id"]}
        return {"verified": True, "path": str(path), "sha256": artifact["sha256"]}
    raise RuntimeError("Unknown server operation")


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "data": perform(json.load(sys.stdin))}, default=str))
    except Exception as exc:
        # Never echo subprocess output, environment, credentials, or request JSON.
        message = (
            str(exc)
            if isinstance(exc, RuntimeError)
            else f"Remote {type(exc).__name__}; check server prerequisites and logs."
        )
        result = {"ok": False, "error": message}
        if isinstance(exc, DiagnosticFailure):
            result["details"] = exc.report
        print(json.dumps(result))
