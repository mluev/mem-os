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

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "integrations" / "hermes" / "memkit"


def _load_plugin():
    """Import the provider with Hermes's two touchpoints stubbed out."""
    if "agent.memory_provider" not in sys.modules:
        agent = types.ModuleType("agent")
        provider_mod = types.ModuleType("agent.memory_provider")

        class MemoryProvider:  # minimal stand-in for the real ABC
            pass

        provider_mod.MemoryProvider = MemoryProvider
        agent.memory_provider = provider_mod
        sys.modules["agent"] = agent
        sys.modules["agent.memory_provider"] = provider_mod

    if "tools.registry" not in sys.modules:
        tools = types.ModuleType("tools")
        registry = types.ModuleType("tools.registry")
        registry.tool_error = lambda message, **extra: json.dumps({"error": str(message), **extra})
        tools.registry = registry
        sys.modules["tools"] = tools
        sys.modules["tools.registry"] = registry

    package = "memkit_hermes_plugin"
    spec = importlib.util.spec_from_file_location(
        package,
        str(PLUGIN / "__init__.py"),
        submodule_search_locations=[str(PLUGIN)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    spec.loader.exec_module(module)
    return module


plugin = _load_plugin()


class FakeClient:
    """Stands in for the HTTP client. Records what the provider tried to do."""

    def __init__(self, *, fail=False, memories=None):
        self.fail = fail
        self.memories = memories or []
        self.messages: list[dict] = []
        self.memories_added: list[dict] = []
        self.closed: list[str] = []
        self.searches: list[str] = []

    def _boom(self):
        from memkit_hermes_plugin.client import MemkitError

        raise MemkitError("service down")

    def search(self, query, **kwargs):
        self.searches.append(query)
        if self.fail:
            self._boom()
        return self.memories

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


class TestContract(unittest.TestCase):
    """What the ABC requires. Getting any of this wrong stops the plugin loading."""

    def test_the_four_abstract_members_exist(self):
        provider = plugin.MemkitProvider({})
        self.assertEqual(provider.name, "memkit")
        self.assertIsInstance(provider.is_available(), bool)
        self.assertTrue(callable(provider.initialize))
        self.assertTrue(callable(provider.get_tool_schemas))

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
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(provider.is_available())

    def test_backup_paths_needs_no_initialize_and_no_network(self):
        # hermes backup only walks HERMES_HOME; memkit's SQLite lives outside it, so
        # an undeclared path means a backup/restore cycle loses every memory.
        provider = plugin.MemkitProvider({"db_path": "~/dev/memkit/data/memkit.db"})
        paths = provider.backup_paths()
        self.assertEqual(len(paths), 1)
        self.assertTrue(paths[0].endswith("data/memkit.db"))
        self.assertNotIn("~", paths[0])


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

    def test_unknown_tool_is_an_error(self):
        provider = make_provider(client=FakeClient())
        self.assertIn("error", json.loads(provider.handle_tool_call("nope", {})))


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
