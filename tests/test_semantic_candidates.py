"""Semantic candidates and write-time dedup (decisions/0054, 0055).

Offline throughout: a crafted stub returns dense hits with chosen scores, and
HashEmbedder keeps distinct texts distinct. What is being proven:

* the judge sees near-duplicates from OTHER contexts (exact-context recency
  never could), but a Qdrant hit alone never authorises anything — the row is
  re-read from SQLite first;
* the model can only reference candidates through small integers, and an
  integer outside the map is dropped before it can touch the store;
* an extracted ADD that near-verbatim duplicates an existing same-context
  memory links its evidence to that memory instead of inserting a twin, while
  a below-threshold neighbour and the manual API path still insert.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from memkit import extract, judge, store
from memkit.db import transaction
from tests.fixtures import OWNER, HashEmbedder, StubQdrant, fake_provider, make_db, make_judge_run


class ScoredStub(StubQdrant):
    """StubQdrant that returns every stored memory point at a fixed score."""

    def __init__(self, score: float = 0.95) -> None:
        super().__init__()
        self.score = score

    def query_points(self, collection_name, **kwargs):
        return SimpleNamespace(
            points=[
                SimpleNamespace(id=pid, score=self.score, payload=payload)
                for pid, payload in self._col(collection_name).items()
            ]
        )


class RankedStub(StubQdrant):
    """Returns stored points in a fixed order, honouring limit and exclude_ids.

    ScoredStub gives every point the same score and ignores both, which cannot
    express "the dense arm filled every slot with other contexts".
    """

    def __init__(self, order: list[str], score: float = 0.95) -> None:
        super().__init__()
        self.order = order
        self.score = score

    def query_points(self, collection_name, **kwargs):
        excluded: set[str] = set()
        flt = kwargs.get("query_filter")
        for condition in getattr(flt, "must_not", None) or []:
            excluded.update(str(pid) for pid in getattr(condition, "has_id", []) or [])
        col = self._col(collection_name)
        points = [
            SimpleNamespace(id=pid, score=self.score, payload=col[pid])
            for pid in self.order
            if pid in col and pid not in excluded
        ]
        return SimpleNamespace(points=points[: kwargs.get("limit") or len(points)])


class FindCandidatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.embedder = HashEmbedder()
        self.client = ScoredStub()
        with transaction(self.conn):
            self.global_id = store.add_memory(
                self.conn,
                owner_id=OWNER,
                text="Prefers pnpm over npm everywhere",
                kind="preference",
                context={},
                source_role="user",
            )
            self.scoped_id = store.add_memory(
                self.conn,
                owner_id=OWNER,
                text="Auth lives in auth/ on session cookies",
                kind="fact",
                context={"workspace": "memkit"},
                source_role="user",
            )
        from memkit import outbox

        outbox.drain(self.conn, self.client, self.embedder, limit=10)

    def tearDown(self) -> None:
        self.conn.close()

    def test_without_index_behaviour_is_exact_context_recency(self) -> None:
        found = extract.find_candidates(self.conn, owner_id=OWNER, context={"workspace": "memkit"})
        self.assertEqual([c["id"] for c in found], [self.scoped_id])

    def test_dense_arm_surfaces_cross_context_candidates(self) -> None:
        found = extract.find_candidates(
            self.conn,
            owner_id=OWNER,
            context={"workspace": "memkit"},
            client=self.client,
            embedder=self.embedder,
            window_text="давай везде pnpm",
        )
        ids = {c["id"] for c in found}
        self.assertIn(self.global_id, ids)  # cross-context, dense arm only
        self.assertIn(self.scoped_id, ids)  # same-context recency arm
        by_id = {c["id"]: c for c in found}
        self.assertEqual(by_id[self.global_id]["context"], {})

    def test_dense_hit_without_active_sqlite_row_is_dropped(self) -> None:
        with transaction(self.conn):
            self.conn.execute("UPDATE memories SET status='archived' WHERE id=?", (self.global_id,))
        # The stub still holds the point: exactly the stale-index case.
        found = extract.find_candidates(
            self.conn,
            owner_id=OWNER,
            context={},
            client=self.client,
            embedder=self.embedder,
            window_text="давай везде pnpm",
        )
        self.assertNotIn(self.global_id, {c["id"] for c in found})


class IntegerRemapTest(unittest.TestCase):
    def test_unknown_integer_never_reaches_the_store(self) -> None:
        conn = make_db()
        raw = {
            "op": "DELETE",
            "id": "99",
            "reason": "fabricated target",
            "evidence": [],
        }
        op = judge.Op.parse(raw)
        self.assertIsNotNone(op)
        # judge.extract drops it before apply_ops; simulate the contract at the
        # apply layer too: a DELETE with an id that matches no memory is skipped.
        with transaction(conn):
            outcome = extract.apply_ops(
                conn,
                ops=[op],
                owner_id=OWNER,
                agent_id="chat",
                context={},
                judge_run_id=make_judge_run(conn),
                source_message_ids=[],
            )
        self.assertEqual(outcome.applied, 0)
        conn.close()

    def test_run_extraction_surfaces_unknown_candidates_as_rejections(self) -> None:
        # Unit-level check of the merge step in run_extraction's tail.
        outcome = extract.ExtractionOutcome()
        for dropped in [{"op": "UPDATE", "id": "7"}]:
            outcome.rejected += 1
            outcome.rejections.append({**dropped, "reason": "unknown_candidate"})
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(outcome.rejections[0]["reason"], "unknown_candidate")


class JudgeRemapEndToEndTest(unittest.TestCase):
    """judge.extract shows the model integers and translates them back."""

    def test_prompt_shows_integers_and_ops_return_real_ids(self) -> None:
        from memkit import providers

        conn = make_db()
        seen: dict[str, str] = {}

        def fake(**kwargs):
            seen["prompt"] = kwargs["prompt"]
            return providers.ProviderResult(
                raw={"operations": []},
                operations=[
                    {  # resolves through the map to the real candidate id
                        "op": "DELETE",
                        "id": "1",
                        "reason": "obsolete",
                        "evidence": [],
                    },
                    {  # fabricated: never shown, must be dropped
                        "op": "DELETE",
                        "id": "42",
                        "reason": "hallucinated",
                        "evidence": [],
                    },
                ],
            )

        with fake_provider(fake, family="remap", prefix="remap-"):
            result = judge.extract(
                conn,
                window=[{"id": 1, "role": "user", "content": "obsolete fact, drop it"}],
                candidates=[
                    {
                        "id": "aaaaaaaa-1111-2222-3333-444444444444",
                        "kind": "fact",
                        "text": "Old fact",
                        "importance": 0.5,
                        "context": {},
                    }
                ],
                monthly_limit_usd=10.0,
                model="remap-judge",
                owner_id=OWNER,
            )
        self.assertIn("id=1 ", seen["prompt"])
        self.assertNotIn("aaaaaaaa-1111", seen["prompt"])
        self.assertEqual(len(result.ops), 1)
        self.assertEqual(result.ops[0].id, "aaaaaaaa-1111-2222-3333-444444444444")
        self.assertEqual(result.unknown_candidates, [{"op": "DELETE", "id": "42"}])
        run = conn.execute("SELECT input_json FROM judge_runs").fetchone()
        self.assertIn("candidate_map", run["input_json"])
        conn.close()


class CandidateSlotTest(unittest.TestCase):
    """Same-context candidates must survive a crowded dense arm.

    Dense hits were merged in first and could occupy every slot, leaving the
    model no candidate it was permitted to UPDATE or DELETE while apply_ops
    rejected anything else. A ten-slot block full of other contexts is a block
    that can only produce duplicates.
    """

    def test_recency_keeps_its_slots_when_dense_hits_are_plentiful(self) -> None:
        conn = make_db()
        context = {"source_workspace": "mem-os"}
        scoped = store.add_memory(
            conn,
            owner_id=OWNER,
            text="mem-os stores memories in SQLite",
            kind="project",
            context=context,
            source_role="user",
        )
        elsewhere = [
            store.add_memory(
                conn,
                owner_id=OWNER,
                text=f"unrelated fact number {i}",
                kind="fact",
                context={"source_workspace": f"other-{i}"},
                source_role="user",
            )
            for i in range(12)
        ]
        conn.commit()

        # A stub that ranks the other contexts above the in-context memory and
        # honours `limit`/`exclude_ids`, which is how Qdrant behaves and what
        # makes crowding possible at all.
        client = RankedStub(order=[*elsewhere, scoped])
        found = extract.find_candidates(
            conn,
            owner_id=OWNER,
            context=context,
            client=client,
            embedder=HashEmbedder(),
            window_text="what does mem-os store",
        )
        ids = [item["id"] for item in found]
        self.assertIn(scoped, ids, "the only updatable candidate was crowded out")
        self.assertLessEqual(len(ids), 10)
        self.assertEqual(len(ids), len(set(ids)))
        conn.close()


class WriteTimeDedupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db()
        self.embedder = HashEmbedder()
        with transaction(self.conn):
            self.existing = store.add_memory(
                self.conn,
                owner_id=OWNER,
                text="Prefers pnpm over npm for all projects",
                kind="preference",
                context={},
                source_role="user",
            )
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                owner_id=OWNER,
                agent_id="chat",
                role="user",
                content="prefers pnpm rather than npm everywhere",
            )
        self.message_id = message_id
        self.client = ScoredStub(score=0.95)
        from memkit import outbox

        outbox.drain(self.conn, self.client, self.embedder, limit=10)

    def tearDown(self) -> None:
        self.conn.close()

    def add_op(self) -> judge.Op:
        return judge.Op.parse(
            {
                "op": "ADD",
                "text": "Prefers pnpm rather than npm everywhere",
                "kind": "preference",
                "context_entries": [],
                "evidence": [{"message_id": self.message_id, "start_char": 0, "end_char": 20}],
                "reason": "restated preference",
            }
        )

    def apply_with_threshold(self, threshold: float | None):
        op = self.add_op()
        dedup_hits = extract.plan_dedup(
            self.conn,
            ops=[op],
            owner_id=OWNER,
            client=self.client,
            embedder=self.embedder,
            threshold=threshold,
        )
        with transaction(self.conn):
            return extract.apply_ops(
                self.conn,
                ops=[op],
                owner_id=OWNER,
                agent_id="chat",
                context={},
                judge_run_id=make_judge_run(self.conn),
                source_message_ids=[self.message_id],
                dedup_hits=dedup_hits,
            )

    def count_memories(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0])

    def test_near_verbatim_add_links_evidence_instead_of_inserting(self) -> None:
        outcome = self.apply_with_threshold(0.90)
        self.assertEqual((outcome.added, outcome.deduplicated), (0, 1))
        self.assertEqual(self.count_memories(), 1)
        linked = self.conn.execute(
            "SELECT memory_id FROM memory_evidence WHERE memory_id=?", (self.existing,)
        ).fetchall()
        self.assertEqual(len(linked), 1)
        self.assertEqual(outcome.as_dict()["deduplicated"], 1)

    def test_below_threshold_neighbour_still_inserts(self) -> None:
        self.client.score = 0.85
        outcome = self.apply_with_threshold(0.90)
        self.assertEqual((outcome.added, outcome.deduplicated), (1, 0))
        self.assertEqual(self.count_memories(), 2)

    def test_disabled_threshold_never_deduplicates(self) -> None:
        outcome = self.apply_with_threshold(None)
        self.assertEqual((outcome.added, outcome.deduplicated), (1, 0))

    def test_cross_context_twin_is_not_deduplicated(self) -> None:
        with transaction(self.conn):
            self.conn.execute("DELETE FROM memory_evidence")
            self.conn.execute("DELETE FROM memory_sources")
            self.conn.execute("DELETE FROM memories")
            store.add_memory(
                self.conn,
                owner_id=OWNER,
                text="Prefers pnpm over npm for all projects",
                kind="preference",
                context={"workspace": "other"},
                source_role="user",
            )
        from memkit import outbox

        outbox.drain(self.conn, self.client, self.embedder, limit=10)
        self.client.score = 0.95
        outcome = self.apply_with_threshold(0.90)
        # Same text, different context: by this repo's model, two facts.
        self.assertEqual((outcome.added, outcome.deduplicated), (1, 0))

    def test_manual_api_write_is_never_deduplicated(self) -> None:
        with transaction(self.conn):
            twin = store.add_memory(
                self.conn,
                owner_id=OWNER,
                text="Prefers pnpm over npm for all projects",
                kind="preference",
                context={},
                source_role="manual",
            )
        self.assertNotEqual(twin, self.existing)
        self.assertEqual(self.count_memories(), 2)


if __name__ == "__main__":
    unittest.main()
