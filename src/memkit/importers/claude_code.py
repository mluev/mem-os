"""Compatibility imports for the shared Claude transcript classifier."""

from ..claude_classifier import (
    EXCLUDED_SOURCES,
    MAX_TURN_CHARS,
    MIN_INDEX_CHARS,
    NOISE_PATTERNS,
    ImportStats,
    Turn,
    classify,
    extract_text,
    iter_turns,
)

__all__ = [
    "EXCLUDED_SOURCES",
    "MAX_TURN_CHARS",
    "MIN_INDEX_CHARS",
    "NOISE_PATTERNS",
    "ImportStats",
    "Turn",
    "classify",
    "extract_text",
    "iter_turns",
]
