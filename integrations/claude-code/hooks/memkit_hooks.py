#!/usr/bin/env python3
"""Claude Code hooks for Mem OS: profile injection, capture, and reasoned recall.

Four subcommands, registered in ~/.claude/settings.json by
`memkit install-claude-code`:

    session-start   SessionStart: render the five profile blocks and print a
                    <mem-os-context> block (a SessionStart hook's stdout becomes
                    context). Also names the scope this session writes to.
    capture         Stop and PreCompact: post the transcript delta since the last
                    cursor as one idempotent evidence batch.
    session-end     SessionEnd: capture the final delta, then close the session so
                    the extraction tail runs server-side.
    recall          UserPromptSubmit: off by default. When on, decides cheaply
                    whether this prompt is worth a search and emits
                    hookSpecificOutput.additionalContext if it is.

Every path fails open: a dead or unconfigured service must never block the user's
session, so errors go to stderr and the exit code stays 0. Capture advances its
cursor only after every batch succeeds; `external_id` per turn (the transcript
line uuid, the same id `memkit import-claude-code` uses) makes any re-send
idempotent, so the hook and the bulk importer can coexist.

Two things are deliberately decided here rather than server-side. Which scope a
conversation belongs to comes from `.memkit.toml` at the repository root, because
only the client knows which checkout it is in. And whether a prompt deserves a
search is decided before the request is made, because a recall that fires on
every prompt is latency and noise the user will turn off, which costs more than
the recalls it would have got right.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
import tomllib
from pathlib import Path
from typing import Any, NamedTuple

try:
    from memkit import remote
except ImportError:  # pragma: no cover - a misinstalled hook must still exit 0
    remote = None  # type: ignore[assignment]

CAPTURE_TIMEOUT = 10.0
# A session close is the one moment the service may be slow: the session is over
# and a dropped tail is never extracted. Bounded so that a capture that used its
# whole budget plus a close still fits the 30s the installer registers for
# SessionEnd -- a hook killed by Claude Code mid-close leaves the tail exactly as
# unextracted as never calling it.
CLOSE_TIMEOUT = 15.0
# The SessionStart hook gets 5s from the installer, and it makes two calls; these
# two numbers plus interpreter startup have to fit inside that, or a hanging
# service turns into a hook Claude Code kills rather than one that fails open.
PROFILE_TIMEOUT = 3.0
ENTITY_TIMEOUT = 1.0
# decisions/0040 measured 75-93ms steady state for a local search over HTTP, and
# 0.4s as the budget that clears it without ever stalling a turn.
RECALL_TIMEOUT = 0.4
BATCH_LIMIT = 100
PROFILE_BUDGET = 550
# What the whole rendered block may cost, headings and bullets included. The
# server honours `budget_tokens` for the item text and knows nothing about the
# chrome around it, so without a cap on items the block's real size would be
# unbounded: a budget spent on many short facts buys many bullets, and each
# bullet costs tokens the budget never counted. Both numbers are asserted by
# tests/test_claude_code_integration.py against retrieval._token_count.
MAX_ITEMS_PER_BLOCK = 12
MAX_BLOCK_TOKENS = 800
RECALL_BUDGET = 200
RECALL_LIMIT = 3
# Below this a prompt is "ok", "continue", "да" -- there is no question in it.
MIN_RECALL_CHARS = 12
# Long enough that one GET serves a whole session, short enough that an entity
# created mid-session is picked up by the next one.
ENTITY_CACHE_TTL = 600.0
STATE_DIR = (
    Path(os.environ.get("XDG_STATE_HOME") or "~/.local/state").expanduser()
    / "memkit"
    / "claude-code"
)

CONFIG_NAME = ".memkit.toml"

SECTIONS = (
    ("about", "About you"),
    ("style", "How you like to work"),
    ("team", "Team rules"),
    ("project", "This project"),
    ("recent", "Recently"),
)
BLOCKS = [name for name, _ in SECTIONS]

# What Claude Code puts in `source` on SessionStart. Gated here rather than by a
# settings.json matcher because the hook is what knows which sources it can
# render, and a matcher that silently stops matching after an upgrade looks
# exactly like a service outage.
SESSION_START_SOURCES = frozenset({"startup", "resume", "clear", "compact", "fork"})

# Prompts that are asking memory a question, in the two languages this user
# works in. Deliberately narrow: a false positive costs a wrong injected fact
# and 0.4s on a turn that did not need it, and enough of those and recall gets
# switched off, which costs every true positive too.
RECALL_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bwhat (?:did|do) (?:we|you|i) (?:decide|choose|pick)\b",
        r"\bwhy (?:did|do|are|is) (?:we|you|i)\b",
        r"\bwe (?:decided|agreed|chose)\b",
        r"\blast time\b",
        r"\bthe decision\b",
        r"\bremind me\b",
        r"\bкак мы (?:решили|договорились)\b",
        r"\bмы (?:решили|договорились)\b",
        r"\bпочему мы\b",
        r"\bнапомни\b",
        r"\bв прошлый раз\b",
    )
)


class Repo(NamedTuple):
    """What this checkout says about where its conversations belong."""

    root: Path
    name: str
    entity: str | None
    capture: bool
    recall: bool


def _client(*, timeout: float = PROFILE_TIMEOUT) -> Any:
    return remote.connect(timeout=timeout)


def _hook_input() -> dict[str, Any]:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _state_key(session_id: str) -> str:
    """A session id reduced to something safe to put in a path.

    Claude Code sends uuids, but a state file name built from a value that
    arrived on stdin is a path traversal waiting for the one release that changes
    the format.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", session_id)[:128] or "unknown"


# ---------------------------------------------------------------------------
# Per-repository configuration
# ---------------------------------------------------------------------------


def repo_settings(cwd: Path | str) -> Repo:
    """Read `.memkit.toml`, walking up from `cwd` and stopping at the git root.

    Stopping there is the point. Without it a checkout below a home directory
    would inherit a stray ~/.memkit.toml and start filing one project's
    conversations into another project's scope -- a permissions mistake, not a
    configuration one, because scope is what decides who can read a fact.
    """
    start = Path(cwd).expanduser()
    with contextlib.suppress(OSError):
        start = start.resolve()
    section: dict[str, Any] = {}
    root = start
    for directory in (start, *start.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            root = directory
            section = _read_config(candidate)
            break
        if (directory / ".git").exists():
            root = directory
            break
    entity = section.get("entity")
    return Repo(
        root=root,
        name=root.name or start.name,
        entity=entity.strip() if isinstance(entity, str) and entity.strip() else None,
        capture=bool(section.get("capture", True)),
        recall=bool(section.get("recall", False)) or os.environ.get("MEMKIT_RECALL") == "1",
    )


def _read_config(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    section = data.get("memkit")
    return section if isinstance(section, dict) else {}


# ---------------------------------------------------------------------------
# Entities: one cached list serves scope resolution and the recall heuristic
# ---------------------------------------------------------------------------


def entity_cache(client: Any, session_id: str) -> list[dict[str, Any]]:
    """Every entity this key can see, cached per session on disk.

    One GET per session is affordable; one per turn is not, and both capture and
    recall need the same answer. A failure caches nothing and returns nothing,
    which degrades to a private scope and pattern-only recall -- both correct
    answers rather than wrong ones.
    """
    path = STATE_DIR / f"{_state_key(session_id)}.entities.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(cached["fetched_at"]) < ENTITY_CACHE_TTL:
            return list(cached["items"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        payload = client.get("/v1/entities", timeout=ENTITY_TIMEOUT) or {}
    except remote.RemoteError:
        return []
    items = [
        {
            "slug": str(item.get("slug") or ""),
            "name": str(item.get("name") or ""),
            "aliases": [str(alias) for alias in (item.get("aliases") or []) if alias],
            "writable": bool(item.get("writable")),
        }
        for item in (payload.get("items") or [])
        if item.get("slug")
    ]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError, TypeError):
        path.write_text(json.dumps({"fetched_at": time.time(), "items": items}), encoding="utf-8")
    return items


def resolve_scope(repo: Repo, entities: list[dict[str, Any]]) -> str | None:
    """The scope slug to stamp on this session's evidence, or None for private.

    Only a scope this key may actually write to is ever returned. The server
    answers 403 for a scope the caller does not hold and 404 for one that does
    not exist, and the batch is refused either way -- so a `.memkit.toml` naming
    a project the user has not been added to must degrade to private rather than
    lose the conversation.
    """
    writable = {entity["slug"] for entity in entities if entity["writable"]}
    if repo.entity:
        return repo.entity if repo.entity in writable else None
    # No `entity` line: fall back to the repository name as an alias, which is
    # what `memkit import-claude-code` does with the same transcripts. A hook
    # that skipped this would file live sessions somewhere other than the
    # backfill of the very same conversations.
    wanted = repo.name.casefold()
    for entity in entities:
        if not entity["writable"]:
            continue
        names = [entity["slug"], entity["name"], *entity["aliases"]]
        if any(name.casefold() == wanted for name in names):
            return entity["slug"]
    return None


# ---------------------------------------------------------------------------
# SessionStart
# ---------------------------------------------------------------------------


def session_start() -> None:
    hook = _hook_input()
    source = str(hook.get("source") or "startup")
    if source not in SESSION_START_SOURCES:
        # A source this hook has not been taught about is a newer Claude Code.
        # Printing into a context whose lifecycle we do not understand is worse
        # than printing nothing.
        return
    client = _client()
    if client is None:
        return
    repo = repo_settings(hook.get("cwd") or os.getcwd())
    profile = (
        client.post(
            "/v1/profiles/render",
            {
                "blocks": BLOCKS,
                "workspace": repo.name[:128],
                "budget_tokens": PROFILE_BUDGET,
            },
            timeout=PROFILE_TIMEOUT,
        )
        or {}
    )
    scope = resolve_scope(repo, entity_cache(client, str(hook.get("session_id") or "")))
    block = render_context(profile, repo, scope)
    if block:
        print(block)


def render_context(profile: dict[str, Any], repo: Repo, scope: str | None) -> str:
    """The <mem-os-context> block, or "" when there is nothing to say.

    A heading is printed only for a block that has items: an empty "Team rules:"
    heading teaches the model that the team has no rules, which is a claim the
    service never made.
    """
    blocks = profile.get("blocks") or {}
    body: list[str] = []
    for key, heading in SECTIONS:
        items = [item for item in (blocks.get(key) or []) if item.get("text")][:MAX_ITEMS_PER_BLOCK]
        if not items:
            continue
        if key == "project":
            heading = f"{heading}: {items[0].get('scope') or repo.name}"
        body.append(f"{heading}:")
        body.extend(f"- {item['text']}" for item in items)
    if not body:
        return ""
    return "\n".join(
        [
            "<mem-os-context>",
            "Long-term memory from Mem OS. Use it naturally; for anything deeper,",
            "search with the mem-os skill.",
            *body,
            _scope_line(repo, scope),
            "</mem-os-context>",
        ]
    )


def _scope_line(repo: Repo, scope: str | None) -> str:
    """Say where this session's facts land, because nothing else tells the model.

    Saving privately and saving to a shared scope are the same call with one
    field different, and the difference is who can read the result. An agent left
    to guess either over-shares or stops saving anything.
    """
    if not repo.capture:
        return "Scope: capture is off for this repository; nothing here is saved."
    if scope:
        return (
            f'Scope: facts from this session are saved to "{scope}", visible to '
            "everyone in it, and start unconfirmed in that team's review queue."
        )
    return "Scope: facts from this session are private to you."


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def events_from_delta(
    transcript: Path,
    cursor_file: Path,
    workspace: str,
    scope: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    from memkit.importers.claude_code import MAX_TURN_CHARS, classify

    offset = 0
    if cursor_file.is_file():
        try:
            offset = int(cursor_file.read_text().strip() or 0)
        except ValueError:
            offset = 0
    data = transcript.read_bytes()
    if offset > len(data):
        offset = 0  # transcript rewritten; idempotent ids make re-reads safe
    events: list[dict[str, Any]] = []
    for raw in data[offset:].splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        turn, _reason = classify(line)
        if turn is None:
            continue
        # classify() keeps full documents out already; assistant turns are
        # context only server-side, so cap them to keep batches small.
        text = turn.text if turn.role == "user" else turn.text[:2000]
        events.append(
            {
                "session_id": turn.session_id,
                "agent_id": "claude-code",
                "role": turn.role,
                "content": text[:MAX_TURN_CHARS],
                "external_source": "claude-code",
                "external_id": turn.external_id,
                "context": {"source_workspace": turn.project or workspace},
                **({"scope": scope} if scope else {}),
                **({"created_at": turn.created_at} if turn.created_at else {}),
            }
        )
    return events, len(data)


def capture(*, close: bool) -> None:
    hook = _hook_input()
    session_id = str(hook.get("session_id") or "")
    client = _client(timeout=CAPTURE_TIMEOUT)
    if client is None or not session_id:
        return
    repo = repo_settings(hook.get("cwd") or os.getcwd())
    transcript = Path(str(hook.get("transcript_path") or "")).expanduser()
    if repo.capture and str(transcript) and transcript.is_file():
        _flush(client, transcript, session_id, repo, Path(hook.get("cwd") or ".").name)
    if close:
        _close(client, session_id)


def _flush(client: Any, transcript: Path, session_id: str, repo: Repo, workspace: str) -> None:
    cursor_file = STATE_DIR / f"{_state_key(session_id)}.offset"
    scope = resolve_scope(repo, entity_cache(client, session_id))
    events, offset = events_from_delta(transcript, cursor_file, workspace, scope)
    for start in range(0, len(events), BATCH_LIMIT):
        _send(client, events[start : start + BATCH_LIMIT])
    # Only reached when every batch landed: a failed send keeps the old cursor
    # and the idempotency keys absorb the overlap on the next run.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cursor_file.write_text(str(offset))


def _send(client: Any, events: list[dict[str, Any]]) -> None:
    try:
        client.post("/v1/evidence/events:batch", {"events": events}, timeout=CAPTURE_TIMEOUT)
    except remote.RemoteError as exc:
        if exc.status not in (403, 404) or not any("scope" in event for event in events):
            raise
        # 403 means this key cannot write there; 404 means no such entity yet.
        # The batch is one server-side transaction, so nothing landed, and
        # resending it private keeps the turn instead of losing it to a typo in
        # `.memkit.toml`.
        private = [{k: v for k, v in event.items() if k != "scope"} for event in events]
        client.post("/v1/evidence/events:batch", {"events": private}, timeout=CAPTURE_TIMEOUT)


def _close(client: Any, session_id: str) -> None:
    """Force extraction of the tail.

    Attempted whenever the session ends, not only when this run had something to
    send. Stop fires after every response, so by SessionEnd the delta is usually
    empty -- and a hook that closed only after a successful send therefore never
    closed the sessions it had been capturing all along, leaving the last turns
    unextracted until some later job forced them. A 404 is the one honest case
    for skipping: nothing was ever stored under this id.
    """
    try:
        client.post(f"/v1/sessions/{session_id}/close", timeout=CLOSE_TIMEOUT)
    except remote.RemoteError as exc:
        if exc.status != 404:
            raise


# ---------------------------------------------------------------------------
# Optional recall
# ---------------------------------------------------------------------------


def recall_reason(prompt: str, aliases: set[str]) -> str:
    """Why this prompt is worth a search, or "" for the silent majority.

    Returns the reason rather than a bool because the reason is what makes the
    heuristic reviewable. Abstention is the default: most prompts are
    instructions, and answering them with three semi-related facts trains the
    user to ignore injected context.
    """
    text = prompt.strip()
    if len(text) < MIN_RECALL_CHARS or text.startswith("/"):
        return ""
    lowered = text.casefold()
    for pattern in RECALL_PATTERNS:
        if pattern.search(lowered):
            return "decision-phrase"
    words = set(re.findall(r"\w+", lowered))
    for alias in aliases:
        # A single word must match on a word boundary -- "mem" cannot be allowed
        # to fire on "remember" -- while a hyphenated or multi-word alias is
        # specific enough that a substring is safe.
        if (alias in words) if alias.isalnum() else (alias in lowered):
            return "alias"
    return ""


def _aliases(entities: list[dict[str, Any]]) -> set[str]:
    """Every name that could refer to an entity, case-folded.

    Names under three characters are dropped: an entity called "AI" would match
    half of every prompt, and firing on everything is the failure this heuristic
    exists to avoid.
    """
    names: set[str] = set()
    for entity in entities:
        for name in (entity["slug"], entity["name"], *entity["aliases"]):
            folded = name.casefold().strip()
            if len(folded) >= 3:
                names.add(folded)
    return names


def recall() -> None:
    hook = _hook_input()
    repo = repo_settings(hook.get("cwd") or os.getcwd())
    if not repo.recall:
        return
    client = _client(timeout=RECALL_TIMEOUT)
    if client is None:
        return
    session_id = str(hook.get("session_id") or "")
    prompt = str(hook.get("prompt") or "")
    if not recall_reason(prompt, _aliases(entity_cache(client, session_id))):
        return
    injected = _injected(session_id)
    payload = (
        client.post(
            "/v1/memories/search",
            {"query": prompt[:2000], "limit": RECALL_LIMIT, "budget_tokens": RECALL_BUDGET},
            timeout=RECALL_TIMEOUT,
        )
        or {}
    )
    fresh = [
        memory
        for memory in (payload.get("memories") or [])
        if memory.get("text") and str(memory.get("id")) not in injected
    ]
    if not fresh:
        return
    _remember_injected(session_id, [str(memory["id"]) for memory in fresh])
    lines = "\n".join(f"- {memory['text']}" for memory in fresh)
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": f"Possibly relevant memory (Mem OS):\n{lines}",
                }
            }
        )
    )


def _injected(session_id: str) -> set[str]:
    """Memory ids already put in front of the model this session.

    Repeating a fact the model has already been given is pure cost: it spends
    the budget, and it reads as new information about the same thing.
    """
    path = STATE_DIR / f"{_state_key(session_id)}.recalled"
    try:
        return {line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line}
    except OSError:
        return set()


def _remember_injected(session_id: str, ids: list[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"{_state_key(session_id)}.recalled"
    with contextlib.suppress(OSError), path.open("a", encoding="utf-8") as handle:
        handle.write("".join(f"{memory_id}\n" for memory_id in ids))


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if remote is None:
        print("memkit hook: memkit is not importable by this interpreter", file=sys.stderr)
        return 0
    try:
        if command == "session-start":
            session_start()
        elif command == "capture":
            capture(close=False)
        elif command == "session-end":
            capture(close=True)
        elif command == "recall":
            recall()
        else:
            print(f"unknown memkit hook command: {command!r}", file=sys.stderr)
    except Exception as exc:  # fail open, always
        print(f"memkit hook {command} failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
