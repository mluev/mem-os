"""Drive a running Mem OS over its public HTTP API, as an agent would.

Every conversation gets its own user, created with an administrator key: a
private scope is the only isolation that also holds for dedup candidates,
supersession targets and dreaming, all of which look across what a user can
read. Turns are ingested with the session's recorded date, so extraction
resolves "last week" against the benchmark's calendar rather than today's.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx

from .datasets import Conversation, Question

BATCH = 100


class BenchError(RuntimeError):
    pass


def _check(response: httpx.Response, what: str) -> dict[str, Any]:
    if response.status_code >= 400:
        raise BenchError(f"{what}: HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


class Memkit:
    def __init__(
        self,
        http: httpx.Client,
        *,
        admin_key: str,
        run_id: str,
        on_wait: Callable[[], None] | None = None,
    ) -> None:
        self.http = http
        self.admin = {"X-API-Key": admin_key}
        self.run_id = run_id
        # Tests run queued jobs synchronously here; a server has its own worker.
        self.on_wait = on_wait

    def provision(self, conversation: Conversation) -> str:
        """A fresh user and key for one conversation; returns the key."""
        handle = f"bench-{self.run_id}-{conversation.conversation_id}".lower()
        handle = "".join(c if c.isalnum() or c in "_.-" else "-" for c in handle)[:62]
        user = _check(
            self.http.post(
                "/v1/users",
                headers=self.admin,
                json={
                    "handle": handle,
                    "display_name": f"Benchmark {conversation.conversation_id}",
                    "password": secrets.token_urlsafe(24),
                },
            ),
            "create user",
        )
        key = _check(
            self.http.post(
                "/v1/api-keys",
                headers=self.admin,
                json={"name": f"bench {self.run_id}", "user_id": user["id"]},
            ),
            "create key",
        )
        return str(key["secret"])

    def ingest(self, key: str, conversation: Conversation) -> dict[int, str]:
        """Post every turn, close every session; map message id -> turn id."""
        auth = {"X-API-Key": key}
        mapping: dict[int, str] = {}
        for session in conversation.sessions:
            events = []
            for index, turn in enumerate(session.turns):
                event: dict[str, Any] = {
                    "session_id": f"{self.run_id}-{session.session_id}"[:256],
                    "agent_id": "bench",
                    "role": turn.role,
                    "content": turn.text[:100_000],
                    "external_source": f"bench-{self.run_id}",
                    "external_id": turn.turn_id,
                }
                if session.date is not None:
                    # One second apart keeps the recorded order and the date.
                    event["created_at"] = (session.date + timedelta(seconds=index)).isoformat()
                events.append(event)
            for start in range(0, len(events), BATCH):
                chunk = events[start : start + BATCH]
                body = _check(
                    self.http.post(
                        "/v1/evidence/events:batch", headers=auth, json={"events": chunk}
                    ),
                    "ingest",
                )
                for event, item in zip(chunk, body["items"], strict=True):
                    mapping[int(item["message_id"])] = str(event["external_id"])
            if events:
                _check(
                    self.http.post(f"/v1/sessions/{events[0]['session_id']}/close", headers=auth),
                    "close session",
                )
        return mapping

    def wait(self, key: str, *, timeout: float = 3600.0, poll: float = 2.0) -> dict[str, int]:
        """Until the user's extraction and dream jobs have finished."""
        auth = {"X-API-Key": key}
        deadline = time.monotonic() + timeout
        while True:
            if self.on_wait is not None:
                self.on_wait()
            jobs = _check(self.http.get("/v1/jobs?limit=200", headers=auth), "jobs")["items"]
            active = [job for job in jobs if job["status"] in {"queued", "running"}]
            if not active:
                counts: dict[str, int] = {}
                for job in jobs:
                    counts[f"{job['kind']}:{job['status']}"] = (
                        counts.get(f"{job['kind']}:{job['status']}", 0) + 1
                    )
                return counts
            if time.monotonic() > deadline:
                raise BenchError(f"{len(active)} jobs still active after {timeout}s")
            time.sleep(poll)

    def search(
        self,
        key: str,
        question: Question,
        *,
        mode: str,
        budget_tokens: int,
        limit: int,
        rewrite: bool,
    ) -> tuple[dict[str, Any], float]:
        body: dict[str, Any] = {
            "query": question.question,
            "include_sources": mode != "raw",
            "source_context_chars": 600,
            "include_history": True,
            "include_related": True,
            "include_raw": mode in {"hybrid", "raw"},
            "budget_tokens": budget_tokens,
            "limit": limit,
            "rewrite_query": rewrite,
        }
        if mode == "raw":
            body["kinds"] = ["evidence"]
        if question.question_date is not None:
            body["as_of"] = question.question_date.isoformat()
        started = time.perf_counter()
        payload = _check(
            self.http.post("/v1/memories/search", headers={"X-API-Key": key}, json=body),
            "search",
        )
        return payload, (time.perf_counter() - started) * 1000
