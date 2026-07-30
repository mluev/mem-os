"""memkit — Hermes MemoryProvider backed by the local memkit service.

Everything inside memkit (Qdrant, BGE-M3 on MPS, the extraction judge) is invisible
from here: this plugin only speaks HTTP to 127.0.0.1.

Install with `memkit install-hermes`, which copies this package to
`$HERMES_HOME/plugins/memkit` — the directory Hermes scans for user-installed
providers. Then in `$HERMES_HOME/config.yaml`:

    memory:
      provider: memkit
    plugins:
      memkit:
        base_url: http://127.0.0.1:8077
        owner_id: u-1
        budget_tokens: 800
        send_tool_results: false

`MEMKIT_API_KEY` comes from the environment.

Corrections to docs/07-hermes-adapter.md, which was written before the real ABC
was read. Each of these would have stopped the plugin loading or working:

* The ABC has **four** abstract members, not two: `name` (a property),
  `is_available()`, `initialize()` and `get_tool_schemas()`. A class missing any
  of them cannot be instantiated.
* User plugins live in `$HERMES_HOME/plugins/<name>/`. The `plugins/memory/<name>/`
  path in the doc is where *bundled* providers live, inside the hermes-agent
  package.
* Tool schemas use a `parameters` key, not `input_schema`. All four shipped
  providers do it this way.
* `prefetch(query, *, session_id="")`, and `on_session_end(messages)` takes the
  message list. The doc gives both no arguments.
* There is no `POST /v1/sessions`. Sessions are created implicitly by the first
  message, via `ensure_session`.
* `queue_prefetch`, `get_config_schema`, `save_config` and `backup_paths` exist and
  matter; the doc does not mention them. `backup_paths` especially: memkit's SQLite
  and Qdrant data live outside HERMES_HOME, so without declaring them
  `hermes backup` silently captures nothing of this provider's state.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Any

from agent.memory_provider import MemoryProvider

from .client import Client, MemkitError
from .scrub import scrub

logger = logging.getLogger(__name__)

_LAST = "__last__"

MEMKIT_SEARCH = {
    "name": "memkit_search",
    "description": (
        "Search long-term memory about the user and their projects. Use when you "
        "need a preference, a past decision, or a fact about the user that is not "
        "already in the injected context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for."},
            "scope": {
                "type": "string",
                "enum": ["user", "project", "task"],
                "description": "Optional filter. Omit to search everything.",
            },
            "project": {
                "type": "string",
                "description": (
                    "Current project/repository name. Required to see "
                    "project-scoped facts; without it they are filtered out."
                ),
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
            "type": {
                "type": "string",
                "enum": [
                    "preference", "fact", "skill", "relation", "project",
                    "decision", "task",
                ],
            },
        },
        "required": ["text"],
    },
}


def _config() -> dict[str, Any]:
    try:
        from hermes_cli.config import cfg_get

        return cfg_get("plugins.memkit", {}) or {}
    except Exception:  # noqa: BLE001 - a missing config is not an error
        return {}


class MemkitProvider(MemoryProvider):
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config if config is not None else _config()
        self._client: Client | None = None
        self._session_id = ""
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._threads: list[threading.Thread] = []
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
        return str(self._config.get("base_url") or "http://127.0.0.1:8077")

    def _api_key(self) -> str:
        env_var = str(self._config.get("api_key_env") or "MEMKIT_API_KEY")
        return os.environ.get(env_var, "")

    # -- lifecycle ---------------------------------------------------------

    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._session_id = session_id or ""
        self._client = Client(
            self._base_url(),
            self._api_key(),
            owner_id=str(self._config.get("owner_id") or "u-1"),
        )
        # Non-primary contexts must not write: a cron system prompt or a subagent's
        # scratch reasoning is not the user talking, and the ABC says so explicitly.
        self._read_only = kwargs.get("agent_context", "primary") != "primary"
        if self._read_only:
            logger.info("memkit: %s context, writes disabled",
                        kwargs.get("agent_context"))
        # Pay the ~840ms cold call here, in the background, rather than letting the
        # first turn's prefetch eat its timeout and silently return no memory.
        self._spawn(self._warm, "")

    def shutdown(self) -> None:
        for thread in list(self._threads):
            thread.join(timeout=5.0)
        self._threads.clear()

    def _spawn(self, target: Any, *args: Any) -> None:
        """Run a write off the turn's critical path.

        Daemon threads so a hung request cannot keep the agent alive, but tracked so
        `shutdown` can wait for them -- a turn's last message must not be lost to
        interpreter exit. Finished threads are reaped here rather than accumulating
        over a long gateway session.
        """
        self._threads = [t for t in self._threads if t.is_alive()]
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        self._threads.append(thread)

    # -- read path ---------------------------------------------------------

    def system_prompt_block(self) -> str:
        return (
            "Long-term memory (memkit) is available. Relevant facts about the user "
            "are injected automatically each turn. Use memkit_search when you need "
            "something specific that is not there, and memkit_remember only when "
            "the user explicitly asks you to remember something."
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
            memories = self._client.search(
                key, budget_tokens=self._budget, timeout=self._prefetch_timeout
            )
            with self._lock:
                self._cache[key] = memories
                self._cache[_LAST] = memories
        except MemkitError:
            with self._lock:
                memories = self._cache.get(key) or self._cache.get(_LAST) or []
        except Exception:  # noqa: BLE001 - see the docstring; never propagate
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
        try:
            memories = self._client.search(
                key or "user preferences and identity",
                budget_tokens=self._budget,
                timeout=5.0,
            )
        except Exception:  # noqa: BLE001 - background, best effort
            return
        if not key:
            # Startup warm-up: seed only the last-resort fallback, so a real query
            # is never answered with generic results it did not ask for.
            with self._lock:
                self._cache.setdefault(_LAST, memories)
            return
        with self._lock:
            self._cache[key] = memories

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
                p for p in (
                    self._message(m.get("role", ""), m.get("content", ""), sid)
                    for m in messages if m.get("role") == "tool"
                ) if p
            ]
        if payloads:
            self._spawn(self._post_all, payloads)

    def _message(self, role: str, content: str, session_id: str) -> dict[str, Any] | None:
        body = scrub(content or "").strip()
        if not body or role not in ("user", "assistant", "tool"):
            return None
        # Content-hashed, not a uuid: Hermes has three independent paths that deliver
        # the same turn (sync_turn, the on_memory_write mirror, and tools), and a
        # network retry re-sends an identical turn. The service has
        # UNIQUE(external_source, external_id), so a repeat is a no-op.
        external_id = hashlib.sha256(
            f"{session_id}|{role}|{body}".encode()
        ).hexdigest()[:32]
        return {
            "session_id": session_id or "hermes-unknown",
            "owner_id": self._client.owner_id,
            "agent_id": "hermes",
            # A tool message is stored as an assistant turn: the service's schema
            # only knows user and assistant.
            "role": "user" if role == "user" else "assistant",
            "content": body,
            "external_source": "hermes",
            "external_id": external_id,
        }

    def _post_all(self, payloads: list[dict[str, Any]]) -> None:
        for payload in payloads:
            try:
                self._client.add_message(payload)
            except MemkitError as exc:
                logger.debug("memkit: message not stored (%s)", exc)
            except Exception:  # noqa: BLE001 - background thread, never crash
                logger.debug("memkit: message not stored", exc_info=True)

    def on_memory_write(
        self, action: str, target: str, content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Mirror built-in memory writes. Only additions; edits stay Hermes-side."""
        if not self._client or self._read_only or action != "add" or not content:
            return
        text = scrub(content).strip()
        if not text:
            return
        self._spawn(
            self._mirror, text, "preference" if target == "user" else "fact"
        )

    def _mirror(self, text: str, type_: str) -> None:
        try:
            self._client.add_memory(text, type=type_, importance=0.8)
        except Exception:  # noqa: BLE001 - background, best effort
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
        try:
            result = self._client.close_session(self._session_id)
            logger.info("memkit: session closed, %s", result)
        except Exception:  # noqa: BLE001 - end of session, nothing to break
            logger.debug("memkit: close failed", exc_info=True)

    def on_session_switch(self, new_session_id: str, **kwargs: Any) -> None:
        self.on_session_end([])
        self._session_id = new_session_id or ""
        with self._lock:
            self._cache.clear()

    # -- tools -------------------------------------------------------------

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [MEMKIT_SEARCH, MEMKIT_REMEMBER]

    def handle_tool_call(
        self, tool_name: str, args: dict[str, Any], **kwargs: Any
    ) -> str:
        from tools.registry import tool_error

        if not self._client:
            return tool_error("memkit is not initialized")
        try:
            if tool_name == "memkit_search":
                query = str(args.get("query") or "").strip()
                if not query:
                    return tool_error("query is required")
                scope = args.get("scope")
                memories = self._client.search(
                    query,
                    budget_tokens=self._budget,
                    scopes=[scope] if scope else None,
                    scope_key=args.get("project") or None,
                    timeout=5.0,
                )
                if not memories:
                    return "No matching memories."
                return "\n".join(
                    f"- ({m.get('type')}, {m.get('scope')}) {m['text']}"
                    for m in memories
                )
            if tool_name == "memkit_remember":
                text = scrub(str(args.get("text") or "")).strip()
                if not text:
                    return tool_error("text is required")
                if self._read_only:
                    return tool_error("writes are disabled in this context")
                # Straight to /v1/memories, past the judge, at high importance: the
                # user said "remember this", so there is nothing to weigh up.
                result = self._client.add_memory(
                    text, type=str(args.get("type") or "fact"), importance=0.9
                )
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
                "description": "X-API-Key for the memkit service",
                "secret": True,
                "required": True,
                "env_var": "MEMKIT_API_KEY",
            },
            {"key": "owner_id", "description": "memkit owner id", "default": "u-1"},
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
        except Exception:  # noqa: BLE001 - setup convenience, not correctness
            logger.warning("memkit: could not write %s", config_path, exc_info=True)

    def backup_paths(self) -> list[str]:
        """memkit's own state, which lives outside HERMES_HOME.

        `hermes backup` only walks HERMES_HOME, so without this the SQLite source of
        truth is not in the archive and a backup/restore cycle silently loses every
        memory. Resolved from config only, with no network and no initialize(), as
        the ABC requires.
        """
        paths: list[str] = []
        db_path = self._config.get("db_path")
        if db_path:
            paths.append(str(Path(str(db_path)).expanduser()))
        qdrant_path = self._config.get("qdrant_storage")
        if qdrant_path:
            paths.append(str(Path(str(qdrant_path)).expanduser()))
        return paths


def register(ctx: Any) -> None:
    """Explicit registration hook.

    The loader tries this first and only falls back to instantiating whatever
    MemoryProvider subclass `dir(module)` happens to surface first. Declaring it
    removes that dependency on attribute ordering.
    """
    ctx.register_memory_provider(MemkitProvider())


# Hermes discovers the provider class by scanning this module.
__all__ = ["MemkitProvider", "register"]
