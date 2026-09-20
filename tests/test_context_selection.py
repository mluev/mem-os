"""Context selection must retain evidence and survive provider failures atomically."""

from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from eval.context_cases import corpus
from eval.context_experiments import metrics, pack
from memkit.context_selection import ContextSelector
from memkit.retrieval import _token_count
from memkit.semantic import JevClient
from tests.test_semantic import candidate, response, score


@pytest.fixture(autouse=True)
def clean_database():
    yield


def test_batched_filter_preserves_order_and_never_returns_unchecked_tail():
    rows = [candidate(str(i), f"fact {i}") for i in range(7)]
    observed = []

    def handler(request):
        data = json.loads(request.content)
        observed.extend(c["text"] for c in data["state"]["candidates"])
        return httpx.Response(200, json=response({k: score(3) for k in data["questions"]}))

    with JevClient("test", transport=httpx.MockTransport(handler)) as client:
        result = ContextSelector(client, limit=5, batch_size=2).rerank("query", rows)
    assert observed == [f"fact {i}" for i in range(5)]
    assert [r.id for r in result] == [str(i) for i in range(5)]
    assert all(r.score == 0.6 for r in rows)


def test_later_batch_failure_restores_entire_baseline():
    rows = [candidate(str(i), f"fact {i}") for i in range(5)]
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        data = json.loads(request.content)
        if calls == 2:
            return httpx.Response(529)
        return httpx.Response(200, json=response({k: score(0) for k in data["questions"]}))

    with JevClient("test", attempts=1, transport=httpx.MockTransport(handler)) as client:
        result = ContextSelector(client, batch_size=2).rerank("query", rows)
    assert result == rows


def test_redundancy_only_compares_against_surviving_evidence():
    rows = [
        candidate("base", "Postgres"),
        candidate("duplicate", "PostgreSQL"),
        candidate("exception", "Redis remains for cache"),
        candidate("conflict", "Use SQLite"),
    ]
    before = [replace(r) for r in rows]
    seen = []

    def handler(request):
        data = json.loads(request.content)
        seen.append(data["state"])
        redundant = data["state"]["candidate"]["text"] == "PostgreSQL"
        return httpx.Response(
            200,
            json=response(
                {
                    "redundant": {
                        "type": "noul",
                        "noul": float(redundant),
                    }
                }
            ),
        )

    with JevClient("test", transport=httpx.MockTransport(handler)) as client:
        result = ContextSelector(client).remove_redundancy("database", rows)
    assert [r.id for r in result] == ["base", "exception", "conflict"]
    assert [r["text"] for r in seen[-1]["earlier"]] == ["Postgres", "Redis remains for cache"]
    assert rows == before


def test_compaction_failure_restores_ranked_input():
    rows = [candidate("a", "A"), candidate("b", "B")]
    with JevClient(
        "test", attempts=1, transport=httpx.MockTransport(lambda _: httpx.Response(529))
    ) as client:
        assert ContextSelector(client).remove_redundancy("query", rows) == rows


def test_compaction_only_uses_evidence_that_fits_the_remaining_context_budget():
    rows = [
        candidate("first", "First useful fact."),
        candidate("long", "PostgreSQL " * 30),
        candidate("short", "Use PostgreSQL."),
    ]
    budget = sum(_token_count(r.text) + 6 for r in (rows[0], rows[2]))
    observed = []

    def handler(request):
        state = json.loads(request.content)["state"]
        observed.extend(c["text"] for c in state["earlier"])
        redundant = any("PostgreSQL" in c["text"] for c in state["earlier"])
        return httpx.Response(
            200, json=response({"redundant": {"type": "noul", "noul": float(redundant)}})
        )

    with JevClient("test", transport=httpx.MockTransport(handler)) as client:
        selected = ContextSelector(client).remove_redundancy("database", rows, budget_tokens=budget)
    selected, used = pack(selected, budget)
    assert [r.id for r in selected] == ["first", "short"]
    assert used <= budget
    assert rows[1].text not in observed


def test_compaction_checks_only_survivors_within_the_output_limit():
    rows = [candidate("first", "First"), candidate("tail", "Tail")]
    calls = []
    with JevClient(
        "test", transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(529))
    ) as client:
        selected = ContextSelector(client).remove_redundancy("query", rows, max_results=1)
    assert selected == rows[:1]
    assert calls == []


def test_time_budget_stops_between_provider_calls_without_losing_input(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("memkit.context_selection.monotonic", lambda: clock[0])
    rows = [candidate("first", "a"), candidate("second", "b")]
    calls = []

    def handler(request):
        calls.append(request)
        clock[0] = 6
        return httpx.Response(200, json=response({"0": score(0)}))

    with JevClient("test", transport=httpx.MockTransport(handler)) as client:
        result = ContextSelector(client, batch_size=1, deadline_seconds=5).rerank("query", rows)
    assert result == rows
    assert len(calls) == 1


def test_corpus_split_is_by_family_and_every_label_has_a_source():
    data = corpus()
    by_id = {i["id"]: i for i in data["items"]}
    assert len(by_id) == len(data["items"])
    for query in data["queries"]:
        relevant = [by_id[k] for k in query["relevant_ids"]]
        assert all(i["split"] == query["split"] for i in relevant)
        available = {f for i in relevant for f in i["facets"]}
        assert set(query["expected"]) <= available
    families = {}
    for item in data["items"]:
        families.setdefault(item["family"], set()).add(item["split"])
    assert all(len(splits) == 1 for splits in families.values())


def test_budget_and_metrics_count_information_once():
    data = corpus()
    query = next(q for q in data["queries"] if q["id"] == "ledger-broad")
    records = [
        {
            "query": query,
            "variants": {
                "test": {
                    "ids": ["ledger-m0", "ledger-m1", "ledger-e1"],
                    "tokens": 80,
                    "usage": {
                        "provider_ms_sum": 0,
                        "input_tokens": 0,
                        "new_input_tokens": 0,
                        "errors": 0,
                    },
                }
            },
        }
    ]
    result = metrics(records, data, "test")
    assert (result["details_retained"], result["details_expected"], result["redundant_items"]) == (
        2,
        4,
        1,
    )
    rows = [candidate("huge", "word " * 500), candidate("small", "hello")]
    chosen, used = pack(rows, 10)
    assert [r.id for r in chosen] == ["small"]
    assert used <= 10
