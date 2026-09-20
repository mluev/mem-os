"""Workflow decisions at real database boundaries, with an offline semantic provider."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest
from psycopg.pq import TransactionStatus

from memkit import extract, judge, outbox, providers, store
from memkit.config import Settings
from memkit.semantic import JevClient
from memkit.semantic_runtime import SemanticBlocks, from_settings
from tests.fixtures import HashEmbedder, apply, fake_provider, make_session, seed_team
from tests.test_semantic import candidate, response, score, support
from tests.test_semantic_candidates import ScoredStub


def relation(label="equivalent"):
    return {
        "type": "choice",
        "choice": label,
        "confidence": 1,
        "probabilities": {
            k: int(k == label)
            for k in ("equivalent", "addition", "correction", "conflict", "unrelated")
        },
    }


@pytest.mark.parametrize(
    "mode,label,http_status,expected",
    [
        ("verify", "equivalent", 200, (0, 1)),
        ("verify", "conflict", 200, (1, 0)),
        ("verify", "equivalent", 529, (1, 0)),
        ("shadow", "conflict", 200, (0, 1)),
    ],
)
def test_dedup_changes_actual_write_only_after_confirmation(
    clean_database, mode, label, http_status, expected
):
    conn = clean_database
    team = seed_team(conn)
    make_session(conn, team)
    scope = team.scope_of("alice")
    with conn.transaction():
        original = store.add_memory(
            conn,
            scope_id=scope,
            author_id=team.alice_id,
            text="Alice prefers tea.",
            kind="preference",
            source_role="user",
        )
        message, _, _ = store.add_message(
            conn,
            session_id="s-1",
            user_id=team.alice_id,
            scope_id=scope,
            agent_id="chat",
            role="user",
            content="Alice likes tea.",
        )
    op = judge.Op(
        op="ADD",
        reason="stated",
        text="Alice likes tea.",
        kind="preference",
        evidence=[{"message_id": message, "start_char": 0, "end_char": 15}],
    )
    vectors, embedder = ScoredStub(), HashEmbedder()
    outbox.drain(conn, vectors, embedder)
    events = []

    def handler(request):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        payload = json.loads(request.content)
        assert payload["state"]["pairs"] == [
            {"existing": "Alice prefers tea.", "incoming": "Alice likes tea."}
        ]
        return httpx.Response(http_status, json=response({"0": relation(label)}))

    with JevClient("test", attempts=1, transport=httpx.MockTransport(handler)) as client:
        blocks = SemanticBlocks(client, dedup=mode, observer=events.append)
        planned = extract.plan_dedup(
            conn,
            ops=[op],
            scope_id=scope,
            client=vectors,
            embedder=embedder,
            threshold=0.9,
            semantic=blocks,
        )
        with conn.transaction():
            outcome = apply(conn, team, [op], source_message_ids=[message], dedup_hits=planned)
    assert (outcome.added, outcome.deduplicated) == expected
    linked = conn.execute(
        "SELECT memory_id FROM memory_evidence WHERE message_id=%s", (message,)
    ).fetchall()
    assert len(linked) == 1
    assert (str(linked[0]["memory_id"]) == original) == bool(expected[1])
    assert "Alice" not in json.dumps(events)


@pytest.mark.parametrize("change", ["revision", "subject", "expiry", "trust", "context"])
def test_stale_dedup_plan_cannot_swallow_new_fact(clean_database, change):
    conn = clean_database
    team = seed_team(conn)
    make_session(conn, team)
    scope = team.scope_of("alice")
    with conn.transaction():
        original = store.add_memory(
            conn,
            scope_id=scope,
            author_id=team.alice_id,
            text="Alice prefers tea.",
            kind="preference",
            source_role="user",
        )
        message, _, _ = store.add_message(
            conn,
            session_id="s-1",
            user_id=team.alice_id,
            scope_id=scope,
            agent_id="chat",
            role="user",
            content="Alice likes tea.",
        )
    op = judge.Op(
        op="ADD",
        reason="stated",
        text="Alice likes tea.",
        kind="preference",
        evidence=[{"message_id": message, "start_char": 0, "end_char": 15}],
    )
    vectors = ScoredStub()
    outbox.drain(conn, vectors, HashEmbedder())
    planned = extract.plan_dedup(
        conn, ops=[op], scope_id=scope, client=vectors, embedder=HashEmbedder(), threshold=0.9
    )
    assert planned
    updates = {
        "revision": ("revision=revision+1,text=%s", "Alice now prefers coffee."),
        "subject": ("subject_id=%s", team.scope_of("bob")),
        "expiry": ("valid_until=%s", "2020-01-01T00:00:00Z"),
        "trust": ("source_role=%s", "assistant"),
        "context": ("context=%s", '{"project":"elsewhere"}'),
    }
    sql, value = updates[change]
    conn.execute(f"UPDATE memories SET {sql} WHERE id=%s", (value, original))
    with conn.transaction():
        outcome = apply(conn, team, [op], source_message_ids=[message], dedup_hits=planned)
    assert (outcome.added, outcome.deduplicated) == (1, 0)


def test_foreign_subject_and_untrusted_rows_never_reach_semantic_provider(clean_database):
    conn = clean_database
    team = seed_team(conn)
    scope = team.scope_of("alice")
    with conn.transaction():
        for options in [
            {"scope_id": team.scope_of("bob")},
            {"subject_id": team.scope_of("bob")},
            {"source_role": "assistant"},
            {"valid_until": "2020-01-01T00:00:00Z"},
            {"context": {"project": "other"}},
            {"kind": "project"},
        ]:
            store.add_memory(
                conn,
                **(
                    {
                        "scope_id": scope,
                        "author_id": team.alice_id,
                        "text": "A similar fact",
                        "kind": "fact",
                        "source_role": "user",
                    }
                    | options
                ),
            )
    vectors = ScoredStub()
    outbox.drain(conn, vectors, HashEmbedder())

    def unexpected(_):
        pytest.fail("ineligible data reached provider")

    with JevClient("test", transport=httpx.MockTransport(unexpected)) as client:
        planned = extract.plan_dedup(
            conn,
            ops=[judge.Op(op="ADD", reason="stated", text="A fact", kind="fact")],
            scope_id=scope,
            client=vectors,
            embedder=HashEmbedder(),
            threshold=0.9,
            semantic=SemanticBlocks(client, dedup="verify"),
        )
    assert planned == {}


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("off", ["bad", "good"]),
        ("shadow", ["bad", "good"]),
        ("rerank", ["good", "bad"]),
        ("filter", ["good"]),
    ],
)
def test_retrieval_modes_preserve_inputs(clean_database, mode, expected):
    rows = [candidate("bad", "irrelevant"), candidate("good", "useful")]
    before = [replace(r) for r in rows]
    events = []
    with JevClient(
        "test",
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=response({"0": score(0), "1": score(3)}))
        ),
    ) as client:
        result = SemanticBlocks(client, retrieval=mode, observer=events.append).rerank(
            "question", rows
        )
    assert [r.id for r in result] == expected
    assert rows == before
    assert (len(events) == 0) == (mode == "off")


def test_support_failure_is_advisory_and_modes_are_explicit(clean_database):
    events = []
    with JevClient(
        "test", attempts=1, transport=httpx.MockTransport(lambda _: httpx.Response(529))
    ) as client:
        result = SemanticBlocks(client, support="shadow", observer=events.append).inspect_support(
            [{"claim": "fictional", "user_spans": ["something else"]}]
        )
        with pytest.raises(ValueError, match="advisory"):
            SemanticBlocks(client, support="verify")
    assert result == {"checked": 0, "supported": 0, "uncertain": 0, "errors": 1}
    assert "fictional" not in json.dumps(events)
    assert from_settings(Settings(_env_file=None, JEV="credential")) is None


def test_extraction_support_is_advisory_after_exact_source_validation(clean_database):
    conn = clean_database
    team = seed_team(conn)
    make_session(conn, team)
    with conn.transaction():
        mid, _, _ = store.add_message(
            conn,
            session_id="s-1",
            user_id=team.alice_id,
            scope_id=team.scope_of("alice"),
            agent_id="chat",
            role="user",
            content="I prefer quiet hotels.",
        )
    operations = [
        {
            "op": "ADD",
            "text": "Alice prefers quiet hotels.",
            "kind": "preference",
            "reason": "stated",
            "context_entries": [],
            "evidence": [{"message_id": mid, "start_char": 0, "end_char": 22}],
        }
    ]
    observed = []

    def handler(request):
        assert conn.info.transaction_status == TransactionStatus.IDLE
        state = json.loads(request.content)["state"]
        observed.append(state)
        assert state["user_spans"] == ["I prefer quiet hotels."]
        assert state["context"]["recording_date"]
        assert state["context"]["entities"]
        return httpx.Response(200, json=response({"support": support(0)}))

    with (
        JevClient("test", transport=httpx.MockTransport(handler)) as client,
        fake_provider(lambda **_: providers.ProviderResult(raw={}, operations=operations)),
    ):
        result = extract.run_extraction(
            conn,
            session_id="s-1",
            agent_id="chat",
            api_key="",
            gemini_api_key="",
            project="",
            location="",
            monthly_limit_usd=10,
            model="fake-judge",
            force=True,
            semantic=SemanticBlocks(client, support="shadow"),
        )
    assert len(observed) == 1
    assert result.added == 1
    assert result.semantic_support == {"checked": 1, "supported": 0, "uncertain": 1, "errors": 0}
    aggregate = extract.ExtractionOutcome()
    aggregate.absorb(result)
    assert aggregate.as_dict()["semantic_support"]["uncertain"] == 1
