"""Shared test fixtures: stub Qdrant, stub embedders, temp-SQLite builders.

These lived in ``tests/test_extract.py`` and were imported from there by five
other modules. That made a 1000-line extraction-test file the de-facto conftest,
so importing a fixture meant importing sixty extraction tests. They live here
now; ``test_extract.py`` imports them like everyone else.

Everything here runs offline: no model load, no container, no API key.

    .venv/bin/python -m unittest discover -s tests -t .
    uv run python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import hashlib
import struct
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import judge, vectors  # noqa: E402
from memkit.db import connect, ensure_owner, ensure_session, init_db  # noqa: E402

OWNER = "u-test"
DIM = 1024


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
    ranking, scope filtering, dedup and budget fill are covered against fake
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

    # `points` is the memories collection: that is what the pre-existing
    # assertions in test_extract/test_mutate/test_taskboard mean by it.
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
        return SimpleNamespace(
            collections=[SimpleNamespace(name=n) for n in self._store]
        )

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


def make_db(owner: str = OWNER):
    """A real temp SQLite file at the current schema — never the live DB."""
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    init_db(tmp)
    conn = connect(tmp)
    ensure_owner(conn, owner, "test")
    ensure_session(conn, "s-1", owner, "chat")
    return conn


def make_judge_run(conn, cost=0.002) -> int:
    """Insert a real judge_runs row and return its id.

    memories.judge_run_id is a foreign key, so a fabricated id is rejected --
    provenance cannot point at a judge run that never happened. Production
    always has a real row here because judge.extract() logs before applying.
    """
    cur = conn.execute(
        """INSERT INTO judge_runs
           (kind, model, prompt_version, input_json, cost_usd, created_at)
           VALUES ('extract', ?, ?, '{}', ?, '2026-07-01T00:00:00Z')""",
        (judge.DEFAULT_MODEL, judge.PROMPT_VERSION, cost),
    )
    conn.commit()
    return int(cur.lastrowid)


def add_messages(conn, n=10, role="user", content="hello there friend", session="s-1"):
    ids = []
    for i in range(n):
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES (?, ?, ?, '2026-07-01T00:00:00Z')",
            (session, role, f"{content} {i}"),
        )
        ids.append(int(cur.lastrowid))
    conn.commit()
    return ids


def apply(conn, q, ops, **kw):
    from memkit import extract

    run_id = kw.get("judge_run_id")
    if run_id is None:
        run_id = make_judge_run(conn)
    return extract.apply_ops(
        conn, q, kw.get("embedder") or StubEmbedder(), ops=ops, owner_id=OWNER,
        agent_id=kw.get("agent_id", "chat"), scope_key=kw.get("scope_key"),
        judge_run_id=run_id,
        source_message_ids=kw.get("source_message_ids", []),
    )
