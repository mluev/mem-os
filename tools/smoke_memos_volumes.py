"""Check managed cache permissions across containers on a disposable Docker host.

Only the uniquely named test project and its volume are removed afterward.
The model cache intentionally stays empty to exercise Docker's copy-up behavior.
"""

# ruff: noqa: S603 -- acceptance test against an explicitly disposable Docker host

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    path = Path(__file__).resolve().parents[1] / "cli/src/memos_cli/assets/server_worker.py"
    spec = importlib.util.spec_from_file_location("server_worker", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    project = "memos-permissions-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=project) as directory:
        root = Path(directory)
        config = worker.compose_config(args.image, 8077, False)
        app = config["services"]["app"]
        app.pop("depends_on")
        app["environment"] = {}
        app["ports"] = []
        config["services"] = {"app": app}
        config["volumes"] = {"models": {}}
        for folder in ("backups", "exports", "imports"):
            (root / folder).mkdir()
        compose = root / "compose.json"
        compose.write_text(json.dumps(config))
        command = ["docker", "compose", "-p", project, "-f", str(compose)]

        def run(*words):
            subprocess.run([*command, *words], check=True, timeout=120)

        try:
            run(
                "run",
                "--rm",
                "--no-deps",
                "--user",
                "0",
                "app",
                "chown",
                "-R",
                f"{os.getuid() or 10001}:{os.getgid() or 10001}",
                "/models",
                "/backups",
                "/exports",
            )
            # Each run creates a fresh container. Remove the probe so the next
            # creation encounters an empty cache just like first installation.
            probe = (
                "from pathlib import Path; "
                "paths=[Path(p)/'permission-probe' for p in ('/models','/backups','/exports')]; "
                "[(p.write_text('ok'), p.unlink()) for p in paths]"
            )
            for _ in range(2):
                run("run", "--rm", "--no-deps", "app", "python", "-c", probe)
            print("Managed cache and artifact directories remain writable across containers.")
        finally:
            run("down", "--volumes")


if __name__ == "__main__":
    main()
