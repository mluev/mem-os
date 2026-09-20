"""Restart-safe polling worker for durable jobs and index deliveries."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from qdrant_client import QdrantClient

from . import jobs, maintenance, outbox, vectors
from .db import ConnectionPool
from .embed import Embedder

logger = logging.getLogger(__name__)

# Poll interval while the vector index is unreachable. Long enough not to
# hammer a service that is down, short enough that recovery is noticed before
# anyone asks why search is still 503.
DEGRADED_POLL_SECONDS = 5.0


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
        # The last dependency failure we reported. A vector-index outage is a
        # designed degraded state, not a fault in this code, so it is logged
        # once when it begins and once when it ends -- not as a thirty-line
        # traceback every second for as long as Qdrant happens to be down.
        self._outage: str | None = None
        self._provisioned = False
        self._last_prune = 0.0

    def start(self) -> None:
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            wait = self.poll_seconds
            try:
                # Recovery is independent of index availability and runs after
                # leases expire, even if the process restarted before expiry.
                with self.db.borrow() as conn:
                    jobs.recover_stale(conn)
            except Exception:
                logger.exception("durable recovery failed")
            ready = False
            try:
                if self._provisioned:
                    names = {row.name for row in self.client.get_collections().collections}
                    self._provisioned = all(
                        any(name == logical or name.startswith(f"{logical}__g") for name in names)
                        for logical in (vectors.MEMORIES, vectors.RAW)
                    )
                if not self._provisioned:
                    vectors.ensure_collections(self.client)
                    self._provisioned = True
                ready = True
            except Exception as exc:
                # Degraded, by design: authoritative writes continue and the
                # outbox holds their index updates until this succeeds again.
                self.dependency_status(False, str(exc))
                if self._outage is None:
                    logger.warning("vector index unavailable; deliveries are queued: %s", exc)
                self._outage = str(exc)
                self._provisioned = False
                wait = max(wait, DEGRADED_POLL_SECONDS)
            if ready and self._outage is not None:
                logger.info("vector index reachable again; draining queued deliveries")
                self._outage = None
            if ready:
                self.dependency_status(True, None)
            try:
                with self.db.borrow() as conn:
                    if ready:
                        outbox.drain(conn, self.client, self.embedder, limit=100)
                        if time.monotonic() - self._last_prune >= 3600:
                            try:
                                with maintenance.exclusive(conn):
                                    vectors.prune_retired_generations(self.client)
                                self._last_prune = time.monotonic()
                            except maintenance.MaintenanceBusy:
                                pass
                    row = conn.execute(
                        """SELECT id,kind FROM jobs WHERE status='queued' AND available_at<=now()
                             AND (%s OR kind NOT IN ('extraction','consolidation','reindex'))
                           ORDER BY available_at,created_at,id LIMIT 1""",
                        (ready,),
                    ).fetchone()
                if row is not None:
                    self.dispatch(str(row["id"]), str(row["kind"]))
                    continue
            except Exception:
                # Anything else is a fault in this code or the database, and a
                # traceback is exactly what is wanted.
                logger.exception("durable worker iteration failed")
            self._wake.wait(wait)
            self._wake.clear()
