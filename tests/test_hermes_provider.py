"""The Hermes provider, against the acceptance checklist in docs/07.

The provider is stdlib-only and talks HTTP, so every checklist item except "a fact
said in chat surfaces in the coding agent" is testable here with a fake transport.
That last one needs both agents running and is done by hand.

Loaded by file path rather than imported: the package lives in
`integrations/hermes/memkit`, is installed into `$HERMES_HOME/plugins/memkit`, and
`from agent.memory_provider import MemoryProvider` only resolves inside Hermes. A
stub for that module is injected before loading, which is also what proves the
provider does not secretly depend on anything else of Hermes's.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
import threading
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "integrations" / "hermes" / "memkit"


def _load_plugin():
    """Import the provider with Hermes's two touchpoints stubbed out."""
    names = ("agent", "agent.memory_provider", "tools", "tools.registry")
    previous = {name: sys.modules.get(name) for name in names}
    if "agent.memory_provider" not in sys.modules:
        agent = types.ModuleType("agent")
        provider_mod = types.ModuleType("agent.memory_provider")

        class MemoryProvider:  # minimal stand-in for the real ABC
            pass

        provider_mod.MemoryProvider = MemoryProvider
        agent.memory_provider = provider_mod
        sys.modules["agent"] = agent
        sys.modules["agent.memory_provider"] = provider_mod

    package = "memkit_hermes_plugin"
    spec = importlib.util.spec_from_file_location(
        package,
        str(PLUGIN / "__init__.py"),
        submodule_search_locations=[str(PLUGIN)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    try:
        spec.loader.exec_module(module)
    finally:
        # Hermes stubs must not replace the repository's tools namespace during
        # collection of unrelated SDK/contract tests.
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return module


plugin = _load_plugin()


@pytest.fixture(autouse=True)
def hermes_tool_registry(monkeypatch):
    registry = types.ModuleType("tools.registry")
    registry.tool_error = lambda message, **extra: json.dumps({"error": str(message), **extra})
    monkeypatch.setitem(sys.modules, "tools.registry", registry)


class FakeClient:
    """Stands in for the HTTP client. Records what the provider tried to do."""

    def __init__(self, *, fail=False, memories=None, blocks=None):
        self.fail = fail
        self.memories = memories or []
        self.blocks = blocks or {}
        self.messages: list[dict] = []
        self.memories_added: list[dict] = []
        self.closed: list[str] = []
        self.searches: list[str] = []
        self.profiles: list[dict] = []

    def _boom(self):
        from memkit_hermes_plugin.client import MemkitError

        raise MemkitError("service down")

    def search(self, query, **kwargs):
        self.searches.append(query)
        if self.fail:
            self._boom()
        return self.memories

    def render_profile(self, **kwargs):
        if self.fail:
            self._boom()
        self.profiles.append(kwargs)
        return self.blocks

    def add_events(self, payloads):
        if self.fail:
            self._boom()
        self.messages.extend(payloads)
        return {"count": len(payloads)}

    def add_memory(self, text, **kwargs):
        if self.fail:
            self._boom()
        self.memories_added.append({"text": text, **kwargs})
        return {"id": "m-1"}

    def close_session(self, session_id, **kwargs):
        if self.fail:
            self._boom()
        self.closed.append(session_id)
        return {"extracted": 2}


def make_provider(*, client=None, config=None):
    provider = plugin.MemkitProvider(config or {})
    provider.initialize("s-1", hermes_home="/tmp", platform="cli")
    if client is not None:
        provider._client = client
    return provider


@contextlib.contextmanager
def _no_client_config(**files):
    """Point the config paths at a scratch directory.

    Needed because `resolve_config` reads real files: a test asserting "no key
    configured" would otherwise pass or fail depending on whether the developer
    running it happens to have `~/.config/memkit/client.env`.
    """
    from memkit_hermes_plugin import client as client_module

    with TemporaryDirectory() as directory:
        paths = {
            "CLIENT_ENV": Path(directory) / "client.env",
            "LEGACY_ENV": Path(directory) / "legacy",
        }
        for name, contents in files.items():
            paths[name].write_text(contents)
        with patch.multiple(client_module, **paths):
            yield paths


class TestContract(unittest.TestCase):
    """What the ABC requires. Getting any of this wrong stops the plugin loading."""

    def test_the_four_abstract_members_exist(self):
        provider = plugin.MemkitProvider({})
        self.assertEqual(provider.name, "memkit")
        self.assertIsInstance(provider.is_available(), bool)
        self.assertTrue(callable(provider.initialize))
        self.assertTrue(callable(provider.get_tool_schemas))

    def test_default_provider_loads_nested_hermes_config(self):
        config = {"plugins": {"memkit": {"base_url": "http://configured"}}}
        config_module = types.ModuleType("hermes_cli.config")
        config_module.load_config = lambda: config
        config_module.cfg_get = lambda value, *keys, default=None: value.get(keys[0], {}).get(
            keys[1], default
        )
        hermes_cli = types.ModuleType("hermes_cli")
        hermes_cli.config = config_module
        with patch.dict(
            sys.modules,
            {"hermes_cli": hermes_cli, "hermes_cli.config": config_module},
        ):
            self.assertEqual(plugin.MemkitProvider()._base_url(), "http://configured")

    def test_tool_schemas_use_the_parameters_key(self):
        # docs/07 specifies `input_schema`. All four shipped providers use
        # `parameters`, and a wrong key means the tools silently never work.
        for schema in plugin.MemkitProvider({}).get_tool_schemas():
            self.assertIn("parameters", schema)
            self.assertNotIn("input_schema", schema)
            self.assertIn("name", schema)

    def test_is_available_makes_no_network_call(self):
        # The ABC says this is called during agent init and must only check config.
        with patch.object(plugin, "Client", side_effect=AssertionError("no network")):
            provider = plugin.MemkitProvider({"base_url": "http://x"})
            with patch.dict("os.environ", {"MEMKIT_API_KEY": "k"}):
                self.assertTrue(provider.is_available())

    def test_unavailable_without_a_key(self):
        provider = plugin.MemkitProvider({"base_url": "http://x"})
        with patch.dict("os.environ", {}, clear=True), _no_client_config():
            self.assertFalse(provider.is_available())

    def test_restricted_key_file_supports_fresh_processes(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "api-key"
            path.write_text("x" * 48)
            path.chmod(0o600)
            provider = plugin.MemkitProvider({"base_url": "http://x", "api_key_file": str(path)})
            with patch.dict("os.environ", {}, clear=True):
                self.assertTrue(provider.is_available())

    def test_configured_key_file_overrides_a_stale_environment_key(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "api-key"
            path.write_text("f" * 48)
            path.chmod(0o600)
            provider = plugin.MemkitProvider({"api_key_file": str(path)})
            with patch.dict("os.environ", {"MEMKIT_API_KEY": "stale"}, clear=True):
                self.assertEqual(provider._api_key(), "f" * 48)

    def test_key_file_fails_closed_when_permissions_are_broad(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            path = Path(directory) / "api-key"
            path.write_text("x" * 48)
            path.chmod(0o644)
            provider = plugin.MemkitProvider({"base_url": "http://x", "api_key_file": str(path)})
            with patch.dict("os.environ", {}, clear=True):
                self.assertFalse(provider.is_available())

    def test_backup_paths_needs_no_initialize_and_no_network(self):
        # hermes backup only walks HERMES_HOME; memkit's state lives outside it, so
        # an undeclared path means a backup/restore cycle loses every memory. What
        # that state is moved with decisions/0059: Postgres is the truth, so the
        # recoverable artefact is the pg_dump directory, not a database file.
        provider = plugin.MemkitProvider({"backup_dir": "~/dev/memkit/data/backups"})
        paths = provider.backup_paths()
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("data/backups"))
        self.assertNotIn("~", paths[0])

    def test_backup_paths_defaults_to_the_dump_directory(self):
        provider = plugin.MemkitProvider({})
        with patch.dict("os.environ", {}, clear=True):
            paths = provider.backup_paths()
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("data/backups"))
        self.assertNotIn("memkit.db", paths[0], "there is no SQLite file to back up")


class TestServiceDown(unittest.TestCase):
    """Checklist: service stopped -> Hermes works, memory empty, no errors."""

    def test_prefetch_returns_empty_string_not_an_exception(self):
        provider = make_provider(client=FakeClient(fail=True))
        self.assertEqual(provider.prefetch("what do i prefer"), "")

    def test_prefetch_falls_back_to_cache(self):
        client = FakeClient(memories=[{"text": "Prefers pnpm"}])
        provider = make_provider(client=client)
        self.assertIn("Prefers pnpm", provider.prefetch("tooling"))
        client.fail = True
        # Same query: served from cache rather than going dark.
        self.assertIn("Prefers pnpm", provider.prefetch("tooling"))
        # Different query: falls back to the last known good result.
        self.assertIn("Prefers pnpm", provider.prefetch("something else"))

    def test_sync_turn_never_raises(self):
        provider = make_provider(client=FakeClient(fail=True))
        provider.sync_turn("hi", "hello", session_id="s-1")
        provider.shutdown()

    def test_tool_call_reports_the_outage_as_a_tool_error(self):
        provider = make_provider(client=FakeClient(fail=True))
        result = provider.handle_tool_call("memkit_search", {"query": "x"})
        self.assertIn("error", json.loads(result))


class TestPrefetchShape(unittest.TestCase):
    def test_result_is_not_wrapped_in_memory_context(self):
        # Hermes adds its own wrapper and strips a provider-supplied one, with a
        # warning. Returning bare lines is the contract.
        provider = make_provider(client=FakeClient(memories=[{"text": "A"}]))
        out = provider.prefetch("q")
        self.assertNotIn("<memory-context>", out)
        self.assertEqual(out, "- A")

    def test_empty_query_short_circuits(self):
        client = FakeClient()
        provider = make_provider(client=client)
        self.assertEqual(provider.prefetch(""), "")
        self.assertEqual(client.searches, [])


class TestIdempotency(unittest.TestCase):
    """Checklist: the same turn sent twice leaves one pair of messages."""

    def test_external_id_is_stable_across_identical_turns(self):
        provider = make_provider(client=FakeClient())
        first = provider._message("user", "я предпочитаю pnpm", "s-1")
        second = provider._message("user", "я предпочитаю pnpm", "s-1")
        self.assertEqual(first["external_id"], second["external_id"])
        self.assertEqual(first["external_source"], "hermes")

    def test_different_session_or_role_gives_a_different_id(self):
        provider = make_provider(client=FakeClient())
        base = provider._message("user", "same text", "s-1")
        self.assertNotEqual(
            base["external_id"], provider._message("user", "same text", "s-2")["external_id"]
        )
        self.assertNotEqual(
            base["external_id"],
            provider._message("assistant", "same text", "s-1")["external_id"],
        )

    def test_empty_content_produces_no_message(self):
        provider = make_provider(client=FakeClient())
        self.assertIsNone(provider._message("user", "   ", "s-1"))


class TestSecrets(unittest.TestCase):
    """Checklist: a secret in command output must not reach the store."""

    def test_credential_assignments_are_redacted_anywhere_in_the_text(self):
        """Regression: the first live checklist run leaked a mid-sentence key.

        The original pattern was anchored to the start of a line, and the unit test
        that "covered" it obligingly put the key on its own line. A key pasted into
        a sentence went through untouched.
        """
        provider = make_provider(client=FakeClient())
        for text in (
            "вот мой конфиг\nAWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI1K7MDENG\n",
            "вот ключ AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI1K7MDENG для доступа",
            "set API_KEY: abc123def456 and restart",
            "DB_PASSWORD=hunter2",
        ):
            payload = provider._message("user", text, "s-1")
            self.assertNotIn("wJalrXUtnFEMI1K7MDENG", payload["content"], text)
            self.assertNotIn("hunter2", payload["content"], text)
            self.assertNotIn("abc123def456", payload["content"], text)

    def test_redaction_keeps_the_surrounding_sentence(self):
        # Replacing the whole line would eat the user's actual words, and the point
        # of forwarding user turns at all is that the extractor reads them.
        provider = make_provider(client=FakeClient())
        payload = provider._message(
            "user", "вот ключ API_KEY=sk-secret123456 поставь его в прод", "s-1"
        )
        self.assertIn("поставь его в прод", payload["content"])
        self.assertIn("[REDACTED]", payload["content"])

    def test_known_token_shapes_are_redacted(self):
        from memkit_hermes_plugin.scrub import scrub

        for secret in (
            "sk-abcdefghijklmnopqrstuvwxyz012345",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_" + "a" * 36,
            "postgres://user:hunter2@db.internal/app",
            "Authorization: Bearer abc.def.ghi",
        ):
            cleaned = scrub(secret)
            self.assertNotEqual(cleaned, secret, secret)

    def test_tool_messages_are_not_forwarded_by_default(self):
        # The structural defence: docs/07 is right that a regex will always miss
        # something, so tool output is not sent at all unless explicitly enabled.
        client = FakeClient()
        provider = make_provider(client=client)
        provider.sync_turn(
            "run the seeder",
            "done",
            session_id="s-1",
            messages=[{"role": "tool", "content": "DATABASE_URL=postgres://u:p@h/db"}],
        )
        provider.shutdown()
        self.assertEqual(len(client.messages), 2)
        self.assertTrue(all("DATABASE_URL" not in m["content"] for m in client.messages))

    def test_enabling_tool_results_still_scrubs(self):
        client = FakeClient()
        provider = make_provider(client=client, config={"send_tool_results": True})
        provider.sync_turn(
            "go",
            "ok",
            session_id="s-1",
            messages=[{"role": "tool", "content": "API_KEY=sk-" + "z" * 30}],
        )
        provider.shutdown()
        self.assertEqual(len(client.messages), 3)
        self.assertTrue(all("sk-zzz" not in m["content"] for m in client.messages))


class TestWriteGuards(unittest.TestCase):
    def test_non_primary_contexts_do_not_write(self):
        # The ABC warns that cron and subagent traffic would corrupt the user's
        # representation: a cron system prompt is not the user talking.
        provider = plugin.MemkitProvider({})
        provider.initialize("s-1", hermes_home="/tmp", platform="cron", agent_context="cron")
        client = FakeClient()
        provider._client = client
        provider.sync_turn("hi", "hello", session_id="s-1")
        provider.on_memory_write("add", "user", "Likes tea")
        provider.shutdown()
        self.assertEqual(client.messages, [])
        self.assertEqual(client.memories_added, [])

    def test_remember_tool_bypasses_the_judge_at_high_importance(self):
        client = FakeClient()
        provider = make_provider(client=client)
        result = provider.handle_tool_call(
            "memkit_remember", {"text": "Lives in Tashkent", "kind": "fact"}
        )
        self.assertIn("Remembered", result)
        self.assertEqual(client.memories_added[0]["importance"], 0.9)
        self.assertEqual(client.memories_added[0]["source_role"], "manual")

    def test_unknown_tool_is_an_error(self):
        provider = make_provider(client=FakeClient())
        self.assertIn("error", json.loads(provider.handle_tool_call("nope", {})))


class TestPerUserKeys(unittest.TestCase):
    """The key is an identity now, so where it comes from is a correctness claim.

    There is no instance-wide key: `memkit api-keys create --user <handle>` mints
    one per person, and it decides whose memory the plugin reads and writes. A
    plugin looking somewhere the CLI and the hooks do not therefore does not
    degrade -- it acts as the wrong person, or as nobody.
    """

    def test_the_precedence_matches_the_rest_of_the_system(self):
        provider = plugin.MemkitProvider({})
        with (
            patch.dict("os.environ", {}, clear=True),
            _no_client_config(CLIENT_ENV="MEMKIT_API_KEY=from-client-env\n"),
        ):
            self.assertEqual(provider._api_key(), "from-client-env")
        with (
            patch.dict("os.environ", {"MEMKIT_API_KEY": "from-env"}, clear=True),
            _no_client_config(CLIENT_ENV="MEMKIT_API_KEY=from-client-env\n"),
        ):
            self.assertEqual(provider._api_key(), "from-env")
        with (
            patch.dict("os.environ", {}, clear=True),
            _no_client_config(LEGACY_ENV="MEMKIT_API_KEY=legacy\n"),
        ):
            self.assertEqual(provider._api_key(), "legacy")

    def test_the_base_url_also_comes_from_the_shared_config(self):
        provider = plugin.MemkitProvider({})
        with (
            patch.dict("os.environ", {}, clear=True),
            _no_client_config(CLIENT_ENV="MEMKIT_BASE_URL=http://memory.internal:8077\n"),
        ):
            self.assertEqual(provider._base_url(), "http://memory.internal:8077")

    def test_the_hook_and_the_plugin_agree_on_the_paths(self):
        """Two copies of the precedence, held together here.

        `client.py` cannot import `memkit.remote`: the plugin runs under Hermes's
        interpreter, which has no reason to have memkit installed. The
        duplication is therefore correct and this is what stops it drifting.
        """
        from memkit_hermes_plugin import client as client_module

        from memkit import remote

        self.assertEqual(client_module.CLIENT_ENV, remote.CLIENT_ENV)
        self.assertEqual(client_module.LEGACY_ENV, remote.LEGACY_ENV)
        self.assertEqual(client_module.DEFAULT_BASE_URL, remote.DEFAULT_BASE_URL)


class TestProfileShape(unittest.TestCase):
    """`{stable, dynamic}` is gone; the profile is five named blocks."""

    BLOCKS: ClassVar[dict] = {
        "about": [{"id": "1", "text": "Lives in Tashkent", "kind": "fact"}],
        "style": [{"id": "2", "text": "Wants comments that say why", "kind": "preference"}],
        "team": [],
        "project": [{"id": "3", "text": "Postgres is the truth", "kind": "fact"}],
        "recent": [{"id": "4", "text": "Moved the schema to v1", "kind": "fact"}],
    }

    def test_the_client_asks_for_every_block_and_returns_them(self):
        from memkit_hermes_plugin.client import PROFILE_BLOCKS, Client

        client = Client("http://127.0.0.1:1", "k")
        with patch.object(
            client, "_request", return_value={"blocks": self.BLOCKS, "used_tokens": 20}
        ) as request:
            self.assertEqual(client.render_profile(workspace="mem-os"), self.BLOCKS)
        body = request.call_args.args[2]
        self.assertEqual(body["blocks"], list(PROFILE_BLOCKS))
        self.assertEqual(body["workspace"], "mem-os")

    def test_the_profile_matches_the_api_model(self):
        """Assert against the model, not against remembered field names."""
        from memkit_hermes_plugin.client import PROFILE_BLOCKS

        from memkit import api

        api.ProfileIn.model_validate({"blocks": list(PROFILE_BLOCKS), "budget_tokens": 800})
        self.assertEqual(
            list(PROFILE_BLOCKS), api.ProfileIn.model_fields["blocks"].default_factory()
        )

    def test_the_startup_warm_seeds_from_the_profile_not_a_made_up_query(self):
        """It used to search for "user preferences and identity" -- nobody's query.

        `/v1/profiles/render` answers that question properly, block by block,
        each bounded by its own share of the budget.
        """
        client = FakeClient(blocks=self.BLOCKS)
        provider = plugin.MemkitProvider({})
        provider._client = client
        provider._warm("")
        self.assertEqual(client.searches, [])
        self.assertEqual(len(client.profiles), 1)
        seeded = [item["text"] for item in provider._cache[plugin._LAST]]
        self.assertEqual(seeded[0], "Lives in Tashkent")
        self.assertEqual(len(seeded), 4, "the empty team block contributes nothing")

    def test_a_failed_profile_render_seeds_nothing(self):
        provider = plugin.MemkitProvider({})
        provider._client = FakeClient(fail=True)
        provider._warm("")
        self.assertEqual(provider._cache, {})


class TestScopedWrites(unittest.TestCase):
    """A shared scope is opt-in, and it changes what the model should say."""

    def test_writes_are_private_unless_a_scope_is_configured(self):
        client = FakeClient()
        provider = make_provider(client=client)
        provider.sync_turn("я предпочитаю pnpm", "понял", session_id="s-1")
        provider.shutdown()
        self.assertTrue(client.messages)
        for message in client.messages:
            self.assertNotIn("scope", message)
        provider.handle_tool_call("memkit_remember", {"text": "Lives in Tashkent"})
        self.assertIsNone(client.memories_added[0]["scope"])

    def test_a_configured_scope_is_stamped_on_every_event(self):
        """The session's scope is fixed from its first event, not set at the end."""
        client = FakeClient()
        provider = make_provider(client=client, config={"scope": "mem-os"})
        provider.sync_turn("я предпочитаю pnpm", "понял", session_id="s-1")
        provider.shutdown()
        self.assertTrue(client.messages)
        for message in client.messages:
            self.assertEqual(message["scope"], "mem-os")

    def test_the_event_payload_still_matches_the_api_model(self):
        from memkit import api

        provider = make_provider(client=FakeClient(), config={"scope": "mem-os"})
        payload = provider._message("user", "я предпочитаю pnpm", "s-1")
        self.assertLessEqual(set(payload), set(api.MessageIn.model_fields))
        api.MessageIn.model_validate(payload)

    def test_a_shared_remember_reports_that_it_needs_review(self):
        """Saying "Remembered" about a pending shared write misreports it."""
        client = FakeClient()
        client.add_memory = lambda text, **kwargs: {"id": "m-1", "review_status": "pending"}
        provider = make_provider(client=client, config={"scope": "mem-os"})
        result = provider.handle_tool_call("memkit_remember", {"text": "Releases ship Thursday"})
        self.assertIn("mem-os", result)
        self.assertIn("review", result)

    def test_the_system_prompt_says_where_memory_goes(self):
        private = plugin.MemkitProvider({}).system_prompt_block()
        shared = plugin.MemkitProvider({"scope": "mem-os"}).system_prompt_block()
        self.assertIn("private", private)
        self.assertIn("mem-os", shared)
        self.assertIn("unconfirmed", shared)


class TestSessionBoundaries(unittest.TestCase):
    """Checklist: on_session_end forces extraction from the tail."""

    def test_session_end_closes_the_session(self):
        client = FakeClient()
        provider = make_provider(client=client)
        provider.on_session_end([])
        self.assertEqual(client.closed, ["s-1"])

    def test_session_switch_closes_and_clears_the_cache(self):
        client = FakeClient(memories=[{"text": "old"}])
        provider = make_provider(client=client)
        provider.prefetch("q")
        provider.on_session_switch("s-2")
        self.assertEqual(client.closed, ["s-1"])
        self.assertEqual(provider._cache, {})
        self.assertEqual(provider._session_id, "s-2")

    def test_session_end_waits_for_pending_evidence_before_closing(self):
        started, release, closed = threading.Event(), threading.Event(), threading.Event()
        order = []

        class SlowClient(FakeClient):
            def add_events(self, payloads):
                started.set()
                release.wait(2)
                order.append("evidence")
                return super().add_events(payloads)

            def close_session(self, session_id, **kwargs):
                order.append("close")
                closed.set()
                return super().close_session(session_id, **kwargs)

        provider = plugin.MemkitProvider({})
        provider._session_id = "s-1"
        provider._client = SlowClient()
        provider.sync_turn("I prefer pnpm for all projects", "Understood")
        self.assertTrue(started.wait(1))
        ending = threading.Thread(target=provider.on_session_end, args=([],))
        ending.start()
        try:
            self.assertFalse(closed.wait(0.05), "close overtook the pending evidence write")
        finally:
            release.set()
            ending.join(2)
            provider.shutdown()
        self.assertEqual(order, ["evidence", "close"])

    def test_session_end_does_not_close_after_a_failed_evidence_write(self):
        client = FakeClient(fail=True)
        provider = plugin.MemkitProvider({})
        provider._session_id = "s-1"
        provider._client = client
        provider.sync_turn("I prefer pnpm for all projects", "Understood")
        provider.shutdown()
        client.fail = False
        provider.on_session_end([])
        self.assertEqual(client.closed, [])

    def test_session_end_has_one_deadline_for_pending_evidence(self):
        started, release = threading.Event(), threading.Event()

        class SlowClient(FakeClient):
            def add_events(self, payloads):
                started.set()
                release.wait(2)
                return super().add_events(payloads)

        client = SlowClient()
        provider = plugin.MemkitProvider({})
        provider._session_id = "s-1"
        provider._client = client
        provider.sync_turn("I prefer pnpm for all projects", "Understood")
        self.assertTrue(started.wait(1))
        try:
            with patch.object(plugin, "SESSION_CLOSE_TIMEOUT", 0.02, create=True):
                provider.on_session_end([])
            self.assertEqual(client.closed, [])
        finally:
            release.set()
            provider.shutdown()


class TestBreaker(unittest.TestCase):
    def test_opens_after_five_failures_and_blocks(self):
        from memkit_hermes_plugin.client import Breaker

        breaker = Breaker(fails=5, cooldown=120)
        for _ in range(4):
            breaker.fail()
        self.assertTrue(breaker.allow())
        breaker.fail()
        self.assertFalse(breaker.allow())

    def test_a_success_resets_the_streak(self):
        from memkit_hermes_plugin.client import Breaker

        breaker = Breaker(fails=3)
        breaker.fail()
        breaker.fail()
        breaker.ok()
        breaker.fail()
        self.assertTrue(breaker.allow())

    def test_a_4xx_does_not_count_toward_opening(self):
        # An unknown id is the service answering, not failing.
        import urllib.error

        from memkit_hermes_plugin.client import Client, MemkitError

        client = Client("http://127.0.0.1:1", "k")
        error = urllib.error.HTTPError("u", 404, "nope", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            for _ in range(10):
                with self.assertRaises(MemkitError):
                    client.healthz()
        self.assertTrue(client.breaker.allow())

    def test_a_5xx_does_count(self):
        import urllib.error

        from memkit_hermes_plugin.client import Client, MemkitError

        client = Client("http://127.0.0.1:1", "k")
        error = urllib.error.HTTPError("u", 503, "down", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            for _ in range(5):
                with self.assertRaises(MemkitError):
                    client.healthz()
        self.assertFalse(client.breaker.allow())


if __name__ == "__main__":
    unittest.main(verbosity=2)
