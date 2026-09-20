"""Real Postgres retrieval boundaries before optional semantic provider egress."""

from __future__ import annotations

import json

import httpx
from psycopg.pq import TransactionStatus

from memkit import retrieval, store
from memkit.semantic import JevClient, JevReranker
from tests.fixtures import StubEmbedder, StubQdrant, seed_team


def test_reranker_only_sees_authorized_live_trusted_matching_rows(clean_database):
    conn = clean_database
    team = seed_team(conn)
    caller = team.principal("alice")
    with conn.transaction():
        wanted = store.add_memory(
            conn,
            scope_id=caller.own_entity_id,
            author_id=team.alice_id,
            text="needle allowed",
            kind="fact",
            source_role="user",
            context={"project": "x"},
        )
        for text, overrides in [
            ("needle private-bob", {"scope_id": team.scope_of("bob"), "author_id": team.bob_id}),
            ("needle expired", {"valid_until": "2020-01-01T00:00:00Z"}),
            ("needle assistant", {"source_role": "assistant"}),
            ("needle wrong-context", {"context": {"project": "y"}}),
            ("needle wrong-kind", {"kind": "preference"}),
        ]:
            options = {
                "scope_id": caller.own_entity_id,
                "author_id": team.alice_id,
                "kind": "fact",
                "source_role": "user",
                "context": {"project": "x"},
            }
            store.add_memory(conn, text=text, **(options | overrides))
    observed = []

    def handler(request):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        payload = json.loads(request.content)
        observed.extend(payload["state"]["candidates"])
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "answers": {
                    "0": {
                        "type": "score",
                        "score": 3,
                        "confidence": 1,
                        "probabilities": {"0": 0, "1": 0, "2": 0, "3": 1},
                    }
                },
            },
        )

    with JevClient("test", transport=httpx.MockTransport(handler)) as jev:
        result = retrieval.explain(
            conn,
            StubQdrant(),
            StubEmbedder(),
            query="needle",
            scope_ids=caller.scopes(),
            kinds=["fact"],
            expression={"field": "context.project", "op": "eq", "value": "x"},
            reranker=JevReranker(jev),
        )
    assert [c["text"] for c in observed] == ["needle allowed"]
    assert [c.id for c in result.chosen] == [wanted]


def test_provider_outage_preserves_real_retrieval_result(clean_database):
    conn = clean_database
    team = seed_team(conn)
    caller = team.principal("alice")
    with conn.transaction():
        store.add_memory(
            conn,
            scope_id=caller.own_entity_id,
            author_id=team.alice_id,
            text="Atlas database Postgres",
            kind="fact",
            source_role="user",
        )
    kwargs = {"query": "Atlas", "scope_ids": caller.scopes()}
    baseline = retrieval.explain(conn, StubQdrant(), StubEmbedder(), **kwargs)
    assert baseline.chosen
    with JevClient(
        "test", attempts=1, transport=httpx.MockTransport(lambda _: httpx.Response(529))
    ) as jev:
        result = retrieval.explain(
            conn, StubQdrant(), StubEmbedder(), reranker=JevReranker(jev), **kwargs
        )
    assert [c.as_dict() for c in result.chosen] == [c.as_dict() for c in baseline.chosen]
