"""Restart-safe polling worker for durable jobs and index deliveries."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable

from qdrant_client import QdrantClient

from . import jobs, outbox, vectors
from .embed import Embedder

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        db: Callable[[], sqlite3.Connection],
        client: QdrantClient,
        embedder: Embedder,
        dispatch: Callable[[str, str], None],
        *,
        poll_seconds: float = 1.0,
        dependency_status: Callable[[bool, str | None], None] | None = None,
    ) -> None:
        self.db = db
        self.client = client
        self.embedder = embedder
        self.dispatch = dispatch
        self.poll_seconds = poll_seconds
        self.dependency_status = dependency_status or (lambda _ready, _error: None)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="memkit-worker", daemon=True)

    def start(self) -> None:
        jobs.recover_stale(self.db())
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                vectors.ensure_collections(self.client)
                self.dependency_status(True, None)
                outbox.drain(self.db(), self.client, self.embedder, limit=100)
                row = (
                    self.db()
                    .execute(
                        "SELECT id,kind FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
                    )
                    .fetchone()
                )
                if row is not None:
                    self.dispatch(str(row["id"]), str(row["kind"]))
                    continue
            except Exception as exc:
                self.dependency_status(False, str(exc))
                logger.exception("durable worker iteration failed")
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
