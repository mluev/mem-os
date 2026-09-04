"""Restart-safe polling worker for durable jobs and index deliveries."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from qdrant_client import QdrantClient

from . import jobs, outbox, vectors
from .db import ConnectionPool
from .embed import Embedder

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        db: ConnectionPool,
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
        # `self.db()` is this thread's pooled connection: the same one every
        # iteration, so the drain and the queue read do not pay a Postgres
        # handshake per poll. It goes back to the pool when the application
        # closes it, which is also the only thing that may close it.
        while not self._stop.is_set():
            try:
                vectors.ensure_collections(self.client)
                self.dependency_status(True, None)
                conn = self.db()
                outbox.drain(conn, self.client, self.embedder, limit=100)
                # A peek, not a claim: the handler that `dispatch` picks is the
                # one that claims the job, and it must find it still queued.
                row = conn.execute(
                    "SELECT id,kind FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
                ).fetchone()
                if row is not None:
                    self.dispatch(str(row["id"]), str(row["kind"]))
                    continue
            except Exception as exc:
                self.dependency_status(False, str(exc))
                logger.exception("durable worker iteration failed")
            self._wake.wait(self.poll_seconds)
            self._wake.clear()
