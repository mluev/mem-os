"""Hermes memory provider for Mem OS, installed by either supported CLI.

The provider speaks HTTP directly for legacy installations or uses the saved
memos connection through bridge.json. Both packages ship this source unchanged.
Writes are private unless a scope is configured. Non-primary agent contexts do
not write; tool output is excluded by default; session close waits for evidence.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from agent.memory_provider import MemoryProvider

from .client import PROFILE_BLOCKS, Client, MemkitError, resolve_config
from .scrub import scrub

logger = logging.getLogger(__name__)
SESSION_CLOSE_TIMEOUT = 30.0

_LAST = "__last__"
_HELPFUL_MEMORY = re.compile(
    r"(?i)\b(memory|remembered|recalled|recall)\b.{0,50}\b(helpful|right|correct|useful)\b"
)
_WRONG_MEMORY = re.compile(
    r"(?i)\b(memory|remembered|recalled|recall)\b.{0,50}\b(wrong|incorrect|false|outdated)\b"
)

MEMKIT_SEARCH = {
    "name": "memkit_search",
    "description": (
        "Search long-term memory. Use when you "
        "need a preference, a past decision, or a fact about the user that is not "
        "already in the injected context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for."},
            "context_key": {
                "type": "string",
                "description": "Optional neutral context field to match.",
            },
            "context_value": {
                "type": "string",
                "description": "Value for context_key.",
            },
        },
        "required": ["query"],
    },
}

MEMKIT_REMEMBER = {
    "name": "memkit_remember",
    "description": (
        "Store a fact the user explicitly asked you to remember. Goes straight in, "
        "bypassing the extraction judge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The fact, self-contained, under 200 characters.",
            },
            "kind": {
                "type": "string",
                "description": "Free-form memory kind, for example preference or fact.",
            },
        },
        "required": ["text"],
    },
}


def _config() -> dict[str, Any]:
    try:
        from hermes_cli.config import cfg_get, load_config

        return cfg_get(load_config(), "plugins", "memkit", default={}) or {}
    except Exception:
        return {}


class MemkitProvider(MemoryProvider):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config if config is not None else _config()
        self._client: Client | None = None
        self._session_id = ""
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._last_retrieval: dict[str, Any] | None = None
        self._threads: list[threading.Thread] = []
        self._session_writes: dict[str, list[threading.Thread]] = {}
        self._failed_sessions: set[str] = set()
        self._lock = threading.Lock()
        self._budget = int(self._config.get("budget_tokens", 800) or 800)
        self._send_tool_results = bool(self._config.get("send_tool_results", False))
        # Measured against the running service: the first request costs ~840ms
        # (connection setup plus server-side warm), every one after it 75-93ms.
        # docs/07 budgeted 0.15s from "BGE-M3 30ms + Qdrant 10ms", which is the
        # in-process cost and not what HTTP delivers. 0.4s clears steady state with
        # room to spare and still cannot stall a turn; the cold call is handled by
        # the warm-up in initialize() instead of by a longer timeout.
        self._prefetch_timeout = float(self._config.get("prefetch_timeout", 0.4) or 0.4)
        # Set here as well as in initialize(): `backup_paths` and `is_available` are
        # documented as callable before initialize, and a half-built provider must
        # fail closed on writes rather than raise AttributeError.
        self._read_only = False

    # -- identity ----------------------------------------------------------

    @property
    def name(self) -> str:
        return "memkit"

    def is_available(self) -> bool:
        """Config only — the ABC forbids network calls here.

        Whether the service is actually up is decided per call by the circuit
        breaker, because it can go down after this returns True.
        """
        return bool(self._base_url() and self._api_key())

    def _base_url(self) -> str:
        return str(self._config.get("base_url") or resolve_config()[0])

    def _api_key(self) -> str:
        """This person's key: an explicit file if configured, else the shared order.

        `api_key_file` still wins when set, because a fresh Hermes process may
        have no environment at all and a 0600 file is the only thing it can read.
        Everything else defers to `client.resolve_config`, so the plugin, the
        hooks and the CLI cannot disagree about whose key is in play.
        """
        key_file = self._config.get("api_key_file")
        if key_file:
            try:
                path = Path(str(key_file)).expanduser()
                if path.stat().st_mode & 0o077:
                    logger.warning("memkit: API key file permissions must be 0600")
                    return ""
                value = path.read_text(encoding="utf-8").strip()
                return value if len(value) >= 32 else ""
            except OSError:
                logger.warning("memkit: API key file is unavailable")
                return ""
        env_var = self._config.get("api_key_env")
        if env_var:
            return os.environ.get(str(env_var), "")
        return resolve_config()[1]

    def _scope(self) -> str:
        """The shared scope writes land in, or "" for this user's private space."""
        return str(self._config.get("scope") or "").strip()

    # -- lifecycle ---------------------------------------------------------

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id or ""
        self._client = Client(
            self._base_url(),
            self._api_key(),
        )
        # Non-primary contexts must not write: a cron system prompt or a subagent's
        # scratch reasoning is not the user talking, and the ABC says so explicitly.
        self._read_only = kwargs.get("agent_context", "primary") != "primary"
        if self._read_only:
            logger.info("memkit: %s context, writes disabled", kwargs.get("agent_context"))
        # Pay the ~840ms cold call here, in the background, rather than letting the
        # first turn's prefetch eat its timeout and silently return no memory.
        self._spawn(self._warm, "")

    def shutdown(self) -> None:
        deadline = time.monotonic() + 5.0
        for thread in list(self._threads):
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            self._threads = [thread for thread in self._threads if thread.is_alive()]

    def _spawn(self, target: Any, *args: Any, session_id: str | None = None) -> None:
        """Run a write off the turn's critical path.

        Daemon threads so a hung request cannot keep the agent alive, but tracked so
        `shutdown` can wait for them -- a turn's last message must not be lost to
        interpreter exit. Finished threads are reaped here rather than accumulating
        over a long gateway session.
        """
        thread = threading.Thread(target=target, args=args, daemon=True)
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
            if session_id is not None:
                pending = self._session_writes.setdefault(session_id, [])
                pending[:] = [t for t in pending if t.is_alive()]
                pending.append(thread)
            thread.start()

    # -- read path ---------------------------------------------------------

    def system_prompt_block(self) -> str:
        scope = self._scope()
        where = (
            f'Anything you remember is saved to "{scope}" and visible to everyone in '
            "it, starting unconfirmed until a person reviews it."
            if scope
            else "Anything you remember is private to this user."
        )
        return (
            "Long-term memory (memkit) is available. Relevant facts about the user "
            "are injected automatically each turn. Use memkit_search when you need "
            "something specific that is not there, and memkit_remember only when "
            f"the user explicitly asks you to remember something. {where}"
        )

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """Synchronous, with a short timeout and a cache fallback.

        Hermes expects this to return instantly from a background cache, which is
        why cloud providers lag a turn behind. memkit is local — BGE-M3 on MPS plus
        Qdrant is well inside the budget — so answering on the spot is worth it, and
        the cache only covers the case where it is not.

        Never raises. A provider that throws here breaks the agent's turn, and no
        memory is strictly better than no answer.
        """
        if not self._client or not query:
            return ""
        key = query.strip()[:200]
        try:
            memories = self._search_and_track(
                key, budget_tokens=self._budget, timeout=self._prefetch_timeout
            )
            with self._lock:
                self._cache[key] = memories
                self._cache[_LAST] = memories
        except MemkitError:
            with self._lock:
                memories = self._cache.get(key) or self._cache.get(_LAST) or []
        except Exception:
            logger.debug("memkit prefetch failed", exc_info=True)
            return ""
        if not memories:
            return ""
        # Not wrapped in <memory-context>: Hermes adds its own wrapper and strips a
        # provider-supplied one with a warning.
        return "\n".join(f"- {m['text']}" for m in memories if m.get("text"))

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        """Warm the cache for the next turn, off the critical path."""
        if not self._client or not query:
            return
        self._spawn(self._warm, query.strip()[:200])

    def _warm(self, key: str) -> None:
        """Prime the cache, or just the connection when `key` is empty."""
        if not key:
            self._warm_profile()
            return
        try:
            memories = self._search_and_track(key, budget_tokens=self._budget, timeout=5.0)
        except Exception:
            return
        with self._lock:
            self._cache[key] = memories

    def _warm_profile(self) -> None:
        """Seed the last-resort fallback from the profile, not from a fake query.

        This used to search for "user preferences and identity", which is a query
        nobody asked and which ranked by similarity to that phrase.
        `/v1/profiles/render` answers the same question properly -- who the user
        is, how they work, the team's rules, this project, what changed lately --
        each block bounded by its own share of the budget. It also pays the ~840ms
        cold call here rather than in the first turn's prefetch.
        """
        if self._client is None:
            return
        try:
            blocks = self._client.render_profile(budget_tokens=self._budget, timeout=5.0)
        except Exception:
            return
        items = [
            {"id": item.get("id"), "text": item.get("text"), "kind": item.get("kind")}
            for block in PROFILE_BLOCKS
            for item in (blocks.get(block) or [])
            if item.get("text")
        ]
        with self._lock:
            self._cache.setdefault(_LAST, items)

    def _search_and_track(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        if self._client is None:
            return []
        search_with_run = getattr(self._client, "search_with_run", None)
        if search_with_run is None:
            return self._client.search(query, **kwargs)
        result = search_with_run(query, **kwargs)
        memories = list(result.get("memories") or [])
        retrieval_id = result.get("retrieval_id")
        if retrieval_id:
            with self._lock:
                self._last_retrieval = {
                    "id": str(retrieval_id),
                    "memory_ids": [str(item["id"]) for item in memories if item.get("id")],
                }
        return memories

    def _record_explicit_feedback(self, user_content: str) -> None:
        helpful = bool(_HELPFUL_MEMORY.search(user_content))
        wrong = bool(_WRONG_MEMORY.search(user_content))
        if not helpful and not wrong:
            return
        with self._lock:
            recent = dict(self._last_retrieval) if self._last_retrieval else None
        if not recent or self._client is None:
            return
        sender = getattr(self._client, "retrieval_feedback", None)
        if sender is None:
            return
        for memory_id in recent["memory_ids"]:
            try:
                sender(
                    recent["id"],
                    memory_id,
                    useful=helpful and not wrong,
                    correct=not wrong,
                )
            except Exception:
                logger.debug("memkit feedback failed", exc_info=True)

    # -- write path --------------------------------------------------------

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: list[dict[str, Any]] | None = None,
    ) -> None:
        if not self._client or self._read_only:
            return
        self._spawn(self._record_explicit_feedback, user_content)
        sid = session_id or self._session_id
        payloads = [
            self._message("user", user_content, sid),
            self._message("assistant", assistant_content, sid),
        ]
        payloads = [p for p in payloads if p]
        if self._send_tool_results and messages:
            # Off by default and left off in the acceptance checklist. `messages`
            # carries tool calls and their results: file contents, command output,
            # whatever the agent happened to read. The judge is a cloud API and what
            # reaches it becomes a permanent fact, so the safe default is structural
            # -- do not send them at all -- rather than trusting scrub.py.
            payloads += [
                p
                for p in (
                    self._message(m.get("role", ""), m.get("content", ""), sid)
                    for m in messages
                    if m.get("role") == "tool"
                )
                if p
            ]
        if payloads:
            self._spawn(self._post_all, payloads, session_id=sid)

    def _message(self, role: str, content: str, session_id: str) -> dict[str, Any] | None:
        body = scrub(content or "").strip()
        if not body or role not in ("user", "assistant", "tool"):
            return None
        # Content-hashed, not a uuid: Hermes has three independent paths that deliver
        # the same turn (sync_turn, the on_memory_write mirror, and tools), and a
        # network retry re-sends an identical turn. The service has
        # UNIQUE(external_source, external_id), so a repeat is a no-op.
        external_id = hashlib.sha256(f"{session_id}|{role}|{body}".encode()).hexdigest()[:32]
        payload = {
            "session_id": session_id or "hermes-unknown",
            "agent_id": "hermes",
            "role": role,
            "content": body,
            "external_source": "hermes",
            "external_id": external_id,
        }
        # The session's scope is fixed from the first event, so it has to be on
        # every one of them rather than sent once at the end.
        scope = self._scope()
        if scope:
            payload["scope"] = scope
        return payload

    def _post_all(self, payloads: list[dict[str, Any]]) -> None:
        try:
            self._client.add_events(payloads)
        except Exception:
            with self._lock:
                self._failed_sessions.update(str(payload["session_id"]) for payload in payloads)
            logger.warning("memkit: evidence was not stored; session will remain open")

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mirror built-in memory writes. Only additions; edits stay Hermes-side."""
        if not self._client or self._read_only or action != "add" or not content:
            return
        text = scrub(content).strip()
        if not text:
            return
        self._spawn(self._mirror, text, "preference" if target == "user" else "fact")

    def _mirror(self, text: str, kind: str) -> None:
        try:
            self._client.add_memory(text, kind=kind, importance=0.8, scope=self._scope() or None)
        except Exception:
            logger.debug("memkit: mirror failed", exc_info=True)

    # -- session boundaries ------------------------------------------------

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        """Force extraction from whatever is left in the tail.

        Synchronous and generously timed: this is the one moment the service is
        allowed to be slow, because the session is over and a dropped tail means
        those messages are never extracted.
        """
        if not self._client or self._read_only or not self._session_id:
            return
        session_id = self._session_id
        deadline = time.monotonic() + SESSION_CLOSE_TIMEOUT
        with self._lock:
            pending = list(self._session_writes.get(session_id, []))
        for thread in pending:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            incomplete = any(thread.is_alive() for thread in pending)
            failed = session_id in self._failed_sessions
            if not incomplete:
                self._session_writes.pop(session_id, None)
        remaining = deadline - time.monotonic()
        if incomplete or failed or remaining <= 0:
            logger.warning("memkit: session close skipped because evidence delivery is incomplete")
            return
        try:
            result = self._client.close_session(session_id, timeout=remaining)
            logger.info("memkit: session closed, %s", result)
        except Exception:
            logger.debug("memkit: close failed", exc_info=True)

    def on_session_switch(self, new_session_id: str, **kwargs: Any) -> None:
        self.on_session_end([])
        self._session_id = new_session_id or ""
        with self._lock:
            self._cache.clear()
            self._last_retrieval = None

    # -- tools -------------------------------------------------------------

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [MEMKIT_SEARCH, MEMKIT_REMEMBER]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs: Any) -> str:
        from tools.registry import tool_error

        if not self._client:
            return tool_error("memkit is not initialized")
        try:
            if tool_name == "memkit_search":
                query = str(args.get("query") or "").strip()
                if not query:
                    return tool_error("query is required")
                context_key = str(args.get("context_key") or "").strip()
                context_value = str(args.get("context_value") or "").strip()
                memories = self._search_and_track(
                    query,
                    budget_tokens=self._budget,
                    context={context_key: context_value} if context_key and context_value else None,
                    timeout=5.0,
                )
                if not memories:
                    return "No matching memories."
                return "\n".join(f"- ({m.get('kind')}) {m['text']}" for m in memories)
            if tool_name == "memkit_remember":
                text = scrub(str(args.get("text") or "")).strip()
                if not text:
                    return tool_error("text is required")
                if self._read_only:
                    return tool_error("writes are disabled in this context")
                # Straight to /v1/memories, past the judge, at high importance: the
                # user said "remember this", so there is nothing to weigh up.
                result = self._client.add_memory(
                    text,
                    kind=str(args.get("kind") or "fact"),
                    importance=0.9,
                    source_role="manual",
                    scope=self._scope() or None,
                )
                where = self._scope()
                if where and result.get("review_status") == "pending":
                    # Telling the model this is the point: a shared write is live
                    # but unconfirmed, and saying "remembered" without saying
                    # "shared, pending review" misreports what just happened.
                    return f'Remembered in "{where}", pending team review: {text}'
                return f"Remembered: {text} (id {result.get('id', '?')})"
            return tool_error(f"unknown tool: {tool_name}")
        except MemkitError as exc:
            return tool_error(f"memkit unavailable: {exc}")

    # -- setup and backup --------------------------------------------------

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "base_url",
                "description": "memkit service URL",
                "default": "http://127.0.0.1:8077",
            },
            {
                "key": "api_key",
                "description": (
                    "This person's memkit key, from `memkit api-keys create --user "
                    "<handle>`. It is the identity on every request; there is no "
                    "instance-wide key. Read from ~/.config/memkit/client.env when "
                    "unset."
                ),
                "secret": True,
                "required": False,
                "env_var": "MEMKIT_API_KEY",
            },
            {
                "key": "api_key_file",
                "description": (
                    "Optional 0600 file holding just the key, for a Hermes process "
                    "with no environment. Leave empty to use the standard order: "
                    "environment, then ~/.config/memkit/client.env."
                ),
                "default": "",
            },
            {
                "key": "scope",
                "description": (
                    "Shared entity slug that writes from this agent belong to. "
                    "Empty means private to the key holder. A shared write is live "
                    "immediately but starts unconfirmed in that team's review queue."
                ),
                "default": "",
            },
            {
                "key": "backup_dir",
                "description": (
                    "memkit's pg_dump archive directory, included by Hermes backup. "
                    "Postgres is the source of truth now, so there is no database "
                    "file to copy -- only what `memkit backup` has written."
                ),
                "default": "./data/backups",
            },
            {
                "key": "budget_tokens",
                "description": "Token budget for injected memory per turn",
                "default": "800",
            },
            {
                "key": "prefetch_timeout",
                "description": (
                    "Seconds to wait for injected memory each turn. Measured: 75-93ms "
                    "steady state over HTTP. Raise only if the log shows timeouts."
                ),
                "default": "0.4",
            },
            {
                "key": "send_tool_results",
                "description": (
                    "Forward tool messages to the extractor. Leave false: they "
                    "carry file contents and command output, and the judge is a "
                    "cloud API."
                ),
                "default": "false",
                "choices": ["true", "false"],
            },
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        config_path = Path(hermes_home) / "config.yaml"
        try:
            import yaml

            existing: dict[str, Any] = {}
            if config_path.exists():
                with open(config_path, encoding="utf-8-sig") as fh:
                    existing = yaml.safe_load(fh) or {}
            existing.setdefault("plugins", {})
            existing["plugins"]["memkit"] = values
            with open(config_path, "w", encoding="utf-8") as fh:
                yaml.dump(existing, fh, default_flow_style=False, allow_unicode=True)
        except Exception:
            logger.warning("memkit: could not write %s", config_path, exc_info=True)

    def backup_paths(self) -> list[str]:
        """memkit's own state, which lives outside HERMES_HOME.

        `hermes backup` only walks HERMES_HOME, so without this nothing of this
        provider's state reaches the archive. What that state *is* changed with
        decisions/0059: Postgres is the source of truth, so there is no database
        file to copy and the recoverable artefact is the `pg_dump` archive
        directory `memkit backup` writes. Resolved from config only, with no
        network and no initialize(), as the ABC requires.
        """
        backup_dir = (
            self._config.get("backup_dir")
            or os.environ.get("MEMKIT_BACKUP_DIR")
            or "./data/backups"
        )
        return [str(Path(str(backup_dir)).expanduser().resolve())]


def register(ctx: Any) -> None:
    """Explicit registration hook.

    The loader tries this first and only falls back to instantiating whatever
    MemoryProvider subclass `dir(module)` happens to surface first. Declaring it
    removes that dependency on attribute ordering.
    """
    ctx.register_memory_provider(MemkitProvider())


# Hermes discovers the provider class by scanning this module.
__all__ = ["MemkitProvider", "register"]
