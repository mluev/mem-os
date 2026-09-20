"""Minimal HTTP client for the memkit service, plus its circuit breaker.

Stdlib `urllib` on purpose. Hermes pins httpx, but a plugin dropped into someone
else's environment should not care what that environment installs, and this is a
handful of small JSON posts to loopback. Nothing here is hot enough to need more.

`resolve_config` duplicates `memkit.remote.resolve_config` rather than importing
it. That is deliberate and it is the only duplication in this file: the plugin is
copied into `$HERMES_HOME/plugins/memkit` and runs under Hermes's interpreter,
which has no reason to have memkit installed at all. The two copies are held
together by tests/test_hermes_provider.py, which asserts the same precedence.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8077"
CLIENT_ENV = Path("~/.config/memkit/client.env").expanduser()
LEGACY_ENV = Path("~/.memkit").expanduser()

# The blocks /v1/profiles/render answers with, in the order it spends the budget.
PROFILE_BLOCKS = ("about", "style", "team", "project", "recent")


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip("'\"")
    return values


def resolve_config() -> tuple[str, str]:
    """The service URL and *this person's* key, by falling precedence.

    There is no instance-wide key any more: the key names the user, so a plugin
    that reads a stale file does not get a degraded answer, it writes into the
    wrong person's memory or none at all. Hence the same order everything else
    uses -- environment, ~/.config/memkit/client.env, then the deprecated
    ~/.memkit.
    """
    if Path(__file__).with_name("bridge.json").is_file():
        # The installed bridge resolves the selected CLI connection on each call.
        return "https://memos-managed.invalid", "memos-managed-identity"
    base = os.environ.get("MEMKIT_BASE_URL", "").strip()
    key = os.environ.get("MEMKIT_API_KEY", "").strip()
    for path in (CLIENT_ENV, LEGACY_ENV):
        if base and key:
            break
        values = _read_env_file(path)
        if not base:
            base = values.get("MEMKIT_BASE_URL", "")
        if not key:
            key = values.get("MEMKIT_API_KEY", "")
        if key and path is LEGACY_ENV:
            logger.warning("memkit: %s is deprecated; move the key to %s", path, CLIENT_ENV)
    return (base or DEFAULT_BASE_URL).rstrip("/"), key


class Breaker:
    """Five consecutive failures, then two minutes off.

    Copied in spirit from the mem0 provider. The point is that the agent keeps
    working without memory rather than paying the timeout on every turn while the
    service is down. A 404 is an expected answer, not a failure — only network
    errors and 5xx count, which is enforced by the caller.
    """

    def __init__(self, fails: int = 5, cooldown: int = 120) -> None:
        self.fails = fails
        self.cooldown = cooldown
        self._n = 0
        self._until = 0.0

    def allow(self) -> bool:
        return time.time() >= self._until

    def ok(self) -> None:
        self._n = 0

    def fail(self) -> None:
        self._n += 1
        if self._n >= self.fails:
            self._until = time.time() + self.cooldown
            self._n = 0
            logger.warning("memkit: circuit open for %ss", self.cooldown)


class MemkitError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Client:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 2.0,
        breaker: Breaker | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an http(s) URL")
        self.api_key = api_key
        self.timeout = timeout
        self.breaker = breaker or Breaker()

    # -- transport ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        if not self.breaker.allow():
            raise MemkitError("circuit open")
        bridge = Path(__file__).with_name("bridge.json")
        if bridge.is_file():
            return self._bridge_request(bridge, method, path, body, timeout=timeout)
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)  # noqa: S310 -- scheme validated in __init__
        req.add_header("X-API-Key", self.api_key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:  # noqa: S310 -- validated URL
                payload = resp.read()
            self.breaker.ok()
            return json.loads(payload) if payload else None
        except urllib.error.HTTPError as exc:
            # 4xx is the service answering, not failing: an unknown id or a
            # rejected body must not push the breaker toward opening.
            if exc.code >= 500:
                self.breaker.fail()
            raise MemkitError(f"http {exc.code}", status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.breaker.fail()
            raise MemkitError(str(exc)) from exc

    def _bridge_request(self, bridge, method, path, body, *, timeout):
        seconds = timeout or self.timeout
        try:
            command = json.loads(bridge.read_text())["command"]
            if (
                not isinstance(command, list)
                or not command
                or not all(isinstance(part, str) and part for part in command)
            ):
                raise ValueError("invalid bridge command")
            process = subprocess.run(  # noqa: S603 -- installed interpreter and module, no shell
                [*command, "internal", "request", "--json", "--timeout", str(seconds)],
                input=json.dumps({"method": method, "path": path, "body": body}),
                text=True,
                capture_output=True,
                timeout=seconds + 1,
            )
            result = json.loads(process.stdout)
            if not isinstance(result, dict):
                raise ValueError("invalid bridge response")
            if not result.get("ok"):
                error = result.get("error", {})
                if not isinstance(error, dict):
                    raise ValueError("invalid bridge error")
                status = error.get("status")
                if status is None or status >= 500:
                    self.breaker.fail()
                raise MemkitError(error.get("message", "Mem OS unavailable"), status=status)
            self.breaker.ok()
            return result["data"]
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
            self.breaker.fail()
            raise MemkitError("Mem OS CLI unavailable") from exc

    # -- endpoints ---------------------------------------------------------

    def healthz(self, *, timeout: float = 1.0) -> dict[str, Any]:
        return self._request("GET", "/healthz", timeout=timeout) or {}

    def search(
        self,
        query: str,
        *,
        budget_tokens: int = 800,
        limit: int = 30,
        context: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        result = self.search_with_run(
            query,
            budget_tokens=budget_tokens,
            limit=limit,
            context=context,
            timeout=timeout,
        )
        return list(result.get("memories") or [])

    def search_with_run(
        self,
        query: str,
        *,
        budget_tokens: int = 800,
        limit: int = 30,
        context: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "budget_tokens": budget_tokens,
            "limit": limit,
        }
        if context:
            body["filter"] = {
                "all": [
                    {"field": f"context.{key}", "op": "eq", "value": value}
                    for key, value in context.items()
                ]
            }
        return self._request("POST", "/v1/memories/search", body, timeout=timeout) or {}

    def retrieval_feedback(
        self,
        retrieval_id: str,
        memory_id: str,
        *,
        useful: bool | None = None,
        correct: bool | None = None,
    ) -> dict[str, Any]:
        return (
            self._request(
                "POST",
                f"/v1/retrieval-runs/{retrieval_id}/feedback",
                {"memory_id": memory_id, "useful": useful, "correct": correct},
            )
            or {}
        )

    def render_profile(
        self,
        *,
        blocks: list[str] | None = None,
        workspace: str | None = None,
        budget_tokens: int = 800,
        timeout: float | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """The five profile blocks, flattened by the caller.

        Replaces the old `{stable, dynamic}` response, which is gone: the stable
        half was selected by `kind` and dropped identity facts entirely once they
        aged out of the dynamic window.
        """
        body: dict[str, Any] = {
            "blocks": list(blocks or PROFILE_BLOCKS),
            "budget_tokens": budget_tokens,
        }
        if workspace:
            body["workspace"] = workspace
        result = self._request("POST", "/v1/profiles/render", body, timeout=timeout) or {}
        return dict(result.get("blocks") or {})

    def add_events(self, payloads: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request("POST", "/v1/evidence/events:batch", {"events": payloads}) or {}

    def add_memory(
        self,
        text: str,
        *,
        kind: str = "fact",
        importance: float = 0.9,
        context: dict[str, Any] | None = None,
        source_role: str = "assistant",
        scope: str | None = None,
        subject: str | None = None,
    ) -> dict[str, Any]:
        """Write a fact directly, bypassing the judge.

        `source_role` defaults to "assistant" because every caller of this method
        inside the plugin is the model: `on_memory_write` mirrors what the agent
        decided to remember, and `memkit_remember` is a tool the model invokes.
        Neither passes through the extractor prompt, so neither has been checked
        against "store what the user stated, not what the assistant said".

        Before the label existed these landed indistinguishable from a human
        write. Measured on one real session: eight new facts, seven of them from
        this path at importance 0.8-0.95, including the same claim stored four
        times in slightly different words.

        `scope` and `subject` are omitted unless set, because omitting `scope` is
        what makes a write private: a fact that should have been shared can be
        moved later, and one that should not have been cannot be unshared.
        """
        body: dict[str, Any] = {
            "text": text,
            "kind": kind,
            "context": context or {},
            "tags": [],
            "importance": importance,
            "confidence": 0.9,
            "agent_id": "hermes",
            "source_role": source_role,
        }
        if scope:
            body["scope"] = scope
        if subject:
            body["subject"] = subject
        return self._request("POST", "/v1/memories", body) or {}

    def close_session(self, session_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/close", {}, timeout=timeout) or {}
