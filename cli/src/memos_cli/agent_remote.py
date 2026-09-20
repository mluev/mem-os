"""The legacy hook interface backed by the standalone client's transport."""

import hashlib

from .claude_classifier import MAX_TURN_CHARS, classify
from .config import resolve
from .connection import open_connection
from .errors import ClientError
from .scrub import scrub

RemoteError = ClientError
RECALL_DEFAULT = True
__all__ = ["MAX_TURN_CHARS", "RemoteError", "classify", "connect", "namespace", "scrub"]


def connect(*, timeout=3):
    settings = resolve()
    if not settings.get("url") or not settings.get("key"):
        return None
    return open_connection(settings, timeout=timeout)


def namespace():
    settings = resolve()
    value = str(settings.get("url")) + "\0" + str(settings.get("key"))
    return hashlib.sha256(value.encode()).hexdigest()[:24]
