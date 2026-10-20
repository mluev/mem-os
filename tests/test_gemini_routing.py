"""A Gemini key reaches the service it belongs to.

An AI Studio key works on the Developer API; a Vertex AI express key works
only on Vertex, with no project, and the Developer API refuses it with an
unbilled 403. The refusal is learned once per key, so the second call goes
straight to Vertex and an AI Studio key never leaves the Developer API.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from memkit import providers


class Refused(Exception):
    code = 403

    def __str__(self) -> str:
        return (
            "403 PERMISSION_DENIED. Requests to this API generativelanguage.googleapis.com "
            "method GenerateContent are blocked."
        )


def _response() -> SimpleNamespace:
    return SimpleNamespace(
        text='{"operations": []}',
        usage_metadata=SimpleNamespace(
            prompt_token_count=10, candidates_token_count=2, thoughts_token_count=0
        ),
        prompt_feedback=None,
    )


class GeminiRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(mock.patch.object(providers, "_EXPRESS_KEYS", set()))
        self.clients: list[dict] = []

        def client(**kwargs):
            self.clients.append(kwargs)
            vertex = kwargs.get("vertexai", False)
            express_key = kwargs.get("api_key") == "AQ.express"

            def generate(**_):
                if express_key and not vertex:
                    raise Refused()
                return _response()

            return SimpleNamespace(models=SimpleNamespace(generate_content=generate))

        self.enterContext(mock.patch("google.genai.Client", side_effect=client))

    def call(self, key: str) -> providers.ProviderResult:
        return providers.call_vertex(model="gemini-3.5-flash-lite", prompt="p", api_key=key)

    def test_an_express_key_is_retried_on_vertex_and_remembered(self) -> None:
        self.assertIsNone(self.call("AQ.express").error)
        self.assertEqual(
            [c.get("vertexai", False) for c in self.clients], [False, True], self.clients
        )
        self.assertNotIn("project", self.clients[1])
        self.clients.clear()
        self.assertIsNone(self.call("AQ.express").error)
        self.assertEqual([c.get("vertexai", False) for c in self.clients], [True])

    def test_an_ai_studio_key_stays_on_the_developer_api(self) -> None:
        self.assertIsNone(self.call("AIza-studio").error)
        self.assertEqual([c.get("vertexai", False) for c in self.clients], [False])

    def test_the_json_path_routes_the_same_way(self) -> None:
        result = providers.call_json(
            model="gemini-3.5-flash-lite",
            prompt="p",
            schema={"type": "object"},
            name="emit",
            gemini_api_key="AQ.express",
        )
        self.assertIsNone(result.error, result.error)
        self.assertEqual([c.get("vertexai", False) for c in self.clients], [False, True])

    def test_any_other_failure_is_not_retried(self) -> None:
        def broken(**kwargs):
            self.clients.append(kwargs)

            def generate(**_):
                raise RuntimeError("503 overloaded")

            return SimpleNamespace(models=SimpleNamespace(generate_content=generate))

        with (
            mock.patch("google.genai.Client", side_effect=broken),
            self.assertRaises(RuntimeError),
        ):
            providers._generate(
                api_key="AQ.express", project="", location="", model="m", contents="p"
            )
        self.assertEqual(len(self.clients), 1)


if __name__ == "__main__":
    unittest.main()
