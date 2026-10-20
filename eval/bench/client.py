"""Drive a running Mem OS over its public HTTP API, as an agent would.

Every conversation gets its own user, created with an administrator key: a
private scope is the only isolation that also holds for dedup candidates,
supersession targets and dreaming, all of which look across what a user can
read. Turns are ingested with the session's recorded date, so extraction
resolves "last week" against the benchmark's calendar rather than today's.

Every benchmark user also joins the instance's team scope -- membership is
system-managed -- so searches are narrowed to the conversation's own scope,
and `team_routed` counts what the extractor sent to the team instead: a fact
there is lost to this conversation and visible to every other one, which is
the same confound memorybench removed with one container per conversation.
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
        index_grace: float = 300.0,
    ) -> None:
        self.http = http
        self.admin = {"X-API-Key": admin_key}
        self.run_id = run_id
        # Tests run queued jobs synchronously here; a server has its own worker.
        self.on_wait = on_wait
        # Seconds to wait for the shared vector-index outbox after jobs finish.
        self.index_grace = index_grace

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

    def scopes(self, key: str) -> dict[str, str]:
        """The conversation user's own scope and the team's, by slug."""
        me = _check(self.http.get("/v1/auth/me", headers={"X-API-Key": key}), "whoami")
        by_id = {scope["id"]: scope["slug"] for scope in me.get("scopes") or []}
        return {
            "own": by_id[me["own_entity_id"]],
            "team": by_id.get(me.get("team_entity_id") or "", ""),
            "handle": me["handle"],
        }

    def team_routed(self, key: str, scopes: dict[str, str]) -> int:
        """Memories this conversation's extraction filed into the team scope."""
        if not scopes.get("team"):
            return 0
        page = _check(
            self.http.get(
                f"/v1/memories?scope={scopes['team']}&limit=500", headers={"X-API-Key": key}
            ),
            "team memories",
        )
        return sum(1 for item in page["items"] if item.get("author") == scopes["handle"])

    def spend(self) -> float:
        """This month's server-side model spend: extraction, dreams, rewrites."""
        metrics = _check(self.http.get("/v1/admin/metrics", headers=self.admin), "metrics")
        return float(metrics.get("month_spend_usd") or 0.0)

    def server_config(self) -> dict[str, Any]:
        """The prompt, policy and dreaming mode the server is running."""
        health = _check(self.http.get("/v1/admin/health", headers=self.admin), "health")
        return dict(health.get("config") or {})

    def dream(
        self, key: str, *, max_clusters: int = 8, max_rounds: int = 20, **wait: Any
    ) -> dict[str, Any]:
        """Dream the conversation's scope until it has caught up.

        One dream processes at most 40 fresh memories, so a long conversation
        needs several; each round waits for its job, as memorybench waits on
        Supermemory's dreamingStatus before asking anything.
        """
        auth = {"X-API-Key": key}
        rounds, caught_up = 0, False
        totals: dict[str, int] = {"superseded": 0, "extended": 0, "inferred": 0}
        while rounds < max_rounds and not caught_up:
            queued = _check(
                self.http.post(
                    "/v1/dream",
                    headers=auth,
                    json={"dry_run": False, "max_clusters": max_clusters},
                ),
                "dream",
            )
            self.wait(key, **wait)
            job = _check(self.http.get(f"/v1/jobs/{queued['job_id']}", headers=auth), "dream job")
            if job.get("status") != "complete":
                raise BenchError(f"dream job {queued['job_id']} ended {job.get('status')}")
            result = job.get("result") or {}
            for name in totals:
                totals[name] += int(result.get(name) or 0)
            caught_up = bool(result.get("caught_up"))
            rounds += 1
        return {"rounds": rounds, "caught_up": caught_up, **totals}

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

    def _active(self, auth: dict[str, str]) -> int:
        # Filtered by status, so a user with more than a page of finished jobs
        # cannot hide one that is still running.
        return sum(
            len(
                _check(self.http.get(f"/v1/jobs?status={status}&limit=200", headers=auth), "jobs")[
                    "items"
                ]
            )
            for status in ("queued", "running")
        )

    def _outbox_pending(self) -> int:
        metrics = _check(self.http.get("/v1/admin/metrics", headers=self.admin), "metrics")
        return int(metrics.get("outbox_pending") or 0)

    def wait(
        self,
        key: str,
        *,
        timeout: float = 3600.0,
        poll: float = 2.0,
    ) -> dict[str, int]:
        """Until the user's jobs have finished and the vector index has caught up.

        A finished job has written Postgres; the dense arm only sees its memories
        once the index outbox has drained. The outbox is shared by the whole
        deployment, so it gets a bounded grace period rather than the full
        timeout: a permanently failing entry is the operator's problem, not a
        reason to stall the run.
        """
        auth = {"X-API-Key": key}
        deadline = time.monotonic() + timeout
        while True:
            if self.on_wait is not None:
                self.on_wait()
            active = self._active(auth)
            if not active:
                break
            if time.monotonic() > deadline:
                raise BenchError(f"{active} jobs still active after {timeout}s")
            time.sleep(poll)
        grace = time.monotonic() + self.index_grace
        pending = self._outbox_pending()
        while pending and time.monotonic() < grace:
            time.sleep(poll)
            pending = self._outbox_pending()
        jobs = _check(self.http.get("/v1/jobs?limit=200", headers=auth), "jobs")["items"]
        counts: dict[str, int] = {"outbox_pending": pending}
        for job in jobs:
            name = f"{job['kind']}:{job['status']}"
            counts[name] = counts.get(name, 0) + 1
        return counts

    def search(
        self,
        key: str,
        question: Question,
        *,
        mode: str,
        budget_tokens: int,
        limit: int,
        rewrite: bool,
        policy: str = "",
        scope: str = "",
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
        if policy:
            body["policy_id"] = policy
        if scope:
            # Only the conversation's own memories: see the module docstring.
            body["scopes"] = [scope]
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
