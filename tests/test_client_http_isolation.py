"""Private memory stays private through the shipped clients over real HTTP."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn

from memkit import api
from sdk.python.memkit_client.api.default import get_memory_v1_memories_memory_id_get
from sdk.python.memkit_client.client import AuthenticatedClient
from tests.httpharness import ApiTestCase

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_TEXT = "Alice's private launch passphrase is saffron-lighthouse-739."


class ClientHttpIsolationTest(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.memory_id = self.seed_memory(text=PRIVATE_TEXT)
        # The harness has already initialized the real app with offline adapters.
        # Passing a bound socket avoids a port-selection race; disabling lifespan
        # avoids starting another worker or loading a production embedding model.
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.base_url = f"http://127.0.0.1:{self.listener.getsockname()[1]}"
        self.server = uvicorn.Server(
            uvicorn.Config(
                api.app,
                lifespan="off",
                log_level="error",
                access_log=False,
                timeout_graceful_shutdown=2,
            )
        )
        self.thread = threading.Thread(
            target=self.server.run, kwargs={"sockets": [self.listener]}, daemon=True
        )
        self.addCleanup(self._stop_server)
        self.thread.start()
        deadline = time.monotonic() + 5
        while not self.server.started and self.thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server.started, "local HTTP server did not start within five seconds")

    def _stop_server(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            self.server.force_exit = True
            self.thread.join(timeout=1)
        self.listener.close()
        self.assertFalse(self.thread.is_alive(), "local HTTP server did not stop")

    def test_generated_python_client_enforces_private_scope(self) -> None:
        for actor, key, status in (("alice", self.alice_key, 200), ("bob", self.bob_key, 404)):
            with (
                self.subTest(actor=actor),
                AuthenticatedClient(
                    base_url=self.base_url,
                    token=key,
                    timeout=httpx.Timeout(3),
                    httpx_args={"trust_env": False},
                ) as client,
            ):
                response = get_memory_v1_memories_memory_id_get.sync_detailed(
                    self.memory_id, client=client
                )
                self.assertEqual(response.status_code, status, response.content)
                if actor == "alice":
                    self.assertEqual(response.parsed.memory.text, PRIVATE_TEXT)
                else:
                    self.assertIsNone(response.parsed)
                    self.assertNotIn(PRIVATE_TEXT.encode(), response.content)

    def test_generated_typescript_client_enforces_private_scope(self) -> None:
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required to test the shipped TypeScript client")
        entry = ROOT / "sdk/typescript/dist/index.js"
        self.assertTrue(entry.is_file(), "build the TypeScript SDK before running its HTTP test")
        script = f"""
            import {{ readFileSync }} from 'node:fs';
            import {{ createMemkitClient }} from {json.dumps(entry.as_uri())};
            const input = JSON.parse(readFileSync(0, 'utf8'));
            const results = [];
            for (const apiKey of input.keys) {{
                const client = createMemkitClient({{ baseUrl: input.baseUrl, apiKey }});
                const result = await client.GET('/v1/memories/{{memory_id}}', {{
                    params: {{ path: {{ memory_id: input.memoryId }} }},
                    signal: AbortSignal.timeout(3000),
                }});
                results.push({{ status: result.response.status, data: result.data,
                                error: result.error }});
            }}
            process.stdout.write(JSON.stringify(results));
        """
        process = subprocess.run(  # noqa: S603
            [node, "--input-type=module", "-e", script],
            input=json.dumps(
                {
                    "baseUrl": self.base_url,
                    "memoryId": self.memory_id,
                    "keys": [self.alice_key, self.bob_key],
                }
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        alice, bob = json.loads(process.stdout)
        self.assertEqual(alice["status"], 200)
        self.assertEqual(alice["data"]["memory"]["text"], PRIVATE_TEXT)
        self.assertEqual(bob["status"], 404)
        self.assertNotIn("data", bob)
        self.assertNotIn(PRIVATE_TEXT, json.dumps(bob))
        self.assertNotIn(PRIVATE_TEXT, process.stderr)

    def test_standalone_memos_cli_enforces_private_scope(self) -> None:
        with TemporaryDirectory(prefix="memkit-http-client-") as directory:
            config = {
                "default": "alice",
                "connections": {
                    "alice": {"url": self.base_url, "key": self.alice_key},
                    "bob": {"url": self.base_url, "key": self.bob_key},
                },
            }
            Path(directory, "connections.json").write_text(json.dumps(config))
            env = {
                key: value
                for key, value in os.environ.items()
                if key
                not in {
                    "MEMOS_URL",
                    "MEMKIT_BASE_URL",
                    "MEMOS_API_KEY",
                    "MEMKIT_API_KEY",
                    "MEMOS_CONNECTION",
                }
            }
            env.update(
                MEMOS_CONFIG_DIR=directory,
                PYTHONPATH=str(ROOT / "cli/src"),
                NO_PROXY="127.0.0.1",
                no_proxy="127.0.0.1",
            )
            for actor, exit_code in (("alice", 0), ("bob", 5)):
                with self.subTest(actor=actor):
                    process = subprocess.run(  # noqa: S603
                        [
                            sys.executable,
                            "-m",
                            "memos_cli",
                            "--connection",
                            actor,
                            "--json",
                            "--timeout",
                            "3",
                            "memories",
                            "get",
                            self.memory_id,
                        ],
                        cwd=directory,
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=10,
                        check=False,
                    )
                    self.assertEqual(process.returncode, exit_code, process.stdout + process.stderr)
                    payload = json.loads(process.stdout)
                    if actor == "alice":
                        self.assertTrue(payload["ok"])
                        self.assertEqual(payload["data"]["memory"]["text"], PRIVATE_TEXT)
                    else:
                        self.assertFalse(payload["ok"])
                        self.assertEqual(payload["error"]["status"], 404)
                        self.assertEqual(payload["error"]["code"], "not_found")
                        self.assertNotIn(PRIVATE_TEXT, process.stdout + process.stderr)
