"""Compatibility imports for the shared bounded Claude transcript reader."""

from .claude_hooks import MAX_DELTA_BYTES, MAX_EVENTS, events_from_delta

__all__ = ["MAX_DELTA_BYTES", "MAX_EVENTS", "events_from_delta"]
