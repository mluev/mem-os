"""The Claude Code agent surface: skill, hooks, installer (decisions/0058).

What is worth a test here, and why each claim exists:

* the installer lands the skill and hook where Claude Code looks, and refuses to
  clobber without --force;
* SKILL.md's endpoints and **field names** exist in api.py -- prose drifts, and a
  skill teaching a model `expected_updated_at` when the API demands
  `expected_revision` fails at runtime with a 422 the model cannot diagnose;
* the capture payload validates against `api.MessageIn` and its context keys
  match what the bulk importer writes -- this is the drift guard that would have
  caught the old breakage, where hook and importer disagreed silently;
* `.memkit.toml` discovery stops at the git root, because a stray file above it
  would file one project's conversations into another project's *scope*, which is
  a permissions mistake rather than a configuration one;
* the recall heuristic abstains on the silent majority, because a recall that
  fires on every prompt gets switched off and then never fires at all;
* every hook path returns 0. A memory service must not be able to break an editor.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from unittest import mock

from memkit import remote

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations" / "claude-code"


def load_hooks_module():
    spec = importlib.util.spec_from_file_location(
        "memkit_hooks", INTEGRATION / "hooks" / "memkit_hooks.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def transcript_line(
    uuid: str,
    role: str,
    text: str,
    *,
    session: str = "cc-session-1",
    **extra,
) -> str:
    return json.dumps(
        {
            "type": role,
            "uuid": uuid,
            "sessionId": session,
            "timestamp": "2026-08-28T10:00:00Z",
            "cwd": "/Users/someone/dev/demo",
            "message": {"role": role, "content": text},
            **extra,
        }
    )


def importer_context_keys() -> set[str]:
    """The context keys `memkit import-claude-code` writes, read from its source.

    Read rather than restated: a literal copy of the key names here would pass
    forever after cli.py renamed one, which is the exact class of drift this file
    is for.
    """
    tree = ast.parse((ROOT / "src" / "memkit" / "cli.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "cmd_import"):
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            for keyword in call.keywords:
                if keyword.arg == "context" and isinstance(keyword.value, ast.Dict):
                    return {
                        key.value
                        for key in keyword.value.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    }
    raise AssertionError("cmd_import no longer passes a literal context dict")


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


class FakeClient:
    """A remote.Client stand-in. Routes are dicts, callables, or exceptions."""

    def __init__(self, routes: dict[str, object] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, str, object]] = []

    def get(self, path, params=None, *, timeout=None):
        return self._answer("GET", path, params)

    def post(self, path, body=None, *, timeout=None):
        return self._answer("POST", path, body)

    def _answer(self, method: str, path: str, body: object):
        self.calls.append((method, path, body))
        answer = self.routes.get(path)
        if isinstance(answer, BaseException):
            raise answer
        if callable(answer):
            return answer(body)
        return answer or {}

    def paths(self) -> list[str]:
        return [path for _method, path, _body in self.calls]


class HookTestCase(unittest.TestCase):
    """Shared plumbing: a fresh hooks module, isolated state, no stray env."""

    def setUp(self) -> None:
        self.hooks = load_hooks_module()
        self.tmp = Path(tempfile.mkdtemp())
        self.hooks.STATE_DIR = self.tmp / "state"
        for name in ("MEMKIT_RECALL", "MEMKIT_BASE_URL", "MEMKIT_API_KEY"):
            original = os.environ.pop(name, None)
            if original is not None:
                self.addCleanup(os.environ.__setitem__, name, original)

    def run_hook(self, function, payload: dict, client=None) -> str:
        """Drive one hook end to end and return whatever it printed."""
        stdout = io.StringIO()
        patches = [mock.patch.object(self.hooks.sys, "stdin", new=_Stdin(json.dumps(payload)))]
        if client is not None:
            patches.append(mock.patch.object(self.hooks.remote, "connect", return_value=client))
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            stack.enter_context(contextlib.redirect_stdout(stdout))
            function()
        return stdout.getvalue()


class InstallerTest(unittest.TestCase):
    def test_installs_skill_and_hook_and_respects_force(self) -> None:
        from memkit import cli

        home = Path(tempfile.mkdtemp()) / "claude"
        args = argparse.Namespace(claude_home=str(home), skills_home=None, force=False)
        self.assertEqual(cli.cmd_install_claude_code(args), 0)
        skill = home / "skills" / "mem-os" / "SKILL.md"
        hook = home / "memkit" / "memkit_hooks.py"
        self.assertTrue(skill.is_file())
        self.assertTrue(hook.is_file())
        # Second run without --force must refuse rather than clobber.
        self.assertEqual(cli.cmd_install_claude_code(args), 1)
        args.force = True
        self.assertEqual(cli.cmd_install_claude_code(args), 0)

    def test_the_installer_names_the_file_the_hooks_read(self) -> None:
        """The two halves of onboarding must agree on one path.

        They did not: the installer documented `~/.memkit` while `memkit setup`
        wrote `~/.config/memkit/client.env`, so a machine set up exactly as
        documented produced hooks with no key -- and because every hook path
        fails open, a silently inert integration rather than an error.
        """
        from memkit import cli, operations

        source = (ROOT / "src" / "memkit" / "cli.py").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_CONFIG_DIR / 'client.env'", source)
        self.assertEqual(
            operations.DEFAULT_CONFIG_DIR / "client.env",
            remote.CLIENT_ENV,
        )
        self.assertIn("api-keys create --user", source)
        self.assertTrue(hasattr(cli, "cmd_install_claude_code"))


class SkillContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.skill = (INTEGRATION / "skills" / "mem-os" / "SKILL.md").read_text(encoding="utf-8")

    def test_every_endpoint_the_skill_names_exists(self) -> None:
        from memkit.api import app

        paths = {re.sub(r"\{[^}]+\}", "{}", path) for path in app.openapi()["paths"]}
        named = set(re.findall(r'"\$BASE(/[a-z0-9/:{}<>._-]+)"', self.skill, re.IGNORECASE))
        self.assertTrue(named, "the skill should name concrete endpoints")
        for path in named:
            route = re.sub(r"<[^>]+>", "{}", path)
            self.assertIn(route, paths, f"SKILL.md names a dead endpoint: {path}")

    def test_every_json_field_the_skill_sends_exists_in_the_model(self) -> None:
        """The endpoint-existence check above cannot catch a wrong field name.

        SKILL.md once told the model to PATCH with `expected_updated_at` while
        the API required `expected_revision` and forbade extra fields, so every
        correction the skill described returned 422 twice over. Field names are
        as much of a contract as paths, and asserting them against
        `model_fields` rather than grepping prose is what makes the check hold
        when the prose is rewritten.
        """
        from memkit import api

        models = {
            ("POST", "/v1/memories"): api.MemoryIn,
            ("PATCH", "/v1/memories/{}"): api.MemoryPatch,
            ("POST", "/v1/memories/search"): api.SearchIn,
            ("POST", "/v1/profiles/render"): api.ProfileIn,
            ("POST", "/v1/entities/resolve"): api.ResolveIn,
            ("POST", "/v1/evidence/events:batch"): api.EvidenceBatchIn,
        }
        joined = self.skill.replace("\\\n", " ")
        calls = re.findall(
            r"curl[^\n]*?-X (GET|POST|PATCH|DELETE) \"\$BASE([^\"]+)\"[^\n]*?-d '(\{.*?\})'",
            joined,
            re.DOTALL,
        )
        self.assertTrue(calls, "the skill should show request bodies")
        seen_models = set()
        for method, path, body in calls:
            route = re.sub(r"<[^>]+>", "{}", path)
            model = models.get((method, route))
            self.assertIsNotNone(model, f"no model mapped for {method} {route}")
            payload = json.loads(body)
            for field in payload:
                self.assertIn(
                    field,
                    model.model_fields,
                    f"SKILL.md sends {field!r} to {method} {route}, which {model.__name__} "
                    "forbids (StrictModel rejects unknown fields)",
                )
            model.model_validate(payload)
            seen_models.add(model.__name__)
        for required in ("MemoryIn", "MemoryPatch", "SearchIn", "ProfileIn", "ResolveIn"):
            self.assertIn(required, seen_models, f"the skill shows no {required} body")

    def test_the_skill_teaches_the_scope_and_subject_split(self) -> None:
        """The two fields a team system can get catastrophically wrong.

        `scope` decides who may read a fact and `subject` decides who it is
        about; swapping them either leaks a private note or loses the team's
        record of a colleague (decisions/0061).
        """
        self.assertIn('"scope": "mem-os"', self.skill)
        self.assertIn('"subject": "sasha"', self.skill)
        self.assertIn("review", self.skill.casefold())

    def test_the_skill_shows_a_read_before_a_correction(self) -> None:
        read_at = self.skill.index('-X GET "$BASE/v1/memories/<id>"')
        patch_at = self.skill.index('-X PATCH "$BASE/v1/memories/<id>"')
        self.assertLess(read_at, patch_at, "expected_revision has to come from somewhere")
        self.assertIn("expected_revision", self.skill)
        self.assertNotIn("expected_updated_at", self.skill)

    def test_skill_teaches_honest_provenance(self) -> None:
        self.assertIn('"source_role": "manual"', self.skill)
        self.assertIn("agent", self.skill)
        self.assertIn("include_untrusted", self.skill)

    def test_the_skill_stays_short_enough_to_be_read(self) -> None:
        """A skill a model skims is a skill that guesses the half it skipped."""
        self.assertLess(len(self.skill), 8_000, "SKILL.md is drifting toward a manual")


class ConfigResolutionTest(HookTestCase):
    """The hook must not have opinions of its own about where the key lives.

    Precedence itself is proved in tests/test_remote_client.py; what matters here
    is that the hook goes through that one implementation, because the failure
    being guarded against is two clients looking in different places and the key
    now being an identity rather than a setting.
    """

    def test_the_hook_resolves_config_through_remote(self) -> None:
        source = (INTEGRATION / "hooks" / "memkit_hooks.py").read_text(encoding="utf-8")
        self.assertIn("from memkit import agent_remote as remote", source)
        self.assertNotIn(".memkit", source.replace(".memkit.toml", ""))
        self.assertIs(self.hooks.remote.connect, remote.connect)
        self.assertIs(self.hooks.remote.RemoteError, remote.RemoteError)

    def test_no_key_means_no_requests_at_all(self) -> None:
        with mock.patch.object(self.hooks.remote, "connect", return_value=None):
            self.assertEqual(
                self.run_hook(
                    self.hooks.session_start, {"source": "startup", "cwd": str(self.tmp)}
                ),
                "",
            )


class RepoConfigTest(HookTestCase):
    """`.memkit.toml`: which scope the conversations in this checkout belong to."""

    def _repo(self) -> Path:
        repo = self.tmp / "outer" / "repo"
        (repo / "sub" / "deep").mkdir(parents=True)
        (repo / ".git").mkdir()
        (self.tmp / "outer" / ".memkit.toml").write_text('[memkit]\nentity = "wrong-project"\n')
        return repo

    def test_discovery_walks_up_to_the_repository_root(self) -> None:
        repo = self._repo()
        (repo / ".memkit.toml").write_text(
            '[memkit]\nentity = "mem-os"\ncapture = true\nrecall = false\n'
        )
        settings = self.hooks.repo_settings(repo / "sub" / "deep")
        self.assertEqual(settings.entity, "mem-os")
        self.assertEqual(settings.root, repo.resolve())
        self.assertTrue(settings.capture)
        self.assertFalse(settings.recall)

    def test_discovery_stops_at_the_git_root(self) -> None:
        """A file above the repository must not be able to redirect its scope."""
        repo = self._repo()
        settings = self.hooks.repo_settings(repo / "sub")
        self.assertIsNone(settings.entity)
        self.assertEqual(settings.root, repo.resolve())
        self.assertEqual(settings.name, "repo")

    def test_capture_can_be_switched_off_and_recall_on(self) -> None:
        repo = self._repo()
        (repo / ".memkit.toml").write_text("[memkit]\ncapture = false\nrecall = true\n")
        settings = self.hooks.repo_settings(repo)
        self.assertFalse(settings.capture)
        self.assertTrue(settings.recall)
        self.assertIsNone(settings.entity)

    def test_the_environment_can_enable_recall_without_a_file(self) -> None:
        repo = self._repo()
        os.environ["MEMKIT_RECALL"] = "1"
        self.assertTrue(self.hooks.repo_settings(repo).recall)

    def test_malformed_toml_degrades_to_defaults(self) -> None:
        repo = self._repo()
        (repo / ".memkit.toml").write_text("[memkit\nentity = ")
        settings = self.hooks.repo_settings(repo)
        self.assertIsNone(settings.entity)
        self.assertTrue(settings.capture)


class ScopeResolutionTest(HookTestCase):
    ENTITIES: ClassVar[list[dict]] = [
        {"slug": "mem-os", "name": "Mem OS", "aliases": ["memkit"], "writable": True},
        {"slug": "secret-lab", "name": "Secret Lab", "aliases": [], "writable": False},
        {"slug": "sasha", "name": "Sasha", "aliases": [], "writable": False},
    ]

    def repo(self, **kwargs) -> object:
        defaults = {
            "root": self.tmp,
            "name": "demo",
            "entity": None,
            "capture": True,
            "recall": False,
        }
        return self.hooks.Repo(**{**defaults, **kwargs})

    def test_a_configured_entity_is_used_when_writable(self) -> None:
        self.assertEqual(
            self.hooks.resolve_scope(self.repo(entity="mem-os"), self.ENTITIES), "mem-os"
        )

    def test_an_explicit_entity_is_preserved_for_server_authorization(self) -> None:
        for entity in ("secret-lab", "not-a-thing"):
            self.assertEqual(
                self.hooks.resolve_scope(self.repo(entity=entity), self.ENTITIES), entity
            )

    def test_the_repository_name_resolves_as_an_alias(self) -> None:
        """The same fallback `memkit import-claude-code` applies to the same files."""
        self.assertEqual(
            self.hooks.resolve_scope(self.repo(name="memkit"), self.ENTITIES), "mem-os"
        )
        self.assertEqual(
            self.hooks.resolve_scope(self.repo(name="Mem OS"), self.ENTITIES), "mem-os"
        )

    def test_an_unknown_repository_name_is_private(self) -> None:
        self.assertIsNone(self.hooks.resolve_scope(self.repo(name="unrelated"), self.ENTITIES))

    def test_the_entity_list_is_cached_for_the_session(self) -> None:
        client = FakeClient({"/v1/entities": {"items": self.ENTITIES}})
        first = self.hooks.entity_cache(client, "s-1")
        second = self.hooks.entity_cache(client, "s-1")
        self.assertEqual(first, second)
        self.assertEqual(client.paths().count("/v1/entities"), 1)

    def test_an_unreachable_service_caches_nothing(self) -> None:
        client = FakeClient({"/v1/entities": remote.RemoteError("down")})
        self.assertEqual(self.hooks.entity_cache(client, "s-1"), [])
        self.assertEqual(client.paths().count("/v1/entities"), 1)
        self.assertEqual(self.hooks.entity_cache(client, "s-1"), [])
        self.assertEqual(client.paths().count("/v1/entities"), 2)

    def test_a_hostile_session_id_cannot_escape_the_state_directory(self) -> None:
        key = self.hooks._state_key("../../etc/passwd")
        self.assertNotIn("/", key)
        self.assertEqual((self.hooks.STATE_DIR / key).parent, self.hooks.STATE_DIR)


class SessionStartTest(HookTestCase):
    PROFILE: ClassVar[dict] = {
        "blocks": {
            "about": [{"id": "1", "text": "Works in Tashkent", "scope": "Maga"}],
            "style": [{"id": "2", "text": "Wants comments that say why", "scope": "Maga"}],
            "team": [],
            "project": [{"id": "3", "text": "Postgres is the source of truth", "scope": "Mem OS"}],
            "recent": [{"id": "4", "text": "Moved the schema to v1", "scope": "Mem OS"}],
        },
        "used_tokens": 40,
        "budget_tokens": 600,
    }

    def client(self) -> FakeClient:
        return FakeClient(
            {
                "/v1/profiles/render": self.PROFILE,
                "/v1/entities": {
                    "items": [{"slug": "mem-os", "name": "Mem OS", "aliases": [], "writable": True}]
                },
            }
        )

    def repo_dir(self) -> Path:
        repo = self.tmp / "mem-os"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        return repo

    def test_it_renders_the_five_headed_sections(self) -> None:
        out = self.run_hook(
            self.hooks.session_start,
            {"source": "startup", "session_id": "s-1", "cwd": str(self.repo_dir())},
            self.client(),
        )
        self.assertIn("<mem-os-context>", out)
        self.assertIn("About you:", out)
        self.assertIn("How you like to work:", out)
        self.assertIn("This project: Mem OS:", out)
        self.assertIn("Recently:", out)
        self.assertIn("</mem-os-context>", out)

    def test_an_empty_block_prints_no_heading(self) -> None:
        """An empty "Team rules:" asserts the team has none. It never said that."""
        out = self.run_hook(
            self.hooks.session_start,
            {"source": "startup", "session_id": "s-1", "cwd": str(self.repo_dir())},
            self.client(),
        )
        self.assertNotIn("Team rules:", out)

    def test_it_renders_after_a_compaction(self) -> None:
        """Nothing else puts the block back once compaction drops it.

        The window after a compact is exactly the window in which the model has
        forgotten the user, so `compact` is the source that most needs the hook.
        """
        out = self.run_hook(
            self.hooks.session_start,
            {"source": "compact", "session_id": "s-1", "cwd": str(self.repo_dir())},
            self.client(),
        )
        self.assertIn("<mem-os-context>", out)

    def test_every_documented_source_renders(self) -> None:
        for source in ("startup", "resume", "clear", "compact", "fork"):
            with self.subTest(source=source):
                out = self.run_hook(
                    self.hooks.session_start,
                    {"source": source, "session_id": "s-1", "cwd": str(self.repo_dir())},
                    self.client(),
                )
                self.assertIn("<mem-os-context>", out)

    def test_an_unknown_source_prints_nothing_and_asks_nothing(self) -> None:
        client = self.client()
        out = self.run_hook(
            self.hooks.session_start,
            {"source": "teleported", "session_id": "s-1", "cwd": str(self.repo_dir())},
            client,
        )
        self.assertEqual(out, "")
        self.assertEqual(client.calls, [])

    def test_the_status_line_names_the_active_scope(self) -> None:
        """Private and shared are one field apart, and the model cannot see which."""
        shared = self.run_hook(
            self.hooks.session_start,
            {"source": "startup", "session_id": "s-1", "cwd": str(self.repo_dir())},
            self.client(),
        )
        self.assertIn('saved to "mem-os"', shared)
        self.assertIn("review queue", shared)

        elsewhere = self.tmp / "unrelated"
        elsewhere.mkdir()
        (elsewhere / ".git").mkdir()
        private = self.run_hook(
            self.hooks.session_start,
            {"source": "startup", "session_id": "s-2", "cwd": str(elsewhere)},
            self.client(),
        )
        self.assertIn("private to you", private)

    def test_an_empty_profile_prints_nothing(self) -> None:
        client = FakeClient(
            {
                "/v1/profiles/render": {"blocks": {name: [] for name in self.hooks.BLOCKS}},
                "/v1/entities": {"items": []},
            }
        )
        out = self.run_hook(
            self.hooks.session_start,
            {"source": "startup", "session_id": "s-1", "cwd": str(self.repo_dir())},
            client,
        )
        self.assertEqual(out, "")

    def test_it_asks_for_every_block_and_names_the_workspace(self) -> None:
        client = self.client()
        self.run_hook(
            self.hooks.session_start,
            {"source": "startup", "session_id": "s-1", "cwd": str(self.repo_dir())},
            client,
        )
        body = next(b for _m, path, b in client.calls if path == "/v1/profiles/render")
        self.assertEqual(body["blocks"], self.hooks.BLOCKS)
        self.assertEqual(body["workspace"], "mem-os")
        self.assertEqual(body["budget_tokens"], self.hooks.PROFILE_BUDGET)

    def _rendered(self, filler: str) -> tuple[str, int]:
        """A block whose item text fills PROFILE_BUDGET exactly, and its cost."""
        from memkit.retrieval import _token_count

        count = max(1, self.hooks.PROFILE_BUDGET // _token_count(filler))
        items = [{"id": str(n), "text": filler, "scope": "Mem OS"} for n in range(count)]
        names = self.hooks.BLOCKS
        blocks = {name: items[index :: len(names)] for index, name in enumerate(names)}
        repo = self.hooks.Repo(
            root=self.tmp, name="mem-os", entity="mem-os", capture=True, recall=False
        )
        block = self.hooks.render_context({"blocks": blocks}, repo, "mem-os")
        return block, _token_count(block)

    def test_a_full_budget_still_fits_the_block_cap(self) -> None:
        """A budget the server honours and the hook then blows is not a budget.

        Counted with the same function the service spends the budget with, so a
        heading, bullet or preamble added here has to be paid for out of the
        difference between the two constants.
        """
        block, used = self._rendered(
            "The user prefers explicit configuration over convention in every service"
        )
        self.assertGreater(used, self.hooks.PROFILE_BUDGET, "the fixture must fill the budget")
        self.assertLessEqual(used, self.hooks.MAX_BLOCK_TOKENS, block[:400])

    def test_many_tiny_facts_cannot_blow_the_cap_through_bullets(self) -> None:
        """The case a token budget alone does not bound.

        `budget_tokens` is spent on item text; every bullet and newline the hook
        adds is unbudgeted, so a budget spent on 200 three-word facts would buy
        200 bullets. MAX_ITEMS_PER_BLOCK is what makes the block's size bounded
        by construction rather than by hoping facts are long.
        """
        _block, used = self._rendered("Uses pnpm")
        self.assertLessEqual(used, self.hooks.MAX_BLOCK_TOKENS)


class CaptureTest(HookTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.transcript = self.tmp / "session.jsonl"
        self.cursor = self.tmp / "cursor.offset"

    def hook_payload(self) -> dict:
        return {
            "transcript_path": str(self.transcript),
            "session_id": "cc-session-1",
            "cwd": "/x/demo",
        }

    def test_delta_classification_and_cursor(self) -> None:
        lines = [
            transcript_line("u1", "user", "запомни: мы используем pnpm везде"),
            transcript_line("a1", "assistant", "Понял, зафиксировал."),
            transcript_line("m1", "user", "meta line", isMeta=True),
            transcript_line("s1", "user", "sidechain", isSidechain=True),
            transcript_line("c1", "user", "<command-name>/clear</command-name>"),
        ]
        self.transcript.write_text("\n".join(lines) + "\n")
        events, offset = self.hooks.events_from_delta(self.transcript, self.cursor, "demo")
        self.assertEqual([e["external_id"] for e in events], ["u1", "a1"])
        self.assertEqual(events[0]["role"], "user")
        self.assertEqual(events[0]["context"], {"source_workspace": "demo"})
        self.assertEqual(events[0]["external_source"], "claude-code")

        # Advance the cursor, append one line: only the new line is read.
        self.cursor.write_text(str(offset))
        with self.transcript.open("a") as fh:
            fh.write(transcript_line("u2", "user", "и ещё: тесты только через pytest") + "\n")
        events, _ = self.hooks.events_from_delta(self.transcript, self.cursor, "demo")
        self.assertEqual([e["external_id"] for e in events], ["u2"])

    def test_the_payload_is_exactly_what_the_api_and_the_importer_accept(self) -> None:
        """The drift guard. The old hook and the API disagreed and nobody noticed.

        Both halves matter: a key the model rejects is a 422 the hook swallows
        (it fails open), and a *context* key the importer does not write splits
        the same conversation across two shapes, so a workspace filter matches
        the backfill and misses the live capture.
        """
        from memkit import api

        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        events, _ = self.hooks.events_from_delta(self.transcript, self.cursor, "demo", "mem-os")
        self.assertTrue(events)
        for event in events:
            self.assertLessEqual(set(event), set(api.MessageIn.model_fields))
            self.assertLessEqual(set(event["context"]), importer_context_keys())
            api.MessageIn.model_validate(event)
        self.assertEqual(events[0]["scope"], "mem-os")

    def test_no_scope_key_is_sent_when_the_session_is_private(self) -> None:
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        events, _ = self.hooks.events_from_delta(self.transcript, self.cursor, "demo", None)
        self.assertNotIn("scope", events[0])

    def test_capture_posts_the_batch_scoped_and_then_closes(self) -> None:
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        repo = self.tmp / "mem-os"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".memkit.toml").write_text('[memkit]\nentity = "mem-os"\n')
        client = FakeClient(
            {
                "/v1/entities": {
                    "items": [{"slug": "mem-os", "name": "Mem OS", "aliases": [], "writable": True}]
                },
                "/v1/evidence/events:batch": {"count": 1},
                "/v1/sessions/cc-session-1/close": {"status": "queued"},
            }
        )
        payload = {**self.hook_payload(), "cwd": str(repo)}
        self.run_hook(lambda: self.hooks.capture(close=True), payload, client)
        batch = next(b for _m, p, b in client.calls if p == "/v1/evidence/events:batch")
        self.assertEqual(batch["events"][0]["scope"], "mem-os")
        self.assertIn("/v1/sessions/cc-session-1/close", client.paths())
        self.assertTrue((self.hooks.STATE_DIR / "cc-session-1.offset").is_file())

    def test_a_forbidden_implicit_workspace_falls_back_to_private(self) -> None:
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        bodies: list[dict] = []

        def batch(body):
            bodies.append(body)
            if any("scope" in event for event in body["events"]):
                raise remote.RemoteError("http 403", status=403)
            return {"count": len(body["events"])}

        client = FakeClient(
            {
                "/v1/entities": {
                    "items": [{"slug": "mem-os", "name": "Mem OS", "aliases": [], "writable": True}]
                },
                "/v1/evidence/events:batch": batch,
            }
        )
        repo = self.tmp / "mem-os"
        repo.mkdir()
        (repo / ".git").mkdir()
        self.run_hook(
            lambda: self.hooks.capture(close=False),
            {**self.hook_payload(), "cwd": str(repo)},
            client,
        )
        self.assertEqual(len(bodies), 2)
        self.assertNotIn("scope", bodies[1]["events"][0])
        self.assertTrue((self.hooks.STATE_DIR / "cc-session-1.offset").is_file())

    def test_a_forbidden_explicit_scope_never_retries_privately_or_closes(self) -> None:
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        repo = self.tmp / "explicit"
        repo.mkdir()
        (repo / ".memkit.toml").write_text('[memkit]\nentity = "secret-lab"\n')
        client = FakeClient(
            {
                "/v1/entities": {"items": []},
                "/v1/evidence/events:batch": remote.RemoteError("http 403", status=403),
            }
        )
        with self.assertRaises(remote.RemoteError):
            self.run_hook(
                lambda: self.hooks.capture(close=True),
                {**self.hook_payload(), "cwd": str(repo)},
                client,
            )
        self.assertEqual(client.paths().count("/v1/evidence/events:batch"), 1)
        self.assertNotIn("/v1/sessions/cc-session-1/close", client.paths())
        self.assertFalse((self.hooks.STATE_DIR / "cc-session-1.offset").exists())

    def test_the_cursor_only_advances_after_every_batch_lands(self) -> None:
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        cursor = self.hooks.STATE_DIR / "cc-session-1.offset"
        ok = FakeClient({"/v1/evidence/events:batch": {"count": 1}, "/v1/entities": {"items": []}})
        self.run_hook(lambda: self.hooks.capture(close=False), self.hook_payload(), ok)
        before = cursor.read_text()

        with self.transcript.open("a") as fh:
            fh.write(transcript_line("u2", "user", "ещё одна реплика для памяти") + "\n")
        down = FakeClient(
            {
                "/v1/entities": {"items": []},
                "/v1/evidence/events:batch": remote.RemoteError("service down"),
            }
        )
        with contextlib.suppress(remote.RemoteError):
            self.run_hook(lambda: self.hooks.capture(close=False), self.hook_payload(), down)
        self.assertEqual(cursor.read_text(), before)

    def test_capture_off_still_closes_the_session(self) -> None:
        """`capture = false` is about evidence, not about leaving a session open."""
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        repo = self.tmp / "quiet"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".memkit.toml").write_text("[memkit]\ncapture = false\n")
        client = FakeClient({"/v1/sessions/cc-session-1/close": {"status": "queued"}})
        self.run_hook(
            lambda: self.hooks.capture(close=True),
            {**self.hook_payload(), "cwd": str(repo)},
            client,
        )
        self.assertEqual(client.paths(), ["/v1/sessions/cc-session-1/close"])

    def test_session_end_closes_even_when_stop_already_flushed_everything(self) -> None:
        """The bug the old hook had: it only closed when it had just sent something.

        Stop fires after every response, so by SessionEnd the delta is empty --
        and the session was therefore never closed, leaving the tail unextracted.
        """
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        client = FakeClient(
            {
                "/v1/entities": {"items": []},
                "/v1/evidence/events:batch": {"count": 1},
                "/v1/sessions/cc-session-1/close": {"status": "queued"},
            }
        )
        self.run_hook(lambda: self.hooks.capture(close=False), self.hook_payload(), client)
        self.run_hook(lambda: self.hooks.capture(close=True), self.hook_payload(), client)
        self.assertIn("/v1/sessions/cc-session-1/close", client.paths())

    def test_closing_an_unknown_session_is_not_an_error(self) -> None:
        client = FakeClient(
            {"/v1/sessions/cc-session-1/close": remote.RemoteError("http 404", status=404)}
        )
        self.hooks._close(client, "cc-session-1")


class RecallTest(HookTestCase):
    ENTITIES: ClassVar[list[dict]] = [
        {"slug": "mem-os", "name": "Mem OS", "aliases": ["memkit"], "writable": True}
    ]

    def setUp(self) -> None:
        super().setUp()
        self.repo = self.tmp / "mem-os"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / ".memkit.toml").write_text('[memkit]\nentity = "mem-os"\nrecall = true\n')

    def client(self, memories=None) -> FakeClient:
        return FakeClient(
            {
                "/v1/entities": {"items": self.ENTITIES},
                "/v1/memories/search": {
                    "memories": memories
                    if memories is not None
                    else [{"id": "m-1", "text": "We chose Postgres over SQLite"}]
                },
            }
        )

    def prompt(self, text: str, client=None, session="s-1") -> str:
        return self.run_hook(
            self.hooks.recall,
            {"prompt": text, "session_id": session, "cwd": str(self.repo)},
            client if client is not None else self.client(),
        )

    def test_a_decision_phrase_fires(self) -> None:
        out = self.prompt("what did we decide about the storage engine?")
        payload = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(payload["hookEventName"], "UserPromptSubmit")
        self.assertIn("Postgres", payload["additionalContext"])

    def test_a_russian_decision_phrase_fires(self) -> None:
        self.assertIn("hookSpecificOutput", self.prompt("напомни, что мы решили про схему"))

    def test_an_alias_hit_fires(self) -> None:
        self.assertIn("hookSpecificOutput", self.prompt("how does memkit route scoped writes"))

    def test_a_slash_command_abstains(self) -> None:
        client = self.client()
        self.assertEqual(self.prompt("/review the current diff please", client), "")
        self.assertNotIn("/v1/memories/search", client.paths())

    def test_a_short_prompt_abstains(self) -> None:
        client = self.client()
        self.assertEqual(self.prompt("ok go", client), "")
        self.assertNotIn("/v1/memories/search", client.paths())

    def test_an_ordinary_instruction_abstains(self) -> None:
        """The silent majority. Firing here is what makes users switch recall off."""
        client = self.client()
        self.assertEqual(self.prompt("add a docstring to the retrieval module", client), "")
        self.assertNotIn("/v1/memories/search", client.paths())

    def test_recall_is_off_unless_asked_for(self) -> None:
        (self.repo / ".memkit.toml").write_text('[memkit]\nentity = "mem-os"\n')
        client = self.client()
        self.assertEqual(self.prompt("what did we decide about storage?", client), "")
        self.assertEqual(client.calls, [])

    def test_an_already_injected_id_is_not_repeated(self) -> None:
        first = self.prompt("what did we decide about the storage engine?")
        self.assertIn("Postgres", first)
        self.assertEqual(self.prompt("what did we decide about the storage engine?"), "")

    def test_an_empty_result_prints_nothing(self) -> None:
        self.assertEqual(self.prompt("what did we decide about storage?", self.client([])), "")

    def test_it_asks_for_the_measured_budget(self) -> None:
        client = self.client()
        self.prompt("what did we decide about the storage engine?", client)
        body = next(b for _m, path, b in client.calls if path == "/v1/memories/search")
        self.assertEqual(body["limit"], self.hooks.RECALL_LIMIT)
        self.assertEqual(body["budget_tokens"], self.hooks.RECALL_BUDGET)
        self.assertEqual(self.hooks.RECALL_TIMEOUT, 0.4)

    def test_a_slow_service_produces_no_output_rather_than_a_late_one(self) -> None:
        """Late context is worse than none: the turn has already been sent."""
        server, base_url = _slow_service(delay=2.0)
        self.addCleanup(server.shutdown)
        client = remote.Client(base_url, "k", timeout=self.hooks.RECALL_TIMEOUT)
        # The alias list comes from disk, so only the search itself is timed.
        self.hooks.STATE_DIR.mkdir(parents=True, exist_ok=True)
        (self.hooks.STATE_DIR / "s-1.entities.json").write_text(
            json.dumps({"fetched_at": time.time(), "items": self.ENTITIES})
        )
        started = time.monotonic()
        with contextlib.suppress(remote.RemoteError):
            out = self.prompt("what did we decide about the storage engine?", client)
            self.assertEqual(out, "")
        self.assertLess(time.monotonic() - started, 1.5)


class FailOpenTest(HookTestCase):
    """`main()` returns 0 on every path. Nothing else about a hook matters more."""

    def _main(self, command: str, connect_result) -> int:
        stderr = io.StringIO()
        with (
            mock.patch.object(self.hooks.sys, "argv", ["memkit_hooks.py", command]),
            mock.patch.object(
                self.hooks.sys,
                "stdin",
                new=_Stdin(
                    json.dumps(
                        {
                            "source": "startup",
                            "session_id": "s-1",
                            "prompt": "what did we decide about storage?",
                            "cwd": str(self.tmp),
                        }
                    )
                ),
            ),
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            if isinstance(connect_result, BaseException):
                with mock.patch.object(self.hooks.remote, "connect", side_effect=connect_result):
                    return self.hooks.main()
            with mock.patch.object(self.hooks.remote, "connect", return_value=connect_result):
                return self.hooks.main()

    def test_an_unreachable_service_is_survivable(self) -> None:
        down = FakeClient(
            dict.fromkeys(
                ("/v1/profiles/render", "/v1/entities", "/v1/memories/search"),
                remote.RemoteError("[Errno 61] Connection refused"),
            )
        )
        for command in ("session-start", "capture", "session-end", "recall"):
            with self.subTest(command=command):
                self.assertEqual(self._main(command, down), 0)

    def test_a_500_is_survivable(self) -> None:
        broken = FakeClient(
            dict.fromkeys(
                ("/v1/profiles/render", "/v1/entities", "/v1/memories/search"),
                remote.RemoteError("http 500", status=500),
            )
        )
        for command in ("session-start", "capture", "session-end", "recall"):
            with self.subTest(command=command):
                self.assertEqual(self._main(command, broken), 0)

    def test_malformed_json_from_the_service_is_survivable(self) -> None:
        garbage = FakeClient(
            dict.fromkeys(
                ("/v1/profiles/render", "/v1/entities", "/v1/memories/search"),
                remote.RemoteError("response was not JSON"),
            )
        )
        for command in ("session-start", "capture", "session-end", "recall"):
            with self.subTest(command=command):
                self.assertEqual(self._main(command, garbage), 0)

    def test_a_profile_of_the_wrong_shape_is_survivable(self) -> None:
        """The failure this rewrite exists to fix: the response shape changed.

        `{stable, dynamic}` became `{blocks: {...}}` and the old hook read keys
        that were simply gone.
        """
        wrong = FakeClient(
            {"/v1/profiles/render": {"stable": ["nope"], "dynamic": None}, "/v1/entities": {}}
        )
        self.assertEqual(self._main("session-start", wrong), 0)

    def test_a_broken_config_lookup_is_survivable(self) -> None:
        self.assertEqual(self._main("capture", OSError("boom")), 0)

    def test_an_unknown_command_is_survivable(self) -> None:
        self.assertEqual(self._main("teleport", None), 0)

    def test_malformed_hook_input_is_survivable(self) -> None:
        with (
            mock.patch.object(self.hooks.sys, "argv", ["memkit_hooks.py", "session-start"]),
            mock.patch.object(self.hooks.sys, "stdin", new=_Stdin("not json at all")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(self.hooks.main(), 0)


def _slow_service(*, delay: float) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self) -> None:
            time.sleep(delay)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args: object) -> None:
            """Silence."""

        def handle_one_request(self) -> None:
            # The client hangs up on timeout, which is the point of the test.
            with contextlib.suppress(OSError):
                super().handle_one_request()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


if __name__ == "__main__":
    unittest.main()
