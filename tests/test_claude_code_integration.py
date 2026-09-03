"""The Claude Code agent surface: skill, hooks, installer (decisions/0058).

Three claims worth a test:

* the installer lands the skill and hook where Claude Code looks, and refuses
  to clobber without --force;
* the SKILL.md's endpoints actually exist in api.py — prose drifts, and a
  skill teaching agents a dead endpoint is worse than no skill;
* capture reads only the transcript delta, reuses the importer's classifier
  (one source of truth for noise), advances its cursor only after the batch
  lands, and keeps idempotency keys so overlap is harmless.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class SkillContractTest(unittest.TestCase):
    def test_every_endpoint_the_skill_names_exists(self) -> None:
        skill = (INTEGRATION / "skills" / "mem-os" / "SKILL.md").read_text()
        api_source = (ROOT / "src" / "memkit" / "api.py").read_text()
        named = set(re.findall(r'"\$BASE(/[a-z0-9/:{}<>._-]+)"', skill, re.IGNORECASE))
        self.assertTrue(named, "the skill should name concrete endpoints")
        for path in named:
            route = re.sub(r"<[^>]+>", "{", path).split("{")[0].rstrip("/")
            self.assertIn(route, api_source, f"SKILL.md names a dead endpoint: {path}")

    def test_every_json_field_the_skill_sends_exists_in_the_model(self) -> None:
        """The endpoint-existence check above cannot catch a wrong field name.

        SKILL.md once told the model to PATCH with `expected_updated_at` while
        the API required `expected_revision` and forbade extra fields, so every
        correction the skill described returned 422 twice over. Field names are
        as much of a contract as paths.
        """
        from memkit import api

        models = {
            ("POST", "/v1/memories"): api.MemoryIn,
            ("PATCH", "/v1/memories/{}"): api.MemoryPatch,
            ("POST", "/v1/memories/search"): api.SearchIn,
            ("POST", "/v1/profiles/render"): api.ProfileIn,
            ("POST", "/v1/evidence/events:batch"): api.EvidenceBatchIn,
        }
        skill = (INTEGRATION / "skills" / "mem-os" / "SKILL.md").read_text()
        # Each curl block may continue over escaped newlines; join them first.
        joined = skill.replace("\\\n", " ")
        calls = re.findall(
            r"curl[^\n]*?-X (GET|POST|PATCH|DELETE) \"\$BASE([^\"]+)\"[^\n]*?-d '(\{.*?\})'",
            joined,
            re.DOTALL,
        )
        self.assertTrue(calls, "the skill should show request bodies")
        checked = 0
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
            checked += 1
        self.assertGreaterEqual(checked, 4)

    def test_skill_teaches_honest_provenance(self) -> None:
        skill = (INTEGRATION / "skills" / "mem-os" / "SKILL.md").read_text()
        self.assertIn('"source_role": "manual"', skill)
        self.assertIn("agent", skill)
        self.assertIn("include_untrusted", skill)


class CaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.hooks = load_hooks_module()
        self.tmp = Path(tempfile.mkdtemp())
        self.hooks.STATE_DIR = self.tmp / "state"
        self.transcript = self.tmp / "session.jsonl"
        self.cursor = self.tmp / "cursor.offset"

    def test_delta_classification_and_cursor(self) -> None:
        lines = [
            transcript_line("u1", "user", "запомни: мы используем pnpm везде"),
            transcript_line("a1", "assistant", "Понял, зафиксировал."),
            transcript_line("m1", "user", "meta line", isMeta=True),
            transcript_line("s1", "user", "sidechain", isSidechain=True),
            transcript_line("c1", "user", "<command-name>/clear</command-name>"),
        ]
        self.transcript.write_text("\n".join(lines) + "\n")
        events, offset = self.hooks._events_from_delta(self.transcript, self.cursor, "demo")
        self.assertEqual([e["external_id"] for e in events], ["u1", "a1"])
        self.assertEqual(events[0]["role"], "user")
        self.assertEqual(events[0]["context"], {"source_workspace": "demo"})
        self.assertEqual(events[0]["external_source"], "claude-code")

        # Advance the cursor, append one line: only the new line is read.
        self.cursor.write_text(str(offset))
        with self.transcript.open("a") as fh:
            fh.write(transcript_line("u2", "user", "и ещё: тесты только через pytest") + "\n")
        events, _ = self.hooks._events_from_delta(self.transcript, self.cursor, "demo")
        self.assertEqual([e["external_id"] for e in events], ["u2"])

    def test_capture_posts_batch_and_advances_cursor_only_on_success(self) -> None:
        self.transcript.write_text(transcript_line("u1", "user", "мы перешли на uv") + "\n")
        hook_json = json.dumps(
            {
                "transcript_path": str(self.transcript),
                "session_id": "cc-session-1",
                "cwd": "/x/demo",
            }
        )
        calls: list[tuple[str, dict | None]] = []

        def fake_post(base, key, path, payload, timeout):
            calls.append((path, payload))
            return {}

        cursor = self.hooks.STATE_DIR / "cc-session-1.offset"
        with (
            mock.patch.object(self.hooks, "_config", return_value=("http://x", "k")),
            mock.patch.object(self.hooks, "_post", side_effect=fake_post),
            mock.patch.object(self.hooks.sys, "stdin", new=_Stdin(hook_json)),
        ):
            self.hooks.capture(close=True)
        self.assertEqual(calls[0][0], "/v1/evidence/events:batch")
        self.assertEqual(calls[1][0], "/v1/sessions/cc-session-1/close")
        self.assertTrue(cursor.is_file())

        # A failing send must leave the cursor untouched.
        with self.transcript.open("a") as fh:
            fh.write(transcript_line("u2", "user", "ещё одна реплика для памяти") + "\n")
        before = cursor.read_text()

        def failing_post(base, key, path, payload, timeout):
            raise OSError("service down")

        with (
            mock.patch.object(self.hooks, "_config", return_value=("http://x", "k")),
            mock.patch.object(self.hooks, "_post", side_effect=failing_post),
            mock.patch.object(self.hooks.sys, "stdin", new=_Stdin(hook_json)),
            # main() is the fail-open boundary, not capture().
            contextlib.suppress(OSError),
        ):
            self.hooks.capture(close=False)
        self.assertEqual(cursor.read_text(), before)

    def test_main_is_fail_open(self) -> None:
        with (
            mock.patch.object(self.hooks, "_config", side_effect=OSError("boom")),
            mock.patch.object(self.hooks.sys, "stdin", new=_Stdin("{}")),
            mock.patch.object(self.hooks.sys, "argv", ["memkit_hooks.py", "capture"]),
        ):
            self.assertEqual(self.hooks.main(), 0)


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


if __name__ == "__main__":
    unittest.main()
