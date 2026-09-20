"""One connection path for public commands, authenticated commands, and hooks."""

from .client import Client, validate_url
from .errors import ClientError


def open_connection(saved, *, timeout=15, authenticated=True, factory=Client):
    if not saved.get("url") or (authenticated and not saved.get("key")):
        raise ClientError(
            "No hosted connection configured; run memos setup.", code="authentication", exit_code=3
        )
    validate_url(saved["url"])
    server = saved.get("server", {})
    if server.get("tunnel"):
        from .server import ensure_tunnel

        ensure_tunnel(server)
    return factory(saved["url"], saved.get("key", "") if authenticated else "", timeout=timeout)
