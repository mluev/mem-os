"""Minimal HTTP client for the memkit service, plus its circuit breaker.

Stdlib `urllib` on purpose. Hermes pins httpx, but a plugin dropped into someone
else's environment should not care what that environment installs, and this is a
handful of small JSON posts to loopback. Nothing here is hot enough to need more.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


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
        owner_id: str = "u-1",
        timeout: float = 2.0,
        breaker: Breaker | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.owner_id = owner_id
        self.timeout = timeout
        self.breaker = breaker or Breaker()

    # -- transport ---------------------------------------------------------

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None,
        *, timeout: float | None = None,
    ) -> Any:
        if not self.breaker.allow():
            raise MemkitError("circuit open")
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("X-API-Key", self.api_key)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
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

    # -- endpoints ---------------------------------------------------------

    def healthz(self, *, timeout: float = 1.0) -> dict[str, Any]:
        return self._request("GET", "/healthz", timeout=timeout) or {}

    def search(
        self,
        query: str,
        *,
        budget_tokens: int = 800,
        limit: int = 30,
        scopes: list[str] | None = None,
        scope_key: str | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "query": query,
            "owner_id": self.owner_id,
            "agent_id": "hermes",
            "budget_tokens": budget_tokens,
            "limit": limit,
        }
        if scopes:
            body["scopes"] = scopes
        if scope_key:
            body["scope_key"] = scope_key
        result = self._request("POST", "/v1/search", body, timeout=timeout) or {}
        return list(result.get("memories") or [])

    def add_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/messages", payload) or {}

    def add_memory(
        self, text: str, *, type: str = "fact", importance: float = 0.9,
        scope: str = "user",
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/memories",
            {
                "owner_id": self.owner_id,
                "text": text,
                "type": type,
                "scope": scope,
                "importance": importance,
                "agent_id": "hermes",
            },
        ) or {}

    def close_session(self, session_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
        return self._request(
            "POST", f"/v1/sessions/{session_id}/close", {}, timeout=timeout
        ) or {}
