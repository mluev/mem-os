"""Execute the CLI's remote restore payload against a disposable Postgres schema."""

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.conftest import _pg_bin


def test_remote_restore_replaces_database_contents(clean_database, database_url, tmp_path):
    # Read the exact self-contained payload without adding the standalone CLI
    # package to the server's runtime or development dependencies.
    worker = Path(__file__).resolve().parents[1] / "cli/src/memos_cli/assets/server_worker.py"
    module = ast.parse(worker.read_text())
    payload = next(
        ast.literal_eval(node.value)
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "RESTORE" for target in node.targets)
    )
    conn = clean_database
    environment = dict(
        os.environ,
        MEMKIT_DATABASE_URL=database_url,
        PATH=os.pathsep.join([_pg_bin() or "", os.environ.get("PATH", "")]),
    )
    archive = tmp_path / "snapshot.dump"
    pg_dump = shutil.which("pg_dump", path=environment["PATH"])
    assert pg_dump is not None, "Postgres client tools are required for the restore check"
    conn.execute("CREATE SCHEMA managed_restore_probe")
    try:
        conn.execute("CREATE TABLE managed_restore_probe.facts (text text)")
        conn.execute("INSERT INTO managed_restore_probe.facts VALUES ('before backup')")
        subprocess.run(  # noqa: S603 -- disposable test database only
            [
                pg_dump,
                "--format=custom",
                "--schema=managed_restore_probe",
                f"--dbname={database_url}",
                f"--file={archive}",
            ],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        conn.execute("INSERT INTO managed_restore_probe.facts VALUES ('after backup')")
        result = subprocess.run(  # noqa: S603 -- reviewed self-contained restore payload
            [sys.executable, "-c", payload, str(archive)],
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert [
            row["text"] for row in conn.execute("SELECT text FROM managed_restore_probe.facts")
        ] == ["before backup"]
    finally:
        conn.execute("DROP SCHEMA managed_restore_probe CASCADE")
