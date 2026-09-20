"""The stdlib HTTP client the thin clients share (src/memkit/remote.py).

Four claims are worth a real socket rather than a mock:

* config precedence, because there is no instance-wide key any more -- a client
  reading the wrong file does not get a degraded answer, it gets nobody's memory;
* the timeout is per call, because the calls it serves differ by two orders of
  magnitude in what they may cost;
* a 4xx does not count toward opening the breaker, because a scope typo is the
  service answering and must not silence memory for two minutes;
* nothing here imports anything outside the standard library, because the hook
  process that imports it has five seconds and `memkit.api` reaches torch.
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from memkit import remote

ROOT = Path(__file__).resolve().parents[1]
CONFIG_VARS = ("MEMKIT_BASE_URL", "MEMKIT_API_KEY")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:
        self._respond("GET", b"")

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        self._respond("POST", self.rfile.read(length))

    def _respond(self, method: str, body: bytes) -> None:
        self.server.seen.append(
            {
                "method": method,
                "path": self.path,
                "key": self.headers.get("X-API-Key"),
                "body": body.decode() or None,
            }
        )
        status, payload, delay = self.server.routes.get(
            self.path.split("?")[0], (404, b'{"detail":"unknown"}', 0.0)
        )
        if delay:
            time.sleep(delay)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        """Silence: the suite's output is a signal, not a web server log."""

    def handle_one_request(self) -> None:
        # A timeout test hangs up mid-response on purpose, so the broken pipe
        # that follows is the expected outcome and not suite noise.
        with contextlib.suppress(OSError):
            super().handle_one_request()


class ServiceTestCase(unittest.TestCase):
    """A real loopback service, so timeouts and status codes are the real thing."""

    def setUp(self) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.routes = {}
        self.server.seen = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def route(self, path: str, status: int, payload: object, *, delay: float = 0.0) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.server.routes[path] = (status, body, delay)

    def client(self, **kwargs: object) -> remote.Client:
        return remote.Client(self.base_url, "mk_test_secret", **kwargs)


class ConfigPrecedenceTest(unittest.TestCase):
    """Environment, then ~/.config/memkit/client.env, then the deprecated file."""

    def setUp(self) -> None:
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.client_env = self.tmp / "client.env"
        self.legacy_env = self.tmp / "legacy"
        for name, value in (("CLIENT_ENV", self.client_env), ("LEGACY_ENV", self.legacy_env)):
            original = getattr(remote, name)
            setattr(remote, name, value)
            self.addCleanup(setattr, remote, name, original)
        for name in CONFIG_VARS:
            original = os.environ.pop(name, None)
            if original is not None:
                self.addCleanup(os.environ.__setitem__, name, original)
            else:
                self.addCleanup(os.environ.pop, name, None)
        remote._legacy_reported = False
        self.addCleanup(setattr, remote, "_legacy_reported", False)

    def resolve(self) -> tuple[tuple[str, str], str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            resolved = remote.resolve_config()
        return resolved, stderr.getvalue()

    def test_environment_wins_over_every_file(self) -> None:
        self.client_env.write_text("MEMKIT_BASE_URL=http://file\nMEMKIT_API_KEY=from-file\n")
        os.environ["MEMKIT_BASE_URL"] = "http://env"
        os.environ["MEMKIT_API_KEY"] = "from-env"
        self.assertEqual(self.resolve()[0], ("http://env", "from-env"))

    def test_client_env_is_read_and_quoting_is_stripped(self) -> None:
        self.client_env.write_text(
            "# a comment\nMEMKIT_BASE_URL=http://127.0.0.1:9000\nMEMKIT_API_KEY='mk_a_b'\n"
        )
        self.assertEqual(self.resolve()[0], ("http://127.0.0.1:9000", "mk_a_b"))

    def test_each_variable_falls_through_independently(self) -> None:
        """A base URL in the environment must not hide a key that is only in a file."""
        os.environ["MEMKIT_BASE_URL"] = "http://env"
        self.client_env.write_text("MEMKIT_API_KEY=from-file\n")
        self.assertEqual(self.resolve()[0], ("http://env", "from-file"))

    def test_client_env_takes_precedence_over_the_legacy_file(self) -> None:
        self.client_env.write_text("MEMKIT_API_KEY=new\n")
        self.legacy_env.write_text("MEMKIT_API_KEY=old\n")
        resolved, stderr = self.resolve()
        self.assertEqual(resolved[1], "new")
        self.assertEqual(stderr, "", "the legacy file was not used, so say nothing about it")

    def test_legacy_file_works_and_says_so_once(self) -> None:
        """The deprecation is worth exactly one line, and only when it is used.

        `memkit doctor` reports this too, but doctor is what somebody runs after
        a problem. A key coming from a path nothing writes any more is the moment
        to mention it -- once per process, because one hook run resolves config
        more than once and three identical lines read as a fault.
        """
        self.legacy_env.write_text("MEMKIT_API_KEY=legacy-key\n")
        resolved, stderr = self.resolve()
        self.assertEqual(resolved, (remote.DEFAULT_BASE_URL, "legacy-key"))
        self.assertEqual(stderr.count("deprecated"), 1)
        self.assertIn(str(self.client_env), stderr)
        self.assertEqual(self.resolve()[1], "", "the notice must not repeat in one process")

    def test_no_config_yields_the_default_url_and_no_key(self) -> None:
        resolved, stderr = self.resolve()
        self.assertEqual(resolved, (remote.DEFAULT_BASE_URL, ""))
        self.assertEqual(stderr, "")

    def test_connect_returns_none_without_a_key(self) -> None:
        self.assertIsNone(remote.connect())
        self.client_env.write_text("MEMKIT_API_KEY=mk_x_y\n")
        self.assertIsInstance(remote.connect(), remote.Client)

    def test_trailing_slash_never_reaches_a_path(self) -> None:
        self.client_env.write_text("MEMKIT_BASE_URL=http://127.0.0.1:9000/\nMEMKIT_API_KEY=k\n")
        self.assertEqual(self.resolve()[0][0], "http://127.0.0.1:9000")


class TransportTest(ServiceTestCase):
    def test_post_sends_the_key_and_the_body(self) -> None:
        self.route("/v1/memories", 201, {"id": "m-1"})
        result = self.client().post("/v1/memories", {"text": "hi"})
        self.assertEqual(result, {"id": "m-1"})
        seen = self.server.seen[-1]
        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["key"], "mk_test_secret")
        self.assertEqual(json.loads(seen["body"]), {"text": "hi"})

    def test_get_encodes_params_and_sends_no_body(self) -> None:
        self.route("/v1/entities", 200, {"items": []})
        self.client().get("/v1/entities", {"kind": "project"})
        seen = self.server.seen[-1]
        self.assertEqual(seen["path"], "/v1/entities?kind=project")
        self.assertIsNone(seen["body"])

    def test_a_post_with_no_body_still_sends_json(self) -> None:
        """`POST /v1/sessions/{id}/close` takes no arguments but is still JSON."""
        self.route("/v1/sessions/s1/close", 202, {"status": "queued"})
        self.assertEqual(self.client().post("/v1/sessions/s1/close"), {"status": "queued"})
        self.assertEqual(json.loads(self.server.seen[-1]["body"]), {})

    def test_a_non_http_base_url_is_refused_at_construction(self) -> None:
        for bad in ("file:///etc/passwd", "127.0.0.1:8077", ""):
            with self.assertRaises(ValueError):
                remote.Client(bad, "k")

    def test_malformed_json_is_an_error_not_a_crash(self) -> None:
        self.route("/v1/memories/search", 200, b"<html>proxy error</html>")
        client = self.client()
        with self.assertRaises(remote.RemoteError) as caught:
            client.post("/v1/memories/search", {"query": "x"})
        self.assertIn("not JSON", str(caught.exception))
        # A proxy's HTML is a broken peer, not a dead service.
        self.assertTrue(client.breaker.allow())

    def test_an_empty_body_reads_as_an_empty_object(self) -> None:
        self.route("/v1/memories/m1", 200, b"")
        self.assertEqual(self.client().get("/v1/memories/m1"), {})


class TimeoutTest(ServiceTestCase):
    def test_the_per_call_timeout_beats_the_client_default(self) -> None:
        """0.4s for a recall and 30s for a session close cannot share one setting."""
        self.route("/v1/memories/search", 200, {"memories": []}, delay=2.0)
        client = self.client(timeout=30.0)
        started = time.monotonic()
        with self.assertRaises(remote.RemoteError):
            client.post("/v1/memories/search", {"query": "x"}, timeout=0.3)
        self.assertLess(time.monotonic() - started, 1.5)

    def test_a_timeout_counts_toward_the_breaker(self) -> None:
        self.route("/v1/memories/search", 200, {"memories": []}, delay=2.0)
        client = self.client(breaker=remote.Breaker(fails=2, cooldown=60))
        for _ in range(2):
            with self.assertRaises(remote.RemoteError):
                client.post("/v1/memories/search", {"query": "x"}, timeout=0.2)
        self.assertFalse(client.breaker.allow())
        before = len(self.server.seen)
        with self.assertRaises(remote.RemoteError) as caught:
            client.post("/v1/memories/search", {"query": "x"}, timeout=0.2)
        self.assertEqual(str(caught.exception), "circuit open")
        self.assertEqual(len(self.server.seen), before, "an open circuit must not dial out")


class BreakerTest(ServiceTestCase):
    def test_a_client_error_answers_with_its_status_and_leaves_the_breaker_shut(self) -> None:
        """A 403 on a scope the key cannot write is an answer, not an outage.

        The hook reads `status` to decide whether to resend the batch privately,
        and if the breaker opened on it, the resend would never be attempted.
        """
        self.route("/v1/evidence/events:batch", 403, {"detail": "scope is not accessible"})
        client = self.client(breaker=remote.Breaker(fails=2, cooldown=60))
        for _ in range(4):
            with self.assertRaises(remote.RemoteError) as caught:
                client.post("/v1/evidence/events:batch", {"events": []})
            self.assertEqual(caught.exception.status, 403)
        self.assertTrue(client.breaker.allow())

    def test_server_errors_open_the_breaker_and_the_cooldown_expires(self) -> None:
        self.route("/v1/profiles/render", 500, {"detail": "boom"})
        client = self.client(breaker=remote.Breaker(fails=3, cooldown=0.2))
        for _ in range(3):
            with self.assertRaises(remote.RemoteError):
                client.post("/v1/profiles/render", {})
        self.assertFalse(client.breaker.allow())
        time.sleep(0.25)
        self.assertTrue(client.breaker.allow(), "the breaker must reclose on its own")

    def test_a_success_resets_the_failure_run(self) -> None:
        self.route("/v1/healthz", 500, {"detail": "boom"})
        self.route("/healthz", 200, {"ok": True})
        client = self.client(breaker=remote.Breaker(fails=2, cooldown=60))
        with self.assertRaises(remote.RemoteError):
            client.get("/v1/healthz")
        client.get("/healthz")
        with self.assertRaises(remote.RemoteError):
            client.get("/v1/healthz")
        self.assertTrue(client.breaker.allow(), "non-consecutive failures must not open it")


class ImportCostTest(unittest.TestCase):
    def test_remote_imports_nothing_but_the_standard_library(self) -> None:
        """The reason this module exists separately at all.

        A SessionStart hook has five seconds. `memkit.api` and `memkit.retrieval`
        reach sentence-transformers and therefore torch, whose import alone
        exceeds that budget on this machine, so a client that grew one convenient
        `from .config import ...` would turn every session start into a timeout
        the user experiences as a broken editor.
        """
        tree = ast.parse((ROOT / "src" / "memkit" / "remote.py").read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0, "a relative import would drag in memkit")
                modules.add((node.module or "").split(".")[0])
        self.assertTrue(modules)
        for module in modules:
            self.assertIn(module, sys.stdlib_module_names, f"{module} is not standard library")


if __name__ == "__main__":
    unittest.main()
