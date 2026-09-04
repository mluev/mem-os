"""One Postgres for the suite, one clean database per test.

The suite needs a real Postgres because half of what it proves is SQL: scope
predicates, full-text stemming, `FOR UPDATE SKIP LOCKED` claims, advisory
locks. None of those have a meaningful in-memory stand-in.

Isolation is `TRUNCATE`, not a rolled-back transaction, because several tests
run worker or heartbeat threads that open their own pooled connections. Those
threads cannot see an uncommitted outer transaction, so rollback-per-test would
make them behave differently from production. Truncating every table takes
about ten milliseconds on an empty schema.

Point `MEMKIT_TEST_DATABASE_URL` at a server, or let the session fixture start
a throwaway cluster from a local PostgreSQL installation.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Import-time guard. `memkit.config` reads `.env`, and `api.py` builds its
# settings singleton on import, so a forgotten patch downstream must not be
# able to reach a real database or a paid provider.
os.environ.setdefault("MEMKIT_DATABASE_URL", "postgresql://memkit@127.0.0.1:5433/memkit-test")
os.environ["MEMKIT_TELEMETRY_HMAC_KEY"] = "test-hmac-key-that-is-long-enough-32ch"
os.environ["MEMKIT_COOKIE_SECURE"] = "false"
for _credential in (
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_VERTEX_API_KEY",
    "VERTEX_PROJECT",
    "GOOGLE_CLOUD_PROJECT",
    "VERTEX_LOCATION",
):
    os.environ[_credential] = ""

_PG_BIN_CANDIDATES = (
    "/opt/homebrew/opt/postgresql@16/bin",
    "/opt/homebrew/opt/postgresql@17/bin",
    "/usr/lib/postgresql/16/bin",
    "/Library/PostgreSQL/17/bin",
    "/Library/PostgreSQL/16/bin",
)


def _pg_bin() -> str | None:
    if shutil.which("initdb"):
        return ""
    for candidate in _PG_BIN_CANDIDATES:
        if Path(candidate, "initdb").is_file():
            return candidate
    return None


def _start_cluster(tmp: Path) -> tuple[str, subprocess.Popen | None]:
    """A throwaway cluster, or a skip if this machine has no Postgres."""
    binaries = _pg_bin()
    if binaries is None:
        pytest.skip(
            "no Postgres available: set MEMKIT_TEST_DATABASE_URL or install PostgreSQL",
            allow_module_level=True,
        )
    prefix = f"{binaries}/" if binaries else ""
    data = tmp / "pgdata"
    # The socket lives outside the data directory: a Unix socket path is capped
    # at 103 bytes and pytest's temp paths are long enough to exceed it.
    socket_dir = Path(tempfile.mkdtemp(prefix="mkpg."))
    port = "54329"
    # An explicit UTF-8 locale, not the shell's. A cluster initialised under C
    # cannot fold Cyrillic case, which is the one thing the full-text tests are
    # there to prove.
    subprocess.run(  # noqa: S603
        [
            f"{prefix}initdb",
            "-D",
            str(data),
            "-U",
            "memkit",
            "--auth=trust",
            "-E",
            "UTF8",
            "--locale=C.UTF-8",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [
            f"{prefix}pg_ctl",
            "-D",
            str(data),
            "-o",
            f"-p {port} -k {socket_dir} -c listen_addresses=127.0.0.1 -c fsync=off",
            "-l",
            str(data / "server.log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603
        [f"{prefix}createdb", "-h", "127.0.0.1", "-p", port, "-U", "memkit", "memkit_test"],
        check=True,
        capture_output=True,
    )
    return f"postgresql://memkit@127.0.0.1:{port}/memkit_test", None


def _worker_database(url: str) -> str:
    """A database of this worker's own, cloned from the one it was given.

    Every test truncates every table, so two workers sharing a database
    deadlock against each other and fail in ways that have nothing to do with
    the code under test. `xdist` gives each worker an id; without it there is
    one worker and one database.
    """
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if not worker:
        return url
    import psycopg

    base, _, name = url.rpartition("/")
    target = f"{name}_{worker}"
    with psycopg.connect(f"{base}/postgres", autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{target}"')
        # TEMPLATE copies the extensions with it, so pg_trgm needs no reinstall.
        admin.execute(f'CREATE DATABASE "{target}" TEMPLATE "{name}"')
    return f"{base}/{target}"


@pytest.fixture(scope="session")
def database_url() -> str:
    """A migrated database for the whole session, private to this worker."""
    from memkit import db

    external = os.environ.get("MEMKIT_TEST_DATABASE_URL")
    tmp = Path(tempfile.mkdtemp(prefix="memkit-tests-"))
    stop_path: Path | None = None
    if external:
        url = external
    else:
        url, _ = _start_cluster(tmp)
        stop_path = tmp / "pgdata"
    db.init_db(url)
    url = _worker_database(url)
    os.environ["MEMKIT_DATABASE_URL"] = url
    db.init_db(url)
    yield url
    if stop_path is not None:
        binaries = _pg_bin() or ""
        prefix = f"{binaries}/" if binaries else ""
        subprocess.run(  # noqa: S603
            [f"{prefix}pg_ctl", "-D", str(stop_path), "-m", "immediate", "stop"],
            check=False,
            capture_output=True,
        )
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_database(database_url: str):
    """Every test starts from an empty, freshly seeded schema."""
    from memkit import config, db

    config.reset_settings()
    conn = db.connect(database_url)
    db.truncate_all(conn)
    yield conn
    conn.close()
