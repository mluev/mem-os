"""Opt-in Jev judgments over already-authorized data, with no database side effects.

This complements the generative judge; it cannot emit memory operations. Calls
are explicit, redacted, bounded and versioned. Failures are errors, never model
answers. No API handlers or workers enable this component by default.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from .security import redact_value
from .semantic_questions import question

if TYPE_CHECKING:
    from .retrieval import Scored

logger = logging.getLogger(__name__)
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
RETRYABLE = frozenset({429, 500, 502, 503, 504, 529})


class SemanticError(RuntimeError):
    """Sanitized failure: never includes source text, response body, or credentials."""


@dataclass(frozen=True)
class Answer:
    kind: str
    choice: str | None
    value: float | None
    probabilities: dict[str, float]
    confidence: float | None


def support_probability(answer: Answer) -> float:
    """Normalize the two experimentally compared support primitives, not their confidence."""
    if answer.kind == "noul":
        return float(answer.value)
    return answer.probabilities["supported"]


@dataclass(frozen=True)
class Judgment:
    model: str
    version: str
    request_sha256: str
    answers: dict[str, Answer]
    input_tokens: int
    output_tokens: int
    latency_ms: float
    attempts: int


class SemanticClient(Protocol):
    """Provider boundary: workflows consume judgments, never provider-specific HTTP."""

    def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]], *, version: str
    ) -> Judgment: ...

    def close(self) -> None: ...


def _number(value: Any, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("not a number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError("out of range")
    return float(value)


def _answer(raw: dict[str, Any], asked: dict[str, Any]) -> Answer:
    kind = asked["type"]
    if raw["type"] != kind:
        raise ValueError("wrong answer type")
    if kind == "noul":
        return Answer(kind, None, _number(raw["noul"], 0, 1), {}, None)
    criteria = asked["criteria"]
    keys = set(criteria) if kind == "choice" else {str(i) for i in range(len(criteria))}
    if set(raw["probabilities"]) != keys:
        raise ValueError("wrong options")
    probabilities = {k: _number(v, 0, 1) for k, v in raw["probabilities"].items()}
    # API probabilities are published to two decimals. Validate within their
    # rounding envelope, rather than rejecting an otherwise valid distribution.
    if not math.isclose(sum(probabilities.values()), 1, abs_tol=0.005 * len(keys) + 1e-9):
        raise ValueError("invalid distribution")
    confidence = _number(raw["confidence"], 0, 1)
    if kind == "choice":
        choice = raw["choice"]
        if choice not in keys or probabilities[choice] < max(probabilities.values()):
            raise ValueError("invalid choice")
        return Answer(kind, choice, None, probabilities, confidence)
    value = _number(raw["score"], 0, len(criteria) - 1)
    expected = sum(int(k) * p for k, p in probabilities.items())
    rounding = 0.005 * (sum(range(len(criteria))) + 1) + 1e-9
    if not math.isclose(value, expected, abs_tol=rounding):
        raise ValueError("inconsistent score")
    return Answer(kind, None, value, probabilities, confidence)


class JevClient:
    """One reusable synchronous HTTP client; suitable for bounded worker threads."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "jev-1.13.0",
        timeout: float = 20,
        attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise SemanticError("JEV or TYPESAFE_API_KEY is required")
        if not 1 <= attempts <= 3 or timeout <= 0:
            raise ValueError("invalid request bounds")
        self.model = model
        self.attempts = attempts
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> JevClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def ask(
        self, state: dict[str, Any], questions: dict[str, dict[str, Any]], *, version: str
    ) -> Judgment:
        if not questions:
            raise ValueError("at least one question is required")
        payload, _ = redact_value({"model": self.model, "state": state, "questions": questions})
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False)
        # Conservative envelope, independent of the provider's changing token limits.
        if len(serialized.encode()) > 100_000:
            raise SemanticError("semantic request exceeds local size limit")
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        started = time.perf_counter()
        for attempt in range(1, self.attempts + 1):
            try:
                response = self._client.post(ENDPOINT, json=payload)
            except httpx.TransportError:
                if attempt == self.attempts:
                    raise SemanticError("Jev transport failure") from None
                time.sleep(0.25 * 2 ** (attempt - 1))
                continue
            if response.status_code in RETRYABLE and attempt < self.attempts:
                try:
                    delay = float(response.headers.get("retry-after", "0"))
                except ValueError:
                    delay = 0
                # Do not retry earlier than a long Retry-After; let the caller defer.
                if not math.isfinite(delay) or delay > 5:
                    raise SemanticError("Jev requested deferred retry")
                time.sleep(max(delay, 0.25 * 2 ** (attempt - 1)))
                continue
            if response.status_code != 200:
                raise SemanticError(f"Jev HTTP {response.status_code}")
            try:
                data = response.json()
                if set(data["answers"]) != set(questions):
                    raise ValueError("missing or extra answers")
                model = data["model"]
                if not isinstance(model, str) or not model:
                    raise ValueError("missing model")
                if self.model not in {"jev-latest", "jev-preview"} and model != self.model:
                    raise ValueError("model version mismatch")
                answers = {key: _answer(data["answers"][key], q) for key, q in questions.items()}
                usage = data["usage"]
                counts = [usage["input_tokens"], usage["output_tokens"]]
                if any(type(n) is not int or n < 0 for n in counts):
                    raise ValueError("invalid token usage")
            except (ValueError, KeyError, TypeError, AttributeError):
                raise SemanticError("Jev invalid response") from None
            return Judgment(
                model,
                version,
                digest,
                answers,
                *counts,
                (time.perf_counter() - started) * 1000,
                attempt,
            )
        raise SemanticError("Jev request exhausted")  # pragma: no cover

    def judge(self, stage: str, state: dict[str, Any], *, version: str = "v1") -> Judgment:
        return self.ask(state, {stage: question(stage, version)}, version=version)


class JevReranker:
    """Optional adapter for retrieval.Reranker; receives authorized candidates only.

    Pure ordering by default. Abstention requires a separately evaluated floor.
    A provider failure preserves the entire original ordering and original scores.
    The caller may supply this to retrieval.explain; nothing enables it globally.
    """

    def __init__(
        self,
        client: SemanticClient,
        *,
        version: str = "v1",
        limit: int = 30,
        min_score: float | None = None,
    ) -> None:
        if limit < 1 or (min_score is not None and not 0 <= min_score <= 3):
            raise ValueError("invalid reranker bounds")
        self.client = client
        self.version = version
        self.limit = limit
        self.min_score = min_score

    def rerank(self, query: str, candidates: list[Scored]) -> list[Scored]:
        if not candidates:
            return []
        shortlist = candidates[: self.limit]
        state = {
            "query": query,
            "candidates": [
                {"text": c.text, "scope": c.scope, "subject": c.subject, "context": c.context}
                for c in shortlist
            ],
        }
        questions = {}
        for i in range(len(shortlist)):
            q = question("relevance", self.version)
            q["instructions"] = q["instructions"].replace("`memory`", f"`candidates[{i}]`")
            questions[str(i)] = q
        try:
            result = self.client.ask(state, questions, version=self.version)
        except SemanticError:
            logger.warning("Jev reranking unavailable; preserving baseline ranking")
            return list(candidates)
        ranked = [
            replace(c, score=float(result.answers[str(i)].value))
            for i, c in enumerate(shortlist)
            if self.min_score is None or float(result.answers[str(i)].value) >= self.min_score
        ]
        ranked.sort(key=lambda c: -c.score)  # Stable ties preserve the original order.
        # When abstaining, unchecked tail items cannot bypass the semantic floor.
        return ranked + (candidates[self.limit :] if self.min_score is None else [])
