"""Bounded HTTP transport shared by commands and agent adapters."""

import json
import math
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .errors import ClientError
from .scrub import scrub

MAX_BODY = 2 * 1024 * 1024


def protocol_error():
    return ClientError(
        "Server returned an unexpected response; check the server version.",
        code="protocol",
        exit_code=7,
    )


def object_response(value):
    if not isinstance(value, dict):
        raise protocol_error()
    return value


def validate_url(url):
    parsed = urlsplit(url or "")
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ClientError("Use a hosted HTTPS URL or an HTTP loopback SSH tunnel.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ClientError("Remote connections require HTTPS. Use an SSH tunnel for HTTP services.")
    if parsed.query or parsed.fragment:
        raise ClientError("The server URL must not contain query parameters or a fragment.")
    return url.rstrip("/")


class Client:
    def __init__(self, url, key="", *, timeout=15, transport=None):
        if not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ClientError("--timeout must be finite, greater than zero and at most 300 seconds")
        self.url = validate_url(url)
        self.key = key or ""
        self.timeout = timeout
        self.http = httpx.Client(
            base_url=self.url + "/",
            timeout=timeout,
            follow_redirects=False,
            headers={"X-API-Key": self.key} if self.key else {},
            transport=transport,
        )

    def close(self):
        self.http.close()

    def request(self, method, path, body=None, params=None, *, timeout=None, output=None):
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ClientError("API paths must be relative to the configured server.")
        if body is not None and not isinstance(body, dict):
            raise ClientError("Request body must be a JSON object")
        data = (
            json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            if body is not None
            else None
        )
        if data is not None and len(data) > MAX_BODY:
            raise ClientError("Request exceeds 2 MB; split evidence into smaller batches.")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        if self.http.cookies and method not in {"GET", "HEAD"}:
            headers["X-Requested-With"] = "memkit"
        try:
            with self.http.stream(
                method,
                path.lstrip("/"),
                content=data,
                params=params,
                headers=headers,
                timeout=timeout or self.timeout,
            ) as response:
                if response.is_error or response.is_redirect:
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=1024):
                        raw.extend(chunk[: 8192 - len(raw)])
                        if len(raw) >= 8192:
                            break
                    try:
                        detail = json.loads(raw).get("detail", "Request failed")
                    except (ValueError, AttributeError):
                        detail = "Server returned an unexpected response"
                    if isinstance(detail, list):
                        # Validation errors contain an `input` field that may be
                        # a password or a whole sensitive payload. Never echo it.
                        detail = "; ".join(
                            ".".join(map(str, item.get("loc", [])))
                            + ": "
                            + str(item.get("msg", "invalid"))
                            for item in detail
                            if isinstance(item, dict) and isinstance(item.get("loc", []), list)
                        )
                    status = response.status_code
                    code, exit_code = {
                        401: ("authentication", 3),
                        403: ("forbidden", 4),
                        404: ("not_found", 5),
                        409: ("conflict", 6),
                        429: ("rate_limited", 7),
                    }.get(status, ("server_error", 7) if status >= 500 else ("invalid_input", 2))
                    message = f"HTTP {status}: {detail}"
                    if self.key:
                        message = message.replace(self.key, "[REDACTED]")
                    for name, value in (body or {}).items():
                        if (
                            any(
                                word in name.lower()
                                for word in ("password", "secret", "token", "key")
                            )
                            and isinstance(value, str)
                            and value
                        ):
                            message = message.replace(value, "[REDACTED]")
                    message = scrub(message)
                    if status == 401:
                        message += "; run memos setup to renew your login"
                    raise ClientError(message, code=code, exit_code=exit_code, status=status)
                if output:
                    import os
                    import tempfile

                    target = Path(output).expanduser()
                    target.parent.mkdir(parents=True, exist_ok=True)
                    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=".memos-download-")
                    try:
                        with os.fdopen(fd, "wb") as stream:
                            for chunk in response.iter_bytes():
                                stream.write(chunk)
                        os.replace(temporary, target)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                    return {"path": str(target.resolve()), "bytes": target.stat().st_size}
                payload = response.read()
                return object_response(json.loads(payload)) if payload else {}
        except httpx.TimeoutException as exc:
            raise ClientError(
                "Mem OS timed out; check memos status. Writes were not retried.",
                code="timeout",
                exit_code=8,
            ) from exc
        except httpx.HTTPError as exc:
            raise ClientError(
                "Cannot connect to Mem OS; check memos status or memos server tunnel.",
                code="unavailable",
                exit_code=7,
            ) from exc
        except ValueError as exc:
            raise ClientError(
                "Server returned invalid JSON; check the URL and server version.",
                code="protocol",
                exit_code=7,
            ) from exc

    def get(self, path, params=None, *, timeout=None):
        return self.request("GET", path, params=params, timeout=timeout)

    def post(self, path, body=None, *, timeout=None):
        return self.request("POST", path, body or {}, timeout=timeout)

    def wait(self, job_id, seconds=60):
        if not math.isfinite(seconds) or not 0 <= seconds <= 3600:
            raise ClientError("--wait must be finite and between 0 and 3600 seconds")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = self.get(
                f"/v1/jobs/{job_id}",
                timeout=max(0.1, min(self.timeout, deadline - time.monotonic())),
            )
            job = object_response(result.get("job", result))
            if not isinstance(job.get("status"), str):
                raise protocol_error()
            if job.get("status") in {"complete", "failed", "cancelled"}:
                if job["status"] in {"failed", "cancelled"}:
                    raise ClientError(
                        f"Job {job_id} {job['status']}; use memos jobs get {job_id}.",
                        code="job_failed",
                        exit_code=9,
                    )
                return result
            time.sleep(min(1, max(0, deadline - time.monotonic())))
        raise ClientError(
            f"Job {job_id} is still running; use memos jobs get {job_id}.",
            code="timeout",
            exit_code=8,
        )
