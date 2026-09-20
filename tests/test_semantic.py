"""Offline contracts for semantic judgment, failure handling and evaluation metrics."""

from __future__ import annotations

import json

import httpx
import pytest

from eval.golden import Case
from eval.semantic import binary_metrics, ranking_metrics, summarize, validate
from eval.semantic_cases import cases
from eval.semantic_extraction import verified_sources
from memkit.config import Settings
from memkit.judge import Op
from memkit.retrieval import Scored
from memkit.semantic import JevClient, JevReranker, SemanticError, support_probability
from memkit.semantic_questions import question


@pytest.fixture(autouse=True)
def clean_database():
    """This module tests pure HTTP adapters and metrics, with no database dependency."""
    yield


def response(answers):
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


def support(probability=1.0):
    return {
        "type": "choice",
        "choice": "supported" if probability >= 0.5 else "unsupported",
        "probabilities": {
            "supported": probability,
            "unsupported": 1 - probability,
            "contradicted": 0,
        },
        "confidence": abs(2 * probability - 1),
    }


def score(level):
    return {
        "type": "score",
        "score": level,
        "confidence": 1,
        "probabilities": {str(i): int(i == level) for i in range(4)},
        "legend": {str(i): str(i) for i in range(4)},
    }


def client(handler, **kwargs):
    return JevClient("test-credential", transport=httpx.MockTransport(handler), **kwargs)


def candidate(name, text):
    return Scored(
        id=name,
        text=text,
        kind="fact",
        context={},
        tags=[],
        source_role="user",
        similarity=0.7,
        lexical=0.3,
        entity=0,
        importance=0.8,
        recency=1,
        score=0.6,
        updated_at="2026-09-20T00:00:00Z",
        scope="team",
    )


def test_ranking_metrics_use_question_indexes_not_response_key_order():
    metrics = summarize(
        [
            {
                "id": "ordered",
                "stage": "relevance",
                "expected": [0],
                "judgment": {
                    "answers": {"1": {"value": 0}, "0": {"value": 3}},
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "latency_ms": 1,
                },
            }
        ],
        {},
        support_floor=0.9,
        duplicate_floor=0.9,
        relevance_floor=2,
    )
    assert metrics["retrieval"]["top1"] == 1


def test_request_is_redacted_and_audited_without_a_key():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response({"support": support()}))

    with client(handler) as jev:
        result = jev.judge(
            "support",
            {
                "user_spans": ["password=hidden-value"],
                "api_key": "another-hidden-value",
                "claim": "A fact",
            },
        )
    body = requests[0].content.decode()
    assert "hidden-value" not in body
    assert "test-credential" not in body
    assert requests[0].headers["Authorization"] == "Bearer test-credential"
    assert len(result.request_sha256) == 64
    assert result.model == "jev-1.13.0"
    assert result.input_tokens == 10


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["answers"].clear(),
        lambda d: d["answers"].update(extra=support()),
        lambda d: d["answers"]["support"].update(type="score"),
        lambda d: d["answers"]["support"].update(choice="invented"),
        lambda d: d["answers"]["support"].update(confidence=-0.1),
        lambda d: d["answers"]["support"].update(confidence=True),
        lambda d: d["answers"]["support"]["probabilities"].update(supported=0.2),
        lambda d: d["answers"]["support"]["probabilities"].update(extra=0),
        lambda d: d["usage"].update(input_tokens=-1),
        lambda d: d.update(model="jev-changed"),
    ],
)
def test_malformed_responses_are_errors_not_answers(mutate):
    data = response({"support": support()})
    mutate(data)
    with (
        client(lambda _: httpx.Response(200, json=data)) as jev,
        pytest.raises(SemanticError, match="invalid response"),
    ):
        jev.judge("support", {})


def test_nonfinite_probability_rejected():
    data = json.dumps(response({"support": support()})).replace(
        '"supported": 1.0', '"supported": NaN'
    )
    with (
        client(lambda _: httpx.Response(200, text=data)) as jev,
        pytest.raises(SemanticError, match="invalid response"),
    ):
        jev.judge("support", {})


def test_http_errors_do_not_echo_provider_body_and_do_not_retry_auth():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="private source and a credential")

    with client(handler) as jev, pytest.raises(SemanticError, match=r"^Jev HTTP 401$"):
        jev.judge("support", {})
    assert len(calls) == 1


def test_bounded_retry_honors_retry_after(monkeypatch):
    delays = []
    monkeypatch.setattr("memkit.semantic.time.sleep", delays.append)
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json=response({"support": support()})),
        ]
    )
    with client(lambda _: next(responses)) as jev:
        result = jev.judge("support", {})
    assert delays == [1.0]
    assert result.attempts == 2


def test_long_retry_after_defers_instead_of_retrying_early():
    with (
        client(lambda _: httpx.Response(429, headers={"Retry-After": "90"})) as jev,
        pytest.raises(SemanticError, match="deferred retry"),
    ):
        jev.judge("support", {})


def test_request_size_limit_applies_before_network():
    with (
        client(lambda _: pytest.fail("network must not be reached")) as jev,
        pytest.raises(SemanticError, match="size limit"),
    ):
        jev.judge("support", {"text": "x" * 100_001})


def test_reranker_uses_each_candidate_and_preserves_input():
    original = [candidate("a", "unrelated"), candidate("b", "direct answer")]

    def handler(request):
        payload = json.loads(request.content)
        assert "`candidates[1]`" in payload["questions"]["1"]["instructions"]
        assert payload["state"]["candidates"][0]["scope"] == "team"
        # Provider order need not be request order.
        return httpx.Response(200, json=response({"1": score(3), "0": score(0)}))

    with client(handler) as jev:
        ranked = JevReranker(jev).rerank("query", original)
    assert [c.id for c in ranked] == ["b", "a"]
    assert original[0].score == original[1].score == 0.6
    assert ranked[0].score == 3


def test_rerank_failure_restores_all_candidates():
    original = [candidate("a", "first"), candidate("b", "second")]
    with client(lambda _: httpx.Response(503), attempts=1) as jev:
        assert JevReranker(jev, limit=1, min_score=2).rerank("q", original) == original


def test_unchecked_tail_cannot_bypass_abstention():
    original = [candidate("a", "first"), candidate("b", "second")]
    with client(lambda _: httpx.Response(200, json=response({"0": score(0)}))) as jev:
        assert JevReranker(jev, limit=1, min_score=2).rerank("q", original) == []


def test_ties_preserve_baseline_order_and_unscored_tail():
    original = [candidate("b", "first"), candidate("a", "second"), candidate("c", "third")]
    with client(
        lambda _: httpx.Response(200, json=response({"0": score(2), "1": score(2)}))
    ) as jev:
        ranked = JevReranker(jev, limit=2).rerank("q", original)
    assert [c.id for c in ranked] == ["b", "a", "c"]
    assert ranked[-1] == original[-1]


def test_empty_candidates_do_not_call_provider():
    with client(lambda _: pytest.fail("no call expected")) as jev:
        assert JevReranker(jev).rerank("q", []) == []


def test_questions_are_independent_copies():
    first = question("support")
    first["criteria"].clear()
    assert len(question("support")["criteria"]) == 3


def test_jev_key_alias_and_repr(monkeypatch):
    monkeypatch.setenv("JEV", "private-jev-key")
    settings = Settings(_env_file=None, telemetry_hmac_key="test")
    assert settings.jev_api_key == "private-jev-key"
    assert "private-jev-key" not in repr(settings)
    monkeypatch.delenv("JEV")
    monkeypatch.setenv("TYPESAFE_API_KEY", "alternate-key")
    assert Settings(_env_file=None, telemetry_hmac_key="test").jev_api_key == "alternate-key"


def test_corpus_and_metrics_count_false_acceptance_and_missing_answers():
    validate(cases())
    metrics = binary_metrics([(True, True), (True, False), (False, True), (False, False)])
    assert metrics["false_positive"] == metrics["false_negative"] == 1
    ranked = ranking_metrics([([1], [2.8, 1.8]), ([], [0.1, 0.2]), ([0, 1], [2.9, 2.8])], 2)
    assert ranked["top1"] == 0.5
    assert ranked["mrr"] == 0.75
    assert ranked["correct_abstentions"] == 1
    assert ranked["relevant_retained"] == 2
    assert ranked["relevant_total"] == 3


def test_score_consistency_and_zero_usage():
    data = response({"relevance": score(3)})
    data["answers"]["relevance"]["score"] = 1
    with (
        client(lambda _: httpx.Response(200, json=data)) as jev,
        pytest.raises(SemanticError, match="invalid response"),
    ):
        jev.judge("relevance", {})


def test_live_score_rounding_does_not_look_like_provider_failure():
    # Captured synthetic response: public probabilities and score round separately.
    answer = {
        "type": "score",
        "score": 0.1,
        "confidence": 0.9,
        "probabilities": {"0": 0.92, "1": 0.08, "2": 0.0, "3": 0.0},
    }
    with client(lambda _: httpx.Response(200, json=response({"relevance": answer}))) as jev:
        assert jev.judge("relevance", {}).answers["relevance"].value == 0.1


def test_transport_failure_does_not_expose_request():
    def handler(request):
        raise httpx.ReadTimeout("secret request content", request=request)

    with (
        client(handler, attempts=1) as jev,
        pytest.raises(SemanticError, match=r"^Jev transport failure$"),
    ):
        jev.judge("support", {})


@pytest.mark.parametrize(
    "source,quote,expected",
    [
        ("I use Vim.", "I use Vim.", ["I use Vim."]),
        ("I use Vim.", "I use Emacs.", None),
        ("Vim, Vim", "Vim", None),
    ],
)
def test_extractor_experiment_checks_verbatim_unique_quotes(source, quote, expected):
    case = Case.parse({"messages": [["user", source]]}, 0)
    op = Op(
        op="ADD",
        text="The user uses Vim",
        reason="test",
        evidence=[
            {
                "message_id": 1,
                "start_char": 0,
                "end_char": len(source),
                "quote": quote,
            }
        ],
    )
    assert verified_sources(case, op) == expected


def test_extractor_experiment_rejects_assistant_sources():
    case = Case.parse({"messages": [["assistant", "I use Vim."]]}, 0)
    op = Op(
        op="ADD",
        text="The user uses Vim",
        reason="test",
        evidence=[
            {
                "message_id": 1,
                "start_char": 0,
                "end_char": 10,
                "quote": "I use Vim.",
            }
        ],
    )
    assert verified_sources(case, op) is None


def test_noul_uses_yes_probability_without_inventing_confidence():
    with client(
        lambda _: httpx.Response(
            200,
            json=response(
                {
                    "support": {"type": "noul", "noul": 0.81},
                }
            ),
        )
    ) as jev:
        answer = jev.judge("support", {}, version="v4").answers["support"]
    assert support_probability(answer) == 0.81
    assert answer.confidence is None


@pytest.mark.parametrize("value", [True, -0.1, 1.1, "0.9"])
def test_invalid_noul_is_an_error(value):
    with (
        client(
            lambda _: httpx.Response(
                200,
                json=response(
                    {
                        "support": {"type": "noul", "noul": value},
                    }
                ),
            )
        ) as jev,
        pytest.raises(SemanticError, match="invalid response"),
    ):
        jev.judge("support", {}, version="v4")
