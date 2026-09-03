"""The eval harness must keep working against the library it measures.

eval/ rotted silently against the v4 rebuild — `score()` called signatures that
no longer existed, so the one instrument that gates every quality change could
not run at all. This suite imports eval/run.py against a real temp database and
a searchable stub index so any future signature drift fails here, offline,
instead of at measurement time.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.run import load_cases, score
from memkit import outbox, store
from tests.fixtures import OWNER, HashEmbedder, StubQdrant

QUERIES_YAML = """\
- id: pref
  query: "my favorite color is teal by the way"
  expect_any: ["favorite color is teal"]
- id: deploy
  query: "we deployed the new billing service to production"
  expect_any: ["billing service"]
  answerable_by: [raw]
"""


class SearchableQdrant(StubQdrant):
    """StubQdrant plus a real dense search over upserted vectors.

    The shared stub deliberately returns no hits from query_points; the eval
    exercises the read path end to end, so this test needs actual ranking.
    Filters are ignored: the corpus is single-owner and fully active.
    """

    def __init__(self) -> None:
        super().__init__()
        self._vectors: dict[tuple[str, str], list[float]] = {}

    def upsert(self, collection_name, points, wait=True):
        col = self._col(collection_name)
        for p in points:
            col[str(p.id)] = p.payload
            self._vectors[(collection_name, str(p.id))] = p.vector["dense"]

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
        scored = [
            SimpleNamespace(
                id=pid,
                score=sum(a * b for a, b in zip(query, vec, strict=True)),
                payload=payload,
            )
            for pid, payload in self._col(collection_name).items()
            if (vec := self._vectors.get((collection_name, pid))) is not None
        ]
        scored.sort(key=lambda hit: -hit.score)
        return SimpleNamespace(points=scored[:limit])


class EvalHarnessTest(unittest.TestCase):
    def setUp(self) -> None:
        from tests.fixtures import make_db

        self.conn = make_db()
        self.embedder = HashEmbedder()
        self.client = SearchableQdrant()
        self.settings = SimpleNamespace(owner_id=OWNER)

        store.add_message(
            self.conn,
            session_id="s-1",
            owner_id=OWNER,
            agent_id="chat",
            role="user",
            content="my favorite color is teal by the way",
        )
        store.add_message(
            self.conn,
            session_id="s-1",
            owner_id=OWNER,
            agent_id="chat",
            role="user",
            content="we deployed the new billing service to production",
        )
        store.add_memory(
            self.conn,
            owner_id=OWNER,
            text="favorite color is teal",
            kind="preference",
            source_role="user",
        )
        self.conn.commit()
        outbox.drain(self.conn, self.client, self.embedder, limit=50)

        path = Path(tempfile.mkdtemp()) / "queries.yaml"
        path.write_text(QUERIES_YAML)
        self.cases = load_cases(path)

    def tearDown(self) -> None:
        self.conn.close()

    def test_load_cases_parses_answerable_by(self) -> None:
        by_id = {case.id: case for case in self.cases}
        self.assertEqual(by_id["pref"].answerable_by, ("raw", "memories"))
        self.assertEqual(by_id["deploy"].answerable_by, ("raw",))

    def test_memories_target_scores_end_to_end(self) -> None:
        cases = [c for c in self.cases if "memories" in c.answerable_by]
        m = score(
            self.conn,
            self.client,
            self.embedder,
            self.settings,
            cases,
            target="memories",
            limit=10,
        )
        self.assertEqual(m["cases"], 1)
        self.assertEqual(m["recall"], 1.0)
        self.assertEqual(m["rejects"], 0)
        self.assertGreater(m["mean_tokens"], 0)

    def test_raw_target_scores_end_to_end(self) -> None:
        m = score(
            self.conn,
            self.client,
            self.embedder,
            self.settings,
            self.cases,
            target="raw",
            limit=10,
        )
        self.assertEqual(m["cases"], 2)
        self.assertEqual(m["recall"], 1.0)
        self.assertEqual(m["mrr"], 1.0)


if __name__ == "__main__":
    unittest.main()
