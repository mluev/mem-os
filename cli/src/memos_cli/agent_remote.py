"""The legacy hook interface backed by the standalone client's transport."""

import hashlib

from .config import resolve
from .connection import open_connection
from .errors import ClientError

RemoteError = ClientError


def connect(*, timeout=3):
    settings = resolve()
    if not settings.get("url") or not settings.get("key"):
        return None
    return open_connection(settings, timeout=timeout)


def namespace():
    settings = resolve()
    value = str(settings.get("url")) + "\0" + str(settings.get("key"))
    return hashlib.sha256(value.encode()).hexdigest()[:24]
