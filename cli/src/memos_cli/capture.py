"""Bounded transcript deltas; never load an entire agent transcript into RAM."""

import json
from pathlib import Path

from .claude_classifier import MAX_TURN_CHARS, classify
from .scrub import scrub

MAX_DELTA_BYTES = 512 * 1024
MAX_EVENTS = 100


def events_from_delta(transcript, cursor_file, workspace, scope=None):
    transcript, cursor_file = Path(transcript), Path(cursor_file)
    try:
        offset = max(0, int(cursor_file.read_text().strip()))
    except (OSError, ValueError):
        offset = 0
    if offset > transcript.stat().st_size:
        offset = 0
    consumed, scanned, events = offset, 0, []
    with transcript.open("rb") as stream:
        # A cursor inside a line means a previous run skipped a giant tool or
        # document record. Continue discarding it without parsing its fragments.
        discarding = False
        if offset:
            stream.seek(offset - 1)
            discarding = stream.read(1) != b"\n"
        stream.seek(offset)
        while scanned < MAX_DELTA_BYTES and len(events) < MAX_EVENTS:
            raw = stream.readline(MAX_DELTA_BYTES - scanned)
            if not raw:
                break
            scanned += len(raw)
            if discarding:
                consumed += len(raw)
                discarding = not raw.endswith(b"\n")
                continue
            if not raw.endswith(b"\n"):
                if len(raw) == MAX_DELTA_BYTES:
                    consumed += len(raw)
                break  # preserve ordinary incomplete lines for the next event
            consumed += len(raw)
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(line, dict):
                continue
            turn, _reason = classify(line)
            if turn is None:
                continue
            text = turn.text if turn.role == "user" else turn.text[:2000]
            events.append(
                {
                    "session_id": turn.session_id,
                    "agent_id": "claude-code",
                    "role": turn.role,
                    "content": scrub(text[:MAX_TURN_CHARS]),
                    "external_source": "claude-code",
                    "external_id": turn.external_id,
                    "context": {"source_workspace": turn.project or workspace},
                    **({"scope": scope} if scope else {}),
                    **({"created_at": turn.created_at} if turn.created_at else {}),
                }
            )
    return events, consumed
