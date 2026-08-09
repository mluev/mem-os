"""Central redaction applied before persistence and provider egress."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?i)\b(sk|pk)-[A-Za-z0-9_\-]{20,}", "[KEY]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[AWS_KEY]"),
    (r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "[GH_TOKEN]"),
    (r"\bAIza[0-9A-Za-z_\-]{35}\b", "[GOOGLE_KEY]"),
    (
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
        "[JWT]",
    ),
    (r"(?i)(bearer|authorization:)\s+\S+", r"\1 [REDACTED]"),
    (
        r"(?i)\b(\w*(?:secret|token|password|passwd|api[_-]?key|credential"
        r"|private[_-]?key|access[_-]?key)\w*)\s*[=:]\s*\S+",
        r"\1=[REDACTED]",
    ),
    (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "[PRIVATE_KEY]",
    ),
    (r"://[^:/\s]+:[^@/\s]+@", "://[CRED]@"),
)

_COMPILED = tuple((re.compile(pattern), replacement) for pattern, replacement in PATTERNS)
_SENSITIVE_KEY = re.compile(
    r"(?i)(secret|token|password|passwd|api[_-]?key|credential|private[_-]?key|access[_-]?key|authorization)"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted: bool
    count: int


def redact(text: str) -> RedactionResult:
    """Return scrubbed text without retaining any removed value."""
    cleaned = text
    count = 0
    for pattern, replacement in _COMPILED:
        cleaned, matches = pattern.subn(replacement, cleaned)
        count += matches
    return RedactionResult(cleaned, count > 0, count)


def redact_value(value: Any) -> tuple[Any, int]:
    """Recursively scrub every string in JSON-compatible input."""
    if isinstance(value, str):
        result = redact(value)
        return result.text, result.count
    if isinstance(value, list):
        cleaned: list[Any] = []
        count = 0
        for item in value:
            next_item, matches = redact_value(item)
            cleaned.append(next_item)
            count += matches
        return cleaned, count
    if isinstance(value, dict):
        cleaned_object: dict[str, Any] = {}
        count = 0
        for key, item in value.items():
            clean_key_result = redact(str(key))
            if _SENSITIVE_KEY.search(str(key)) and isinstance(item, str) and item:
                next_item, matches = "[REDACTED]", 1
            else:
                next_item, matches = redact_value(item)
            cleaned_object[clean_key_result.text] = next_item
            count += matches + clean_key_result.count
        return cleaned_object, count
    return value, 0
