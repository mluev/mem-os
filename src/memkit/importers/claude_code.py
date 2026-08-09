"""Import Claude Code transcripts from ``~/.claude/projects/*.jsonl``.

Classification is the whole job here. A transcript line whose ``type`` is
``user`` is very often not the user: of 724 text-bearing user lines measured on
this machine, 421 were tool results, 75 were interrupt markers, 57 were slash
commands and 51 were local command output. Feeding any of that to the extractor
produces confident "facts about the user" that are nothing of the kind -- the
exact failure docs/04-judge.md warns about.

What the ``promptSource`` field actually means, measured rather than assumed:

===============  =====  ====================================================
promptSource     count  what it is
===============  =====  ====================================================
``sdk``            419  Claude Desktop human input (entrypoint
                        ``claude-desktop``, userType ``external``), with
                        injected ``<task-notification>`` blocks mixed in
absent             211  overwhelmingly machine noise, but ~20 real turns
``typed``           58  terminal human input
``system``          31  injected system text
``queued``           6  human, queued while the agent was busy
===============  =====  ====================================================

So neither "trust promptSource" nor "drop everything unlabeled" is correct.
Both a source check and a content check are required.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..limits import MIN_INDEX_CHARS

# Structural noise. Each of these is machine-authored text that arrives on a
# line whose role is "user". Anchored where the marker only ever appears at the
# start, substring-matched where it can be embedded.
NOISE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("interrupt-marker", re.compile(r"^\[Request interrupted")),
    ("slash-command", re.compile(r"<command-(name|message|args)>")),
    # Custom slash commands expand into their own tag rather than the
    # <command-name> wrapper, e.g. <create-pr-command>. Only one such turn
    # exists in the corpus today, but the set grows every time a command is
    # added, so match the shape instead of enumerating names.
    ("custom-slash-command", re.compile(r"^\s*<[a-zA-Z0-9_-]+-command>")),
    ("command-output", re.compile(r"<local-command-(stdout|stderr)>")),
    ("bash-io", re.compile(r"<bash-(input|stdout|stderr)>")),
    ("task-notification", re.compile(r"<task-notification>")),
    ("system-reminder", re.compile(r"^\s*<system-reminder>")),
    # Written by the compactor, not the user.
    ("compaction-summary", re.compile(r"^This session is being continued from")),
    # Prompts this agent authored for its own subagents.
    ("agent-brief", re.compile(r"^#\s*Peer brief")),
]

# promptSource values that are never the human speaking.
EXCLUDED_SOURCES = {"system"}

# Turns shorter than this are real but carry no memory value ("continue",
# "go on", "hello"). They are still stored in SQLite so that extraction windows
# read faithfully, but they are not worth indexing on their own.
#
# A turn this long is a pasted or injected document, not something anybody
# typed. Measured on this corpus: 386 labelled human turns run p50=130,
# p99=10242, max=17989 characters, with none above 20k. The only lines above
# the cutoff were three copies of a plan document at 78k, 86k and 129k chars --
# together 63% of all user text, enough to dominate the corpus on their own.
# docs/01-architecture.md excludes documents from memory by design, and BGE-M3
# would truncate them to a meaningless prefix regardless.
MAX_TURN_CHARS = 20_000


@dataclass
class Turn:
    """One human- or assistant-authored message worth persisting."""

    external_id: str  # the transcript line uuid; a real stable id
    session_id: str
    role: str
    text: str
    created_at: str
    project: str | None
    git_branch: str | None
    indexable: bool


@dataclass
class ImportStats:
    kept: Counter[str] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    files: int = 0
    lines: int = 0

    def render(self) -> str:
        lines = [f"files={self.files} lines={self.lines}", "  kept:"]
        for reason, n in self.kept.most_common():
            lines.append(f"    {reason:<28} {n:>6}")
        lines.append("  skipped:")
        for reason, n in self.skipped.most_common():
            lines.append(f"    {reason:<28} {n:>6}")
        return "\n".join(lines)


def extract_text(content: Any) -> str:
    """Pull human-readable text out of a message body.

    Deliberately ignores ``tool_use``, ``tool_result`` and ``thinking`` blocks:
    tool traffic carries file contents, command output and credentials, and the
    judge is a cloud API.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()
    return ""


def classify(line: dict[str, Any]) -> tuple[Turn | None, str]:
    """Decide whether a transcript line is a real turn worth keeping.

    Returns ``(turn, reason)``. ``turn`` is None when the line is rejected, and
    ``reason`` always explains the decision so the importer can report a
    per-bucket breakdown rather than a single opaque total.
    """
    ltype = line.get("type")
    if ltype not in ("user", "assistant"):
        return None, f"type:{ltype}"

    # Subagent traffic belongs to the agent's own reasoning, not the user's
    # history. isMeta lines are injected bookkeeping.
    if line.get("isSidechain"):
        return None, "sidechain"
    if line.get("isMeta"):
        return None, "meta"

    message = line.get("message") or {}
    content = message.get("content")

    # A user line carrying tool_result blocks is the harness replying to
    # itself. Detect it before text extraction so it reports distinctly.
    if isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    ):
        return None, "tool_result"

    text = extract_text(content)
    if not text:
        return None, "no-text"

    if len(text) > MAX_TURN_CHARS:
        return None, "oversized-document"

    if ltype == "user":
        source = line.get("promptSource")
        if source in EXCLUDED_SOURCES:
            return None, f"source:{source}"
        for label, pattern in NOISE_PATTERNS:
            if pattern.search(text):
                return None, label

    uuid = line.get("uuid")
    session_id = line.get("sessionId")
    if not uuid or not session_id:
        return None, "missing-ids"

    cwd = line.get("cwd")
    return (
        Turn(
            external_id=uuid,
            session_id=session_id,
            role=ltype,
            text=text,
            created_at=line.get("timestamp") or "",
            project=Path(cwd).name if cwd else None,
            git_branch=line.get("gitBranch") or None,
            indexable=ltype == "user" and len(text) >= MIN_INDEX_CHARS,
        ),
        # Normalised: the key is absent on some lines and explicitly null on
        # others, and both must report under the same label.
        f"{ltype}:{line.get('promptSource') or 'n/a'}" if ltype == "user" else "assistant",
    )


def iter_turns(root: Path, stats: ImportStats) -> list[Turn]:
    """Classify every transcript under ``root``, newest sessions last."""
    turns: list[Turn] = []
    for path in sorted(root.rglob("*.jsonl")):
        stats.files += 1
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                stats.lines += 1
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    stats.skipped["bad-json"] += 1
                    continue
                turn, reason = classify(line)
                if turn is None:
                    stats.skipped[reason] += 1
                else:
                    stats.kept[reason] += 1
                    turns.append(turn)
    # Chronological order across all sessions: extraction windows in stage 2
    # need turns in the order they were actually spoken.
    turns.sort(key=lambda t: (t.created_at, t.external_id))
    return turns
