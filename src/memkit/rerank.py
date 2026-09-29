"""Optional cross-encoder reranking of the fused candidate list.

The fusion score compares a query and a memory through two independent
encodings; a cross-encoder reads them together, which is what separates "the
user prefers dark mode" from "the user dislikes dark mode" when both embed
alike. It is slower, so it only reorders the head of a list the hybrid ranker
already chose and never admits a candidate that ranker dropped.

Off unless `MEMKIT_RERANK_MODEL` names a model (e.g. `BAAI/bge-reranker-v2-m3`).
The model loads on first use; a load or inference failure keeps the hybrid
order, because a reranker outage must not become a search outage.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import replace
from typing import Any

from .retrieval import Scored

logger = logging.getLogger(__name__)

# Candidates the cross-encoder reads. Beyond this the hybrid order stands.
HEAD = 30
# How much of the final order comes from the cross-encoder, the rest from the
# hybrid score it is refining. All-in on either side throws information away.
BLEND = 0.7


class CrossEncoderReranker:
    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        revision: str | None = None,
        head: int = HEAD,
        blend: float = BLEND,
        model: Any = None,
    ) -> None:
        if not 0 <= blend <= 1 or head < 1:
            raise ValueError("invalid reranker bounds")
        self.model_name = model_name
        self.device = device
        self.revision = revision
        self.head = head
        self.blend = blend
        self._model = model
        self._lock = threading.Lock()
        self._failed = False

    def _load(self) -> Any:
        if self._model is None and not self._failed:
            try:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self.model_name, device=self.device, revision=self.revision
                )
            except Exception:
                logger.exception(
                    "cross-encoder %s unavailable; keeping hybrid order", self.model_name
                )
                self._failed = True
        return self._model

    def rerank(self, query: str, candidates: list[Scored]) -> list[Scored]:
        if len(candidates) < 2:
            return candidates
        head, tail = candidates[: self.head], candidates[self.head :]
        with self._lock:
            model = self._load()
            if model is None:
                return candidates
            try:
                raw = model.predict([(query, item.text) for item in head])
            except Exception:
                logger.exception("cross-encoder inference failed; keeping hybrid order")
                return candidates
        relevance = [1.0 / (1.0 + math.exp(-float(value))) for value in raw]
        top = max(item.score for item in head)
        low = min(item.score for item in head)
        spread = (top - low) or 1.0
        blended = [
            replace(
                item,
                score=self.blend * cross + (1 - self.blend) * (item.score - low) / spread,
            )
            for item, cross in zip(head, relevance, strict=True)
        ]
        blended.sort(key=lambda item: (-item.score, item.id))
        return blended + tail


def from_settings(settings: Any) -> CrossEncoderReranker | None:
    name = getattr(settings, "rerank_model", "")
    if not name:
        return None
    return CrossEncoderReranker(name, device=getattr(settings, "embed_device", "cpu"))
