"""Quality accounting must not confuse detail coverage, noise, and abstention."""

import httpx
import pytest

from eval.readiness_http import fixture_request, score_case, summarize


def test_scores_details_sources_and_irrelevance_independently():
    case = {"id": "x", "details": ["pnpm", "exception"], "relevant": ["preference", "quote"]}
    body = {
        "memories": [
            {
                "id": "m1",
                "text": "Uses pnpm",
                "sources": [{"message_id": 1, "excerpt": "an exception"}],
            },
            {"id": "m2", "text": "irrelevant data"},
        ],
        "raw": [],
        "used_tokens": 20,
    }
    result = score_case(case, body, {"m1": "preference", "m2": "other"}, {1: "quote"})
    assert result["details_found"] == 2
    assert result["irrelevant_items"] == ["other"]
    assert result["correct_abstention"] is None


def test_negative_query_fails_abstention_even_if_no_detail_is_expected():
    case = {"id": "negative", "details": [], "relevant": []}
    result = score_case(case, {"memories": [{"id": "m1", "text": "Noise"}]}, {"m1": "other"}, {})
    assert result["correct_abstention"] is False
    aggregate = summarize([result | {"wall_ms": 12, "status": 200}])
    assert aggregate["correct_abstentions"] == 0
    assert aggregate["unanswerable_queries"] == 1
    assert aggregate["details_expected"] == 0


def test_detail_matches_in_irrelevant_records_receive_no_credit():
    case = {"id": "x", "details": ["Tuesday"], "relevant": ["current-release"]}
    body = {"memories": [{"id": "m1", "text": "An unrelated review is on Tuesday."}]}
    result = score_case(case, body, {"m1": "unrelated"}, {})
    assert result["details_found"] == 0
    assert result["irrelevant_items"] == ["unrelated"]


def test_http_failure_is_never_a_successful_empty_answer():
    result = {
        "details_found": 0,
        "details_expected": 0,
        "irrelevant_items": [],
        "correct_abstention": False,
        "status": 503,
        "wall_ms": 10,
    }
    assert summarize([result])["http_errors"] == 1


def test_fixture_maintenance_retry_is_visible_and_bounded(monkeypatch):
    monkeypatch.setattr("eval.readiness_http.time.sleep", lambda _: None)
    events = []
    responses = iter(
        [
            httpx.Response(
                503,
                json={"detail": "memory maintenance is in progress; retry shortly"},
                headers={"Retry-After": "5"},
            ),
            httpx.Response(201, json={"id": "fixture"}),
        ]
    )
    with httpx.Client(
        base_url="http://fixture.invalid",
        transport=httpx.MockTransport(lambda _: next(responses)),
    ) as client:
        response = fixture_request(client, "POST", "/v1/memories", {}, events)
    assert response.json()["id"] == "fixture"
    assert len(events) == 1
    assert events[0]["status"] == 503

    with (
        httpx.Client(
            base_url="http://fixture.invalid",
            transport=httpx.MockTransport(lambda _: httpx.Response(503, json={"detail": "broken"})),
        ) as client,
        pytest.raises(RuntimeError, match="broken"),
    ):
        fixture_request(client, "POST", "/v1/memories", {}, events)

    events = []
    with (
        httpx.Client(
            base_url="http://fixture.invalid",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    503,
                    json={"detail": "memory maintenance is in progress; retry shortly"},
                    headers={"Retry-After": "5"},
                )
            ),
        ) as client,
        pytest.raises(RuntimeError, match="maintenance"),
    ):
        fixture_request(client, "POST", "/v1/memories", {}, events)
    assert len(events) == 5
