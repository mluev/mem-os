"""Shared test fixtures: stub Qdrant, stub embedders, and a seeded team.

Everything here runs offline: no model load, no vector container, no API key.
The database is real (see ``conftest.py``) because the scope predicates and the
full-text configuration are most of what these tests assert.

    uv run pytest -q
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import auth, db, entities, judge, principal, providers, users, vectors

DIM = 1024

TEAM_NAME = "Test Team"
PASSWORD = "a-long-enough-test-password"


class StubEmbedder:
    """One constant unit vector for every text.

    Deterministic and free, which is why six test modules depend on it. The
    consequence to remember: every pair of texts has cosine 1.0, so anything
    testing *dedup* or *distinctness* needs `HashEmbedder` instead.
    """

    # `load`/`ready`/`device` mirror embed.Embedder because api.lifespan calls
    # load() and GET /healthz reports the other two.
    device = "stub"

    def load(self) -> None:
        pass

    @property
    def ready(self) -> bool:
        return True

    def encode_one(self, text: str) -> list[float]:
        return [1.0] + [0.0] * (DIM - 1)

    def encode(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        return [self.encode_one(t) for t in texts]


class HashEmbedder(StubEmbedder):
    """Distinct deterministic unit vectors, seeded from the text itself.

    For tests where two memories must not read as duplicates. Uses sha256 rather
    than ``hash()`` because the built-in is salted per process, which would make
    a dedup assertion pass or fail depending on the run.
    """

    def encode_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        # Stretch 32 bytes into DIM floats in [-1, 1), then L2-normalise so the
        # dot product is the cosine -- the same invariant embed.py guarantees.
        raw = (digest * (DIM * 4 // len(digest) + 1))[: DIM * 4]
        vals = [v / 2**31 - 1.0 for v in struct.unpack(f"{DIM}I", raw)]
        norm = sum(v * v for v in vals) ** 0.5 or 1.0
        return [v / norm for v in vals]


class StubQdrant:
    """In-memory stand-in for QdrantClient, one dict per collection.

    Deliberately *not* a Qdrant emulator. `query_points` returns nothing: search
    ranking, context filtering, dedup and budget fill are covered against fake
    hits in `test_retrieval.py`, and reimplementing `Filter` semantics
    (`min_should`, `IsEmptyCondition`, `HasIdCondition`) here would be a second,
    wrong copy of the read path. What this stub is for is asserting which writes
    reached the index, and how many.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, dict]] = {
            vectors.MEMORIES: {},
            vectors.RAW: {},
        }
        self.deleted: list[str] = []

    # `points` is the active memories collection used by test assertions.
    @property
    def points(self) -> dict[str, dict]:
        return self._store[vectors.MEMORIES]

    @property
    def raw_points(self) -> dict[str, dict]:
        return self._store[vectors.RAW]

    def _col(self, name: str) -> dict[str, dict]:
        return self._store.setdefault(name, {})

    def upsert(self, collection_name, points, wait=True):
        col = self._col(collection_name)
        for p in points:
            col[str(p.id)] = p.payload

    def delete(self, collection_name, points_selector, wait=True):
        col = self._col(collection_name)
        for pid in points_selector:
            self.deleted.append(str(pid))
            col.pop(str(pid), None)

    def set_payload(self, collection_name, points, payload, wait=True):
        col = self._col(collection_name)
        for pid in points:
            col[str(pid)].update(payload)

    def query_points(self, collection_name, **kwargs):
        return SimpleNamespace(points=[])

    # --- collection management: without these, /healthz, /v1/admin/stats and
    # --- /v1/admin/reindex raise instead of exercising their route code.

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self._store])

    def create_collection(self, collection_name, **kwargs):
        self._store.setdefault(collection_name, {})

    def create_payload_index(self, **kwargs):
        pass

    def delete_collection(self, collection_name, **kwargs):
        self._store[collection_name] = {}

    def count(self, collection_name, exact=True):
        return SimpleNamespace(count=len(self._store.get(collection_name, {})))

    def close(self):
        pass


class SearchableQdrant(StubQdrant):
    """StubQdrant plus a real dense search over upserted vectors.

    The plain stub returns no hits, which makes the 0.60-weight dense arm --
    the dominant term in the ranking formula -- invisible to every deterministic
    test. Use this wherever a test's claim depends on real similarity, notably
    abstention: a floor that is never reached cannot be proved to work against
    an empty index.

    Filters are honoured only for the two keyword conditions the read path
    actually sends (`owner_id`, `status`); anything else is ignored, and the
    docstring is the contract.
    """

    def __init__(self) -> None:
        super().__init__()
        self._vectors: dict[tuple[str, str], list[float]] = {}

    def upsert(self, collection_name, points, wait=True):
        col = self._col(collection_name)
        for p in points:
            col[str(p.id)] = p.payload
            vector = p.vector["dense"] if isinstance(p.vector, dict) else p.vector
            self._vectors[(collection_name, str(p.id))] = vector

    def delete(self, collection_name, points_selector, wait=True):
        for pid in points_selector:
            self._vectors.pop((collection_name, str(pid)), None)
        super().delete(collection_name, points_selector, wait=wait)

    @staticmethod
    def _matches(payload: dict, query_filter) -> bool:
        for condition in getattr(query_filter, "must", None) or []:
            key = getattr(condition, "key", None)
            match = getattr(condition, "match", None)
            if key is None or match is None:
                continue
            wanted = getattr(match, "value", None)
            allowed = getattr(match, "any", None)
            if wanted is not None and payload.get(key) != wanted:
                return False
            if allowed is not None and payload.get(key) not in allowed:
                return False
        return True

    def query_points(
        self,
        collection_name,
        query=None,
        using="dense",
        limit=10,
        query_filter=None,
        with_payload=True,
        with_vectors=False,
    ):
        scored = []
        for pid, payload in self._col(collection_name).items():
            vec = self._vectors.get((collection_name, pid))
            if vec is None or not self._matches(payload, query_filter):
                continue
            hit = SimpleNamespace(
                id=pid,
                score=sum(a * b for a, b in zip(query, vec, strict=True)),
                payload=payload,
            )
            if with_vectors:
                hit.vector = {"dense": vec}
            scored.append(hit)
        scored.sort(key=lambda hit: -hit.score)
        return SimpleNamespace(points=scored[:limit])

    def scroll(
        self,
        collection_name,
        limit=100,
        offset=None,
        with_payload=True,
        with_vectors=False,
        scroll_filter=None,
    ):
        items = [
            (pid, payload)
            for pid, payload in self._col(collection_name).items()
            if self._matches(payload, scroll_filter)
        ]
        items.sort()
        start = (
            0
            if offset is None
            else next((i for i, (pid, _) in enumerate(items) if pid == str(offset)), 0)
        )
        page = items[start : start + limit]
        records = []
        for pid, payload in page:
            record = SimpleNamespace(id=pid, payload=payload)
            if with_vectors:
                record.vector = {"dense": self._vectors.get((collection_name, pid))}
            records.append(record)
        nxt = items[start + limit][0] if start + limit < len(items) else None
        return records, nxt


class CountingEmbedder(HashEmbedder):
    """HashEmbedder that records how it was called.

    Batching is a correctness claim about cost and latency, not a style
    preference, so tests assert the shape of the calls: one `encode` for a
    batch, never N calls of `encode_one`.
    """

    def __init__(self) -> None:
        self.encode_calls: list[int] = []
        self.encode_one_calls = 0
        # HashEmbedder.encode delegates to encode_one, so a naive counter would
        # charge a batch call for every text in it. Only direct calls count.
        self._in_batch = False

    def encode(self, texts):
        self.encode_calls.append(len(texts))
        self._in_batch = True
        try:
            return super().encode(texts)
        finally:
            self._in_batch = False

    def encode_one(self, text):
        if not self._in_batch:
            self.encode_one_calls += 1
        return super().encode_one(text)


@contextlib.contextmanager
def fake_provider(handler, *, family: str = "fake", prefix: str = "fake-"):
    """Register a judge provider for the duration of a test, then remove it.

    `providers.register_provider` mutates module state. Tests that registered a
    provider and never removed it leaked it into every later test in the same
    process, so registration belongs behind a context manager.

    `handler` receives the same keywords as `providers.call` and returns a
    `providers.ProviderResult`; raising from it exercises the failure paths.
    """

    def call(**kwargs):
        return handler(**kwargs)

    providers.register_provider(family, model_prefix=prefix, call=call)
    try:
        yield
    finally:
        providers._CUSTOM_PROVIDERS.pop(family, None)


@dataclass
class Team:
    """A seeded instance: two people, a team, and a project they share.

    Two users rather than one, always, because almost every claim worth making
    about a team system is a claim about what the *other* person can see.
    """

    conn: Any
    alice: Any
    bob: Any
    alice_key: str
    bob_key: str
    team_id: str
    project_id: str

    @property
    def alice_id(self) -> str:
        return str(self.alice["id"])

    @property
    def bob_id(self) -> str:
        return str(self.bob["id"])

    def principal(self, who: str = "alice"):
        return principal.load(self.conn, self.alice_id if who == "alice" else self.bob_id)

    def scope_of(self, who: str = "alice") -> str:
        return self.principal(who).own_entity_id


def seed_team(conn, *, project: str = "Mem OS", aliases: tuple[str, ...] = ("memkit",)) -> Team:
    """Create the standard cast. Idempotent within one clean database."""
    with conn.transaction():
        team = entities.ensure_team(conn, name=TEAM_NAME)
        alice = users.create(
            conn, handle="alice", display_name="Alice Ivanova", password=PASSWORD, role="admin"
        )
        bob = users.create(conn, handle="bob", display_name="Bob Petrov", password=PASSWORD)
        alice_key = auth.mint_api_key(conn, user_id=str(alice["id"]), name="test")
        bob_key = auth.mint_api_key(conn, user_id=str(bob["id"]), name="test")
        shared = entities.create(
            conn,
            kind="project",
            name=project,
            created_by=str(alice["id"]),
            aliases=list(aliases),
        )
        entities.set_member(
            conn, entity_id=str(shared["id"]), user_id=str(bob["id"]), role="member"
        )
    return Team(
        conn=conn,
        alice=alice,
        bob=bob,
        alice_key=alice_key.token,
        bob_key=bob_key.token,
        team_id=str(team["id"]),
        project_id=str(shared["id"]),
    )


def make_db(seed: bool = True):
    """A connection to the test database, emptied, optionally seeded.

    `conftest.clean_database` already truncates between tests; this exists for
    the tests that want the cast and a session ready to write into.
    """
    conn = db.connect(os.environ["MEMKIT_DATABASE_URL"])
    db.truncate_all(conn)
    if seed:
        team = seed_team(conn)
        make_session(conn, team)
    return conn


def make_session(conn, team: Team, *, session_id: str = "s-1", who: str = "alice", scope=None):
    """A session owned by one of the cast, in their own scope by default."""
    with conn.transaction():
        conn.execute(
            """INSERT INTO sessions (id,user_id,scope_id,agent_id,started_at)
               VALUES (%s,%s,%s,'chat',now()) ON CONFLICT (id) DO NOTHING""",
            (
                session_id,
                team.alice_id if who == "alice" else team.bob_id,
                scope or team.scope_of(who),
            ),
        )
    return session_id


def make_judge_run(conn, cost=0.002, user_id=None) -> int:
    """Insert a real judge_runs row and return its id.

    memories.judge_run_id is a foreign key, so a fabricated id is rejected --
    provenance cannot point at a judge run that never happened. Production
    always has a real row here because judge.extract() logs before applying.
    """
    with conn.transaction():
        row = conn.execute(
            """INSERT INTO judge_runs
               (user_id,kind,model,prompt_version,input,cost_usd,created_at)
               VALUES (%s,'extract',%s,%s,'{}'::jsonb,%s,now())
               RETURNING id""",
            (user_id, judge.DEFAULT_MODEL, judge.PROMPT_VERSION, cost),
        ).fetchone()
    return int(row["id"])


def add_messages(
    conn, n=10, role="user", content="hello there friend", session="s-1", user_id=None
):
    if user_id is None:
        row = conn.execute("SELECT user_id FROM sessions WHERE id=%s", (session,)).fetchone()
        user_id = str(row["user_id"])
    ids = []
    with conn.transaction():
        for i in range(n):
            row = conn.execute(
                """INSERT INTO messages (session_id,user_id,role,content,created_at)
                   VALUES (%s,%s,%s,%s,now()) RETURNING id""",
                (session, user_id, role, f"{content} {i}"),
            ).fetchone()
            ids.append(int(row["id"]))
    return ids


def apply(conn, team: Team, ops, **kw):
    """Run apply_ops the way run_extraction does, for one of the cast."""
    from memkit import extract

    who = kw.get("who", "alice")
    caller = team.principal(who)
    run_id = kw.get("judge_run_id")
    if run_id is None:
        run_id = make_judge_run(conn, user_id=caller.user_id)
    return extract.apply_ops(
        conn,
        ops=ops,
        user_id=caller.user_id,
        session_scope_id=kw.get("scope_id", caller.own_entity_id),
        own_scope_id=caller.own_entity_id,
        team_scope_id=caller.team_entity_id,
        writable_scope_ids=sorted(caller.writable_scope_ids),
        agent_id=kw.get("agent_id", "chat"),
        context=kw.get("context", {}),
        judge_run_id=run_id,
        source_message_ids=kw.get("source_message_ids", []),
        entity_map=kw.get("entity_map"),
        dedup_hits=kw.get("dedup_hits"),
    )
