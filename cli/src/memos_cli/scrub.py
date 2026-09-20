"""Redact secrets before anything leaves for the memory service.

The judge behind that service is a cloud API, and a coding agent routinely sees
`.env` files, `git remote -v` output and tokens in logs. So the first line of
defence is structural, not textual: `send_tool_results` defaults to false and tool
messages are never forwarded at all (see the provider). These patterns are the
second line, for the user turns that do get sent.

Regexes always miss something. They are here to catch the shapes that are cheap to
recognise, not to make forwarding tool output safe.
"""

from __future__ import annotations

import re

PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\b(sk|pk)-[A-Za-z0-9_\-]{20,}", "[KEY]"),
    (r"\bAKIA[0-9A-Z]{16}\b", "[AWS_KEY]"),
    (r"\bghp_[A-Za-z0-9]{36}\b", "[GH_TOKEN]"),
    (r"\bgh[pousr]_[A-Za-z0-9]{36,}\b", "[GH_TOKEN]"),
    (r"\bAIza[0-9A-Za-z_\-]{35}\b", "[GOOGLE_KEY]"),
    (
        r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}",
        "[JWT]",
    ),
    (r"(?i)(bearer|authorization:)\s+\S+", r"\1 [REDACTED]"),
    # Any `NAME=value` whose name looks like a credential, anywhere in the text --
    # not just at the start of a line. The line-anchored version this replaces
    # passed a unit test that put the key on its own line and then leaked a key
    # pasted mid-sentence ("вот ключ AWS_SECRET_ACCESS_KEY=...") on the first live
    # run of the docs/07 checklist. Only the value is replaced, so a sentence
    # containing one stays readable.
    (
        (
            r"(?i)\b(\w*(?:secret|token|password|passwd|api[_-]?key|credential"
            r"|private[_-]?key|access[_-]?key)\w*)\s*[=:]\s*\S+"
        ),
        r"\1=[REDACTED]",
    ),
    (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "[PRIVATE_KEY]",
    ),
    # user:password@host in a connection string
    (r"://[^:/\s]+:[^@/\s]+@", "://[CRED]@"),
]

_COMPILED = [(re.compile(pattern), repl) for pattern, repl in PATTERNS]


def scrub(text: str) -> str:
    if not text:
        return text
    for pattern, repl in _COMPILED:
        text = pattern.sub(repl, text)
    return text
