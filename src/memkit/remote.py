"""Stdlib-only HTTP client for the memkit service, shared by every thin client.

It lives in `memkit` so the Claude Code hooks can import it, and it imports
nothing else from the package on purpose: `memkit.api` reaches
sentence-transformers and therefore torch, and a hook that paid that import cost
would spend its whole five-second budget before its first request.

The breaker is the one measured for the Hermes adapter (see
integrations/hermes/memkit/client.py). What it buys a short-lived hook process is
narrower than what it buys a long-running agent -- state dies with the process --
but a session end against a dead service makes several calls, and one timeout
instead of one per batch plus the close is the difference between a hook nobody
notices and one that adds half a minute to closing an editor.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8077"

# Where `memkit install-claude-code` and `memkit api-keys create` tell people to
# put their key, and the pre-team location some installs still have.
CLIENT_ENV = Path("~/.config/memkit/client.env").expanduser()
LEGACY_ENV = Path("~/.memkit").expanduser()

_legacy_reported = False


class RemoteError(RuntimeError):
    """A request produced no usable answer. `status` is set for HTTP errors only."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


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


def _report_legacy() -> None:
    """Name the deprecated file once per process, on stderr.

    There is no instance-wide key any more, so a client reading the wrong file
    does not get a degraded answer -- it gets nobody's memory. That makes the
    moment a deprecated file is actually used worth one line, even though
    `memkit doctor` reports it too: doctor is what people run after something has
    already gone wrong. Once per process, because a single hook run resolves
    config more than once and three identical lines read as a fault.
    """
    global _legacy_reported
    if _legacy_reported:
        return
    _legacy_reported = True
    print(
        f"memkit: {LEGACY_ENV} is deprecated; move MEMKIT_BASE_URL and "
        f"MEMKIT_API_KEY into {CLIENT_ENV}",
        file=sys.stderr,
    )


def resolve_config() -> tuple[str, str]:
    """The service URL and this caller's own key, by falling precedence.

    One resolution order defined once, rather than one per integration: the key
    *is* the identity now, so two clients that disagree about where to look do
    not disagree about a setting, they disagree about who is asking.
    """
    base = os.environ.get("MEMKIT_BASE_URL", "").strip()
    key = os.environ.get("MEMKIT_API_KEY", "").strip()
    for path in (CLIENT_ENV, LEGACY_ENV):
        if base and key:
            break
        values = _read_env_file(path)
        used = False
        if not base and values.get("MEMKIT_BASE_URL"):
            base, used = values["MEMKIT_BASE_URL"], True
        if not key and values.get("MEMKIT_API_KEY"):
            key, used = values["MEMKIT_API_KEY"], True
        if used and path == LEGACY_ENV:
            _report_legacy()
    return (base or DEFAULT_BASE_URL).rstrip("/"), key


class Breaker:
    """Five consecutive failures, then two minutes off.

    Shape and numbers from the Hermes adapter, where they were measured. Only
    network errors and 5xx count: a 403 on a scope the caller cannot write to is
    the service answering, and treating a config typo as an outage would silence
    memory for two minutes over something a retry could fix immediately.
    """

    def __init__(self, fails: int = 5, cooldown: float = 120.0) -> None:
        self.fails = fails
        self.cooldown = cooldown
        self._n = 0
        self._until = 0.0

    def allow(self) -> bool:
        return time.monotonic() >= self._until

    def ok(self) -> None:
        self._n = 0

    def fail(self) -> None:
        self._n += 1
        if self._n >= self.fails:
            self._until = time.monotonic() + self.cooldown
            self._n = 0


class Client:
    """JSON over HTTP, with the timeout given per call rather than per client.

    The calls differ by two orders of magnitude in what they may cost: a
    per-prompt recall has 0.4s (decisions/0040), a profile render has a few
    seconds, and a session close is allowed half a minute because a dropped tail
    is never extracted. One client-wide timeout cannot serve all three.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 3.0,
        breaker: Breaker | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an http(s) URL")
        self.api_key = api_key
        self.timeout = timeout
        self.breaker = breaker or Breaker()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        return self._request("GET", path + query, None, timeout)

    def post(
        self,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        return self._request("POST", path, {} if body is None else body, timeout)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        timeout: float | None,
    ) -> Any:
        if not self.breaker.allow():
            raise RemoteError("circuit open")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(  # noqa: S310 -- scheme validated in __init__
            self.base_url + path, data=data, method=method
        )
        request.add_header("X-API-Key", self.api_key)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(  # noqa: S310 -- validated URL
                request, timeout=timeout or self.timeout
            ) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code >= 500:
                self.breaker.fail()
            raise RemoteError(f"http {exc.code}", status=exc.code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.breaker.fail()
            raise RemoteError(str(exc)) from exc
        self.breaker.ok()
        try:
            return json.loads(payload) if payload else {}
        except ValueError as exc:
            # A body that is not JSON means a broken peer -- a proxy's HTML error
            # page, say -- not a transport failure, so it must not count toward
            # opening the breaker against the service behind that proxy.
            raise RemoteError("response was not JSON") from exc


def connect(*, timeout: float = 3.0) -> Client | None:
    """A configured client, or None when this machine has no key.

    None rather than an exception because every caller treats a missing key the
    same way -- memory is not set up here, carry on without it -- and making
    them each catch for that would be four copies of the same `except`.
    """
    base, key = resolve_config()
    if not key:
        return None
    try:
        return Client(base, key, timeout=timeout)
    except ValueError:
        return None
