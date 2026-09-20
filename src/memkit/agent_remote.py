"""Legacy hook runtime, retaining the server client's credentials and defaults."""

from .claude_classifier import MAX_TURN_CHARS, classify
from .remote import RemoteError, connect
from .security import redact

__all__ = ["MAX_TURN_CHARS", "RemoteError", "classify", "connect", "scrub"]


def scrub(text: str) -> str:
    return redact(text).text
