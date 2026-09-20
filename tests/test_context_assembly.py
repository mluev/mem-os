"""Exercise context packing through the real authenticated API and PostgreSQL."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import httpx

from memkit import api, context_assembly, retrieval, vectors
from memkit.semantic import JevClient
from memkit.semantic_runtime import SemanticBlocks
from tests.httpharness import ApiTestCase
from tests.test_semantic import response


class TestContextAssembly(ApiTestCase):
    def configure(self, handler, mode="select"):
        provider = self.enterContext(
            JevClient("test", attempts=1, transport=httpx.MockTransport(handler))
        )
        api.app.state.semantic = SemanticBlocks(provider, context=mode)

    def raw_hits(self, ids):
        # Deliberately ignore vector scope/role filters and supply poisoned text.
        # PostgreSQL, not a supposedly well-behaved index, enforces this boundary.
        def query(collection_name, **kwargs):
            return SimpleNamespace(
                points=[
                    SimpleNamespace(id=mid, score=0.9, payload={"text": "POISONED INDEX CONTENT"})
                    for mid in ids
                ]
                if collection_name == vectors.RAW
                else []
            )

        self.qdrant.query_points = query

    def test_sources_reloaded_and_authorized_before_provider_egress(self):
        own = self.seed_message(
            content="Ledger uses PostgreSQL but keeps Redis only for temporary cache."
        )
        assistant = self.seed_message(role="assistant", content="Invented claim from assistant")
        foreign = self.client.post(
            "/v1/evidence/events",
            headers=self.as_bob,
            json={
                "session_id": "bob-private",
                "role": "user",
                "content": "BOB PRIVATE SOURCE",
            },
        ).json()["message_id"]
        self.raw_hits([own, assistant, foreign, 999999])
        seen = []

        def handler(request):
            payload = json.loads(request.content)
            seen.extend(c["text"] for c in payload["state"]["candidates"])
            return httpx.Response(
                200,
                json=response({k: {"type": "noul", "noul": 0.99} for k in payload["questions"]}),
            )

        self.configure(handler)
        result = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={
                "query": "Ledger cache",
                "include_raw": True,
                "budget_tokens": 100,
            },
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert seen == ["Ledger uses PostgreSQL but keeps Redis only for temporary cache."]
        assert [r["message_id"] for r in body["raw"]] == [own]
        assert body["raw"][0]["source_role"] == "user"
        assert body["raw"][0]["start_char"] == 0
        assert body["used_tokens"] <= 100
        assert body["memories"] == []
        run = self.db.execute(
            "SELECT abstained,timings FROM retrieval_runs WHERE id=%s", (body["retrieval_id"],)
        ).fetchone()
        assert not run["abstained"]
        assert run["timings"]["total_ms"] >= run["timings"]["context_ms"]

    def test_shared_budget_and_provider_outage_preserve_available_context(self):
        self.seed_memory(text="Ledger stores balances in PostgreSQL.")
        raw = self.seed_message(
            content="Ledger keeps Redis only for temporary cache; never put balances there."
        )
        self.raw_hits([raw])
        self.configure(lambda _: httpx.Response(529))
        result = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={
                "query": "Ledger",
                "include_raw": True,
                "budget_tokens": 100,
            },
        )
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["memories"] and body["raw"]
        expected = sum(
            retrieval._token_count(r["text"]) + 6 for r in body["memories"] + body["raw"]
        )
        assert body["used_tokens"] == expected <= 100

    def test_context_filter_applies_to_raw_before_model(self):
        good = self.seed_message(
            session_id="x", content="PostgreSQL is used by project x.", context={"project": "x"}
        )
        bad = self.seed_message(
            session_id="y", content="PRIVATE CONTEXT Y", context={"project": "y"}
        )
        self.raw_hits([good, bad])
        seen = []

        def handler(request):
            data = json.loads(request.content)
            seen.extend(c["text"] for c in data["state"]["candidates"])
            return httpx.Response(
                200, json=response({k: {"type": "noul", "noul": 1} for k in data["questions"]})
            )

        self.configure(handler)
        result = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={
                "query": "PostgreSQL",
                "include_raw": True,
                "filter": {"field": "context.project", "op": "eq", "value": "x"},
            },
        )
        assert result.status_code == 200, result.text
        assert seen == ["PostgreSQL is used by project x."]

    def test_sources_cannot_escape_the_shared_budget(self):
        text = "Ledger stores balances in PostgreSQL because transfers must remain atomic."
        mid = self.seed_message(content=text)
        memory = self.seed_memory(text="Ledger uses PostgreSQL.")
        self.db.execute(
            """INSERT INTO memory_evidence
            (memory_id,message_id,start_char,end_char,excerpt_sha256) VALUES (%s,%s,0,%s,%s)""",
            (memory, mid, len(text), hashlib.sha256(text.encode()).hexdigest()),
        )
        self.raw_hits([mid])
        self.configure(lambda _: httpx.Response(529))
        result = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={
                "query": "Ledger",
                "include_raw": True,
                "include_sources": True,
                "budget_tokens": 35,
            },
        )
        assert result.status_code == 200, result.text
        body = result.json()
        cost = sum(retrieval._token_count(r["text"]) + 6 for r in body["memories"] + body["raw"])
        cost += sum(
            retrieval._token_count(s["excerpt"]) + 6 for m in body["memories"] for s in m["sources"]
        )
        assert cost == body["used_tokens"] <= 35

    def test_every_context_mode_obeys_small_budgets_and_limits(self):
        text = "Ledger stores balances in PostgreSQL; Redis is only a temporary cache."
        message_id = self.seed_message(content=text)
        memory_id = self.seed_memory(text="Ledger stores balances in PostgreSQL.")
        self.db.execute(
            """INSERT INTO memory_evidence
               (memory_id,message_id,start_char,end_char,excerpt_sha256)
               VALUES (%s,%s,0,%s,%s)""",
            (memory_id, message_id, len(text), hashlib.sha256(text.encode()).hexdigest()),
        )
        self.raw_hits([message_id])

        def accepted(request):
            payload = json.loads(request.content)
            return httpx.Response(
                200,
                json=response(
                    {key: {"type": "noul", "noul": 0.99} for key in payload["questions"]}
                ),
            )

        for mode in ("off", "select", "provider_failure"):
            if mode == "off":
                api.app.state.semantic = None
            else:
                self.configure(accepted if mode == "select" else lambda _: httpx.Response(529))
            for raw in (False, True):
                for sources in (False, True):
                    for budget in (1, 20, 80):
                        for limit in (1, 3):
                            with self.subTest(
                                mode=mode, raw=raw, sources=sources, budget=budget, limit=limit
                            ):
                                result = self.client.post(
                                    "/v1/memories/search",
                                    headers=self.auth,
                                    json={
                                        "query": "Ledger PostgreSQL",
                                        "include_raw": raw,
                                        "include_sources": sources,
                                        "budget_tokens": budget,
                                        "limit": limit,
                                    },
                                )
                                self.assertEqual(result.status_code, 200, result.text)
                                body = result.json()
                                items = body["memories"] + body["raw"]
                                cost = sum(
                                    retrieval._token_count(item["text"]) + 6 for item in items
                                )
                                cost += sum(
                                    retrieval._token_count(source["excerpt"]) + 6
                                    for memory in body["memories"]
                                    for source in memory.get("sources", [])
                                )
                                self.assertLessEqual(len(items), limit)
                                self.assertEqual(body["used_tokens"], cost)
                                self.assertLessEqual(cost, budget)
                                if not sources:
                                    self.assertTrue(
                                        all("sources" not in item for item in body["memories"])
                                    )

    def test_no_raw_request_does_not_activate_context_provider(self):
        self.seed_memory(text="Ledger stores balances in PostgreSQL.")
        calls = []
        self.configure(lambda request: calls.append(request) or httpx.Response(529))
        result = self.client.post(
            "/v1/memories/search", headers=self.auth, json={"query": "Ledger"}
        )
        assert result.status_code == 200
        assert result.json()["memories"]
        assert calls == []

    def test_raw_without_semantic_mode_rechecks_scope_role_and_text(self):
        own = self.seed_message(content="The actual authorized user source")
        assistant = self.seed_message(role="assistant", content="An assistant invention")
        foreign = self.client.post(
            "/v1/evidence/events",
            headers=self.as_bob,
            json={"session_id": "bob", "role": "user", "content": "PRIVATE SOURCE"},
        ).json()["message_id"]
        self.raw_hits([own, assistant, foreign, 999999])
        result = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "user source", "include_raw": True},
        )
        assert result.status_code == 200, result.text
        raw = result.json()["raw"]
        assert [r["message_id"] for r in raw] == [own]
        assert raw[0]["text"] == "The actual authorized user source"


def test_passages_are_exact_and_do_not_split_a_long_sentence():
    text = "Short fact. " + ("long " * 270) + "except for caches. Next fact."
    spans = context_assembly.passages(text)
    assert spans
    assert "".join(text[a:b] for a, b in spans) == text
    assert any("except for caches." in text[a:b] for a, b in spans)
    assert context_assembly.passages("x" * 3000) == []
