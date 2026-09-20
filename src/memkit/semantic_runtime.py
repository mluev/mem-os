"""Small semantic blocks with explicit policies and content-free observations.

Callers authorize state before calling. No judgments grant permissions or bypass
citation checks. Runtime observations contain counts, model/version and usage;
experimental per-case evidence belongs in the separate evaluation archive.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .context_selection import ContextSelector
from .semantic import JevClient, JevReranker, SemanticClient, SemanticError, support_probability
from .semantic_questions import question

if TYPE_CHECKING:
    from .config import Settings
    from .retrieval import Scored

logger = logging.getLogger(__name__)


class SemanticBlocks:
    def __init__(
        self,
        client: SemanticClient,
        *,
        version: str = "v2",
        dedup: str = "off",
        retrieval: str = "off",
        support: str = "off",
        context: str = "off",
        contribution_floor: float = 0.7,
        redundancy_floor: float = 0.7,
        duplicate_floor: float = 0.9,
        relevance_floor: float = 2.0,
        support_floor: float = 0.9,
        observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if dedup not in {"off", "shadow", "verify"}:
            raise ValueError("invalid dedup mode")
        if retrieval not in {"off", "shadow", "rerank", "filter", "contribution"}:
            raise ValueError("invalid retrieval mode")
        if context not in {"off", "select", "compact"}:
            raise ValueError("invalid context mode")
        if not 0 <= contribution_floor <= 1 or not 0 <= redundancy_floor <= 1:
            raise ValueError("invalid context thresholds")
        if support not in {"off", "shadow"}:
            raise ValueError("support is advisory only")
        if not 0 <= duplicate_floor <= 1 or not 0 <= support_floor <= 1:
            raise ValueError("invalid probability floor")
        if not 0 <= relevance_floor <= 3:
            raise ValueError("invalid relevance floor")
        question("relation", version)
        self.client = client
        self.version = version
        self.dedup = dedup
        self.retrieval = retrieval
        self.support = support
        self.context = context
        self.contribution_floor = contribution_floor
        self.redundancy_floor = redundancy_floor
        self.duplicate_floor = duplicate_floor
        self.relevance_floor = relevance_floor
        self.support_floor = support_floor
        self.observer = observer

    def _observe(self, event: dict[str, Any]) -> None:
        logger.info("semantic observation %s", event)
        if self.observer is not None:
            self.observer(dict(event))

    def _ask(
        self,
        stage: str,
        state: dict[str, Any],
        questions: dict[str, Any],
        *,
        version: str | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        version = version or self.version
        event = {"stage": stage, "version": version, "questions": len(questions)}
        try:
            result = self.client.ask(state, questions, version=version)
        except SemanticError:
            event["errors"] = 1
            return None, event
        event.update(
            model=result.model,
            errors=0,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=round(result.latency_ms, 2),
        )
        return result, event

    def verify_duplicates(self, pairs: dict[int, dict[str, Any]]) -> set[int]:
        """Can only veto already-proposed duplicates; an outage preserves the new fact."""
        if self.dedup == "off" or not pairs:
            return set(pairs)
        allowed: set[int] = set()
        # Bounded batches prevent one large extraction from exceeding the envelope.
        keys = list(pairs)
        for offset in range(0, len(keys), 10):
            batch = keys[offset : offset + 10]
            state = {"pairs": [pairs[k] for k in batch]}
            questions = {}
            for i, key in enumerate(batch):
                q = question("relation", self.version)
                for name in ("incoming", "existing"):
                    q["instructions"] = q["instructions"].replace(
                        f"`{name}`", f"`pairs[{i}].{name}`"
                    )
                questions[str(key)] = q
            result, event = self._ask("duplicate", state, questions)
            confirmed = {
                key
                for key in batch
                if result is not None
                and result.answers[str(key)].probabilities["equivalent"] >= self.duplicate_floor
            }
            event.update(
                mode=self.dedup, confirmed=len(confirmed), kept_separate=len(batch) - len(confirmed)
            )
            self._observe(event)
            allowed.update(batch if self.dedup == "shadow" else confirmed)
        return allowed

    def inspect_support(self, claims: list[dict[str, Any]]) -> dict[str, int]:
        """Return diagnostics only; no admission policy consumes these counts."""
        counts = {"checked": 0, "supported": 0, "uncertain": 0, "errors": 0}
        if self.support == "off":
            return counts
        for claim in claims:
            result, event = self._ask(
                "support", claim, {"support": question("support", self.version)}
            )
            if result is None:
                counts["errors"] += 1
            else:
                counts["checked"] += 1
                accepted = support_probability(result.answers["support"]) >= self.support_floor
                counts["supported" if accepted else "uncertain"] += 1
                event["supported"] = accepted
            event["mode"] = "shadow"
            self._observe(event)
        return counts

    def rerank(self, query: str, candidates: list[Scored]) -> list[Scored]:
        if self.retrieval == "off" or not candidates:
            return list(candidates)
        if self.retrieval == "contribution":
            return self.select_context(query, candidates, compact=False)
        # Reuse the existing adapter without shared per-request state. The proxy
        # captures only this call's metadata, so concurrent searches cannot mix it.
        owner = self
        events: list[dict[str, Any]] = []

        class ObservedClient:
            def ask(self, state, questions, *, version):
                result, event = owner._ask("relevance", state, questions)
                events.append(event)
                if result is None:
                    raise SemanticError("semantic retrieval unavailable")
                return result

        result = JevReranker(
            ObservedClient(),
            version=self.version,
            min_score=self.relevance_floor if self.retrieval in {"shadow", "filter"} else None,
        ).rerank(query, candidates)
        if events:
            self._observe(
                events[0]
                | {
                    "mode": self.retrieval,
                    "candidates": len(candidates),
                    "selected": len(result),
                    "order_changed": [r.id for r in result] != [r.id for r in candidates],
                }
            )
        return list(candidates) if self.retrieval == "shadow" else result

    def select_context(
        self,
        query: str,
        candidates: list[Scored],
        *,
        compact: bool | None = None,
        budget_tokens: int | None = None,
        max_results: int | None = None,
    ) -> list[Scored]:
        """Shared contribution judgments for facts and optional original passages."""
        owner = self
        compact = self.context == "compact" if compact is None else compact

        class ObservedClient:
            def ask(self, state, questions, *, version):
                stage = "redundancy" if "redundant" in questions else "contribution"
                result, event = owner._ask(stage, state, questions, version=version)
                owner._observe(event)
                if result is None:
                    raise SemanticError("semantic context unavailable")
                return result

            def close(self):
                pass

        result = ContextSelector(
            ObservedClient(),
            limit=60,
            batch_size=30,
            relevance_mode="contribution",
            relevance_floor=self.contribution_floor,
            redundancy_floor=self.redundancy_floor,
            compact=compact,
        ).rerank(query, candidates, budget_tokens=budget_tokens, max_results=max_results)
        self._observe(
            {
                "stage": "context_selection",
                "candidates": len(candidates),
                "selected": len(result),
                "mode": "compact" if compact else "select",
            }
        )
        return result


def from_settings(settings: Settings) -> SemanticBlocks | None:
    """Explicit switches; a credential alone never activates a provider."""
    if all(
        mode == "off"
        for mode in (
            settings.semantic_dedup,
            settings.semantic_retrieval,
            settings.semantic_support,
            settings.semantic_context,
        )
    ):
        return None
    return SemanticBlocks(
        JevClient(
            settings.jev_api_key,
            model=settings.jev_model,
            timeout=settings.semantic_timeout_seconds,
            attempts=1,
        ),
        version=settings.semantic_version,
        dedup=settings.semantic_dedup,
        retrieval=settings.semantic_retrieval,
        support=settings.semantic_support,
        context=settings.semantic_context,
        contribution_floor=settings.semantic_contribution_floor,
        redundancy_floor=settings.semantic_redundancy_floor,
        duplicate_floor=settings.semantic_duplicate_floor,
        relevance_floor=settings.semantic_relevance_floor,
    )
