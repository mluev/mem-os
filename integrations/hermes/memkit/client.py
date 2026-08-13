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
import urllib.parse
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
        """
        return (
            self._request(
                "POST",
                "/v1/memories",
                {
                    "text": text,
                    "kind": kind,
                    "context": context or {},
                    "tags": [],
                    "importance": importance,
                    "confidence": 0.9,
                    "agent_id": "hermes",
                    "source_role": source_role,
                },
            )
            or {}
        )

    def close_session(self, session_id: str, *, timeout: float = 30.0) -> dict[str, Any]:
        return self._request("POST", f"/v1/sessions/{session_id}/close", {}, timeout=timeout) or {}
