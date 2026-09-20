"""Opt-in destructive smoke test against a disposable SSH host only.

Creates an isolated managed deployment, exercises a real restore, and leaves it
stopped for inspection. Docker and embedding downloads occur on that host.
"""

# ruff: noqa: S101, S603 -- acceptance test invoking only the installed CLI

import argparse
import json
import os
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--source", required=True, help="repository checkout on the SSH host")
    args = parser.parse_args()
    ssh_binary = shutil.which("ssh")
    if ssh_binary is None:
        parser.error("SSH is required for the disposable-host smoke test")
    identifier = uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix="memos-smoke-") as temporary:
        folder = Path(temporary)
        environment = dict(os.environ, MEMOS_CONFIG_DIR=str(folder / "config"))
        password = folder / "password"
        password.write_text(secrets.token_urlsafe(24))
        password.chmod(0o600)

        def call(*words, succeeds=True):
            result = subprocess.run(
                [sys.executable, "-m", "memos_cli", *words, "--json"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=2400,
            )
            body = json.loads(result.stdout)
            assert (result.returncode == 0) == succeeds, body
            return body.get("data", body)

        directory = f".local/share/memos/smoke-{identifier}"
        installed = False
        try:
            call(
                "server",
                "install",
                "--host",
                args.host,
                "--directory",
                directory,
                "--source",
                args.source,
                "--image",
                "memos-smoke:one",
                "--password-file",
                str(password),
                "--remote-port",
                "18078",
                "--local-port",
                "18079",
            )
            installed = True
            call("status")
            call("server", "tunnel", "--close")
            call("health")  # Public commands must reopen the configured tunnel too.
            saved = call("remember", "Smoke fixture before backup")
            memory_id = saved["id"]
            backup = call("server", "backup", "create", "--protected")
            call("server", "restart")
            call("memories", "get", memory_id)
            call(
                "server",
                "install",
                "--host",
                args.host,
                "--directory",
                directory,
                "--source",
                args.source,
                "--image",
                "memos-smoke:one",
                "--password-file",
                str(password),
            )
            call("status")  # Omitted ports must preserve both the tunnel and the API key.
            call("server", "upgrade", "--source", args.source, "--image", "memos-smoke:two")
            call("server", "upgrade", "--image", "invalid.invalid/memos:missing", succeeds=False)
            call("status")
            # Create fixtures only on this explicitly disposable remote host.
            prepare = """import json,sys
from pathlib import Path
root=Path.home()/sys.argv[1]
failure=root/'failure-source'; failure.mkdir()
(failure/'Dockerfile').write_text('FROM memos-smoke:two\\nHEALTHCHECK --interval=1s --timeout=1s --start-period=0s --retries=1 CMD false\\n')
transcripts=root/'imports'/'audit'; transcripts.mkdir()
records=[{'type':'user','uuid':'smoke-turn-'+str(i),'sessionId':'smoke-import','message':{'content':'Smoke import preference number '+str(i)}} for i in range(2)]
(transcripts/'session.jsonl').write_text(''.join(json.dumps(r)+'\\n' for r in records))
print(json.dumps({'failure':str(failure),'transcripts':str(transcripts)}))
"""
            prepared = subprocess.run(
                [
                    ssh_binary,
                    "-o",
                    "BatchMode=yes",
                    args.host,
                    shlex.join(["python3", "-c", prepare, directory]),
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            fixtures = json.loads(prepared.stdout)
            preview = call(
                "server", "import-claude-code", "--path", fixtures["transcripts"], "--limit", "1"
            )
            assert "dry run: 1 normalized events" in preview["report"], preview
            failed = call(
                "server",
                "upgrade",
                "--source",
                fixtures["failure"],
                "--image",
                "memos-smoke:unhealthy",
                succeeds=False,
            )
            assert "previous image restored" in failed["error"]["message"], failed
            assert call("server", "status")["deployment"]["image"] == "memos-smoke:two"
            call("memories", "get", memory_id)
            later = call("remember", "Smoke fixture after backup")["id"]
            call("server", "backup", "verify", backup["id"])
            call(
                "server",
                "backup",
                "download",
                backup["id"],
                "--output",
                str(folder / "backup.dump"),
            )
            call("server", "backup", "restore", backup["id"], "--confirm", "RESTORE")
            call("memories", "get", memory_id)
            call("memories", "get", later, succeeds=False)
            call("export", "--wait", "60", "--output", str(folder / "export.json"))
            assert json.loads((folder / "export.json").read_text())
            print(
                "Remote install, persistence, upgrade, failure recovery, backup/restore and export passed."
            )
        finally:
            if installed:
                call("server", "stop")
                call("server", "tunnel", "--close")


if __name__ == "__main__":
    main()
