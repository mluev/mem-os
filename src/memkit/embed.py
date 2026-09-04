"""BGE-M3 embeddings, loaded in-process.

Called on every ingested message and every search, so it sits on the latency
critical path. docs/06-roadmap.md sets the gate: one phrase must embed in under
100 ms on MPS, and if CPU fallback exceeds 300 ms it has to be fixed before the
read path is built.

Both the device and the runtime are configuration, because the same code runs on
a laptop with Metal and in a container with neither GPU nor torch worth loading:
``embed_backend='local'`` is torch, ``'onnx'`` is the exported graph, which is
the faster of the two on CPU.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .config import get_settings

logger = logging.getLogger(__name__)

# Runtimes sentence-transformers can load a dense model under. Anything else is
# a typo in the environment, and a typo must not silently become 'local'.
BACKENDS = frozenset({"local", "onnx"})

# Dense vector width, read from settings because the Qdrant collections are
# created with it: a different width is a different index, so changing the model
# means a reindex rather than a restart. `vectors` imports this.
DIM = get_settings().embed_dim


class Embedder:
    """Lazily-loaded sentence-transformers wrapper.

    Loading the model costs seconds and hundreds of MB, so it is deferred until
    first use and then shared. ``encode`` is guarded by a lock: torch MPS is not
    safe to call concurrently from multiple threads, and the API server is
    threaded.
    """

    def __init__(
        self,
        model_name: str,
        device: str,
        revision: str | None = None,
        backend: str = "local",
    ) -> None:
        if backend not in BACKENDS:
            raise ValueError(
                f"unknown embed backend {backend!r}; expected one of {sorted(BACKENDS)}"
            )
        self._model_name = model_name
        self._requested_device = device
        self._revision = revision
        self._backend = backend
        self._model = None
        self._device: str | None = None
        self._lock = threading.Lock()

    def _resolve_device(self) -> str:
        import torch

        want = self._requested_device
        if want == "mps" and not torch.backends.mps.is_available():
            logger.warning("MPS unavailable, falling back to CPU; expect slower search")
            return "cpu"
        if want == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA unavailable, falling back to CPU")
            return "cpu"
        return want

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            from sentence_transformers import SentenceTransformer

            self._device = self._resolve_device()
            # 'local' is the library's own default; passing it explicitly would
            # break against a version that predates the argument.
            options: dict[str, Any] = {} if self._backend == "local" else {"backend": self._backend}
            t0 = time.perf_counter()
            self._model = SentenceTransformer(
                self._model_name, device=self._device, revision=self._revision, **options
            )
            logger.info(
                "loaded %s on %s via %s in %.1fs",
                self._model_name,
                self._device,
                self._backend,
                time.perf_counter() - t0,
            )
            # First encode on MPS pays a one-off graph-compilation cost. Warm it
            # now so the first real request is not the one that eats it.
            warmed = self._model.encode(["warmup"], normalize_embeddings=True)
            width = len(warmed[0])
            if width != DIM:
                self._model = None
                raise RuntimeError(
                    f"{self._model_name} produces {width}-dimensional vectors but "
                    f"MEMKIT_EMBED_DIM is {DIM}; the Qdrant collections would reject "
                    "every point. Fix the setting and reindex."
                )

    @property
    def device(self) -> str | None:
        return self._device

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def ready(self) -> bool:
        return self._model is not None

    def encode(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        """Embed texts, L2-normalised so cosine distance is a dot product."""
        if not texts:
            return []
        self.load()
        if self._model is None:
            raise RuntimeError("embedding model failed to load")
        with self._lock:
            vecs = self._model.encode(
                texts,
                batch_size=batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return [v.tolist() for v in vecs]

    def encode_one(self, text: str) -> list[float]:
        return self.encode([text])[0]

    def benchmark(self, phrase: str = "привет, я предпочитаю pnpm", runs: int = 5) -> dict:
        """Measure single-phrase latency, the roadmap's phase-0 gate."""
        self.load()
        timings = []
        for _ in range(runs):
            t0 = time.perf_counter()
            self.encode_one(phrase)
            timings.append((time.perf_counter() - t0) * 1000)
        timings.sort()
        return {
            "device": self._device,
            "backend": self._backend,
            "dim": len(self.encode_one(phrase)),
            "median_ms": round(timings[len(timings) // 2], 1),
            "min_ms": round(timings[0], 1),
            "max_ms": round(timings[-1], 1),
        }


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        s = get_settings()
        _embedder = Embedder(s.embed_model, s.embed_device, s.embed_revision, s.embed_backend)
    return _embedder
