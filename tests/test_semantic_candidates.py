"""Semantic candidates and write-time dedup (decisions/0054, 0055).

Offline throughout: a crafted stub returns dense hits with chosen scores, and
HashEmbedder keeps distinct texts distinct. What is being proven:

* the judge sees near-duplicates from OTHER contexts (exact-context recency
  never could), but a Qdrant hit alone never authorises anything -- the row is
  re-read from Postgres first;
* the model can only reference candidates through small integers, and an
  integer outside the map is dropped before it can touch the store;
* an extracted ADD that near-verbatim duplicates an existing same-scope,
  same-context memory links its evidence to that memory instead of inserting a
  twin, while a below-threshold neighbour and the manual API path still insert.
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace

from memkit import extract, judge, outbox, providers, store
from tests.fixtures import (
    HashEmbedder,
    StubQdrant,
    add_messages,
    apply,
    fake_provider,
    make_db,
    make_session,
    seed_team,
)


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


class TeamCase(unittest.TestCase):
    """The seeded cast, with Alice's own scope as the session's."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        self.caller = self.team.principal("alice")
        self.scope = self.caller.own_entity_id

    def tearDown(self) -> None:
        self.conn.close()

    def add_memory(self, text, kind="preference", *, context=None, scope=None, role="user") -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=scope or self.scope,
                author_id=self.team.alice_id,
                text=text,
                kind=kind,
                context=context or {},
                source_role=role,
            )


class FindCandidatesTest(TeamCase):
    def setUp(self) -> None:
        super().setUp()
        self.embedder = HashEmbedder()
        self.client = ScoredStub()
        self.global_id = self.add_memory("Prefers pnpm over npm everywhere")
        self.scoped_id = self.add_memory(
            "Auth lives in auth/ on session cookies", kind="fact", context={"workspace": "memkit"}
        )
        outbox.drain(self.conn, self.client, self.embedder, limit=10)

    def find(self, context, **kw):
        return extract.find_candidates(
            self.conn,
            scope_id=self.scope,
            allowed_scope_ids=self.caller.scopes(),
            context=context,
            **kw,
        )

    def test_without_index_behaviour_is_exact_context_recency(self) -> None:
        found = self.find({"workspace": "memkit"})
        self.assertEqual([item["id"] for item in found], [self.scoped_id])

    def test_dense_arm_surfaces_cross_context_candidates(self) -> None:
        found = self.find(
            {"workspace": "memkit"},
            client=self.client,
            embedder=self.embedder,
            window_text="давай везде pnpm",
        )
        by_id = {item["id"]: item for item in found}
        self.assertIn(self.global_id, by_id)  # cross-context, dense arm only
        self.assertIn(self.scoped_id, by_id)  # same-context recency arm
        self.assertEqual(by_id[self.global_id]["context"], {})

    def test_dense_hit_without_an_active_row_is_dropped(self) -> None:
        """Postgres stays authoritative: the index is derived and can lag."""
        self.conn.execute("UPDATE memories SET status='archived' WHERE id=%s", (self.global_id,))
        # The stub still holds the point: exactly the stale-index case.
        found = self.find(
            {}, client=self.client, embedder=self.embedder, window_text="давай везде pnpm"
        )
        self.assertNotIn(self.global_id, {item["id"] for item in found})

    def test_a_scope_the_speaker_cannot_read_never_becomes_a_candidate(self) -> None:
        """The dense arm searches every readable scope -- and only those.

        Bob's private memory is indexed in the same collection, so the filter on
        the read path is the only thing keeping it out of Alice's prompt.
        """
        bobs = self.add_memory(
            "Prefers pnpm over npm everywhere too", scope=self.team.scope_of("bob")
        )
        outbox.drain(self.conn, self.client, self.embedder, limit=10)
        found = self.find(
            {}, client=self.client, embedder=self.embedder, window_text="давай везде pnpm"
        )
        self.assertNotIn(bobs, {item["id"] for item in found})


class CandidateSlotTest(TeamCase):
    """Same-context candidates must survive a crowded dense arm.

    Dense hits were merged in first and could occupy every slot, leaving the
    model no candidate it was permitted to UPDATE or DELETE while apply_ops
    rejected anything else. A ten-slot block full of other contexts is a block
    that can only produce duplicates.
    """

    def test_recency_keeps_its_slots_when_dense_hits_are_plentiful(self) -> None:
        context = {"source_workspace": "mem-os"}
        scoped = self.add_memory(
            "mem-os stores memories in Postgres", kind="project", context=context
        )
        elsewhere = [
            self.add_memory(
                f"unrelated fact number {index}",
                kind="fact",
                context={"source_workspace": f"other-{index}"},
            )
            for index in range(12)
        ]
        # A stub that ranks the other contexts above the in-context memory and
        # honours `limit`/`exclude_ids`, which is how Qdrant behaves and what
        # makes crowding possible at all.
        client = RankedStub(order=[*elsewhere, scoped])
        outbox.drain(self.conn, client, HashEmbedder(), limit=100)
        found = extract.find_candidates(
            self.conn,
            scope_id=self.scope,
            allowed_scope_ids=self.caller.scopes(),
            context=context,
            client=client,
            embedder=HashEmbedder(),
            window_text="what does mem-os store",
        )
        ids = [item["id"] for item in found]
        self.assertIn(scoped, ids, "the only updatable candidate was crowded out")
        self.assertLessEqual(len(ids), 10)
        self.assertEqual(len(ids), len(set(ids)))


class IntegerRemapTest(TeamCase):
    """The model names targets by integer; anything else never reaches the store."""

    def test_a_target_that_no_longer_exists_is_skipped(self) -> None:
        """Fabricated integers die in `judge.extract`; this is the survivor case.

        By the time an operation reaches apply_ops its id has been translated
        out of the candidate map, so a miss here means the candidate was deleted
        between assembling the window and writing the result.
        """
        op = judge.Op.parse(
            {"op": "DELETE", "id": str(uuid.uuid4()), "reason": "obsolete", "evidence": []}
        )
        assert op is not None
        with self.conn.transaction():
            outcome = apply(self.conn, self.team, [op])
        self.assertEqual((outcome.applied, outcome.skipped), (0, 1))

    def test_run_extraction_surfaces_unknown_candidates_as_rejections(self) -> None:
        """A hallucinated target must be counted, not silently dropped.

        A bare counter hid *why* operations died, which made every prompt
        regression look identical from the job result.
        """
        add_messages(self.conn, n=10, content="drop that obsolete note about npm")

        def fake(**_):
            return providers.ProviderResult(
                raw={"operations": []},
                operations=[{"op": "DELETE", "id": "42", "reason": "hallucinated", "evidence": []}],
            )

        with fake_provider(fake, family="remap", prefix="remap-"):
            outcome = extract.run_extraction(
                self.conn,
                session_id="s-1",
                agent_id="chat",
                api_key="",
                gemini_api_key="",
                project="",
                location="",
                monthly_limit_usd=10.0,
                model="remap-judge",
                force=True,
            )
        self.assertEqual(outcome.rejected, 1)
        self.assertEqual(
            outcome.rejections, [{"op": "DELETE", "id": "42", "reason": "unknown_candidate"}]
        )


class JudgeRemapEndToEndTest(TeamCase):
    """judge.extract shows the model integers and translates them back."""

    def test_prompt_shows_integers_and_ops_return_real_ids(self) -> None:
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
                self.conn,
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
                user_id=self.team.alice_id,
            )
        self.assertIn("id=1 ", seen["prompt"])
        self.assertNotIn("aaaaaaaa-1111", seen["prompt"])
        self.assertEqual(len(result.ops), 1)
        self.assertEqual(result.ops[0].id, "aaaaaaaa-1111-2222-3333-444444444444")
        self.assertEqual(result.unknown_candidates, [{"op": "DELETE", "id": "42"}])
        run = self.conn.execute("SELECT input FROM judge_runs").fetchone()
        self.assertIn("candidate_map", run["input"])

    def test_a_fabricated_entity_number_never_leaves_the_judge(self) -> None:
        """Routing references are remapped exactly like candidate targets.

        A number outside the block the model was shown is fabricated rather than
        mistyped, so the operation is dropped instead of being routed somewhere
        plausible -- a wrong scope is a leak.
        """

        def fake(**_):
            return providers.ProviderResult(
                raw={"operations": []},
                operations=[
                    {
                        "op": "ADD",
                        "text": "The shop ships on Fridays",
                        "kind": "fact",
                        "scope": 7,
                        "reason": "stated",
                        "evidence": [{"message_id": 1, "start_char": 0, "end_char": 4}],
                    }
                ],
            )

        with fake_provider(fake, family="remap", prefix="remap-"):
            result = judge.extract(
                self.conn,
                window=[{"id": 1, "role": "user", "content": "the shop ships on Fridays"}],
                candidates=[],
                entities=[{"id": self.scope, "label": "you, the speaker", "name": "Alice"}],
                monthly_limit_usd=10.0,
                model="remap-judge",
                user_id=self.team.alice_id,
            )
        self.assertEqual(result.ops, [])
        self.assertEqual(result.unknown_entities, [{"op": "ADD", "ref": 7, "field": "scope"}])


class WriteTimeDedupTest(TeamCase):
    def setUp(self) -> None:
        super().setUp()
        self.embedder = HashEmbedder()
        self.existing = self.add_memory("Prefers pnpm over npm for all projects")
        with self.conn.transaction():
            self.message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.scope,
                agent_id="chat",
                role="user",
                content="prefers pnpm rather than npm everywhere",
            )
        self.client = ScoredStub(score=0.95)
        outbox.drain(self.conn, self.client, self.embedder, limit=10)

    def add_op(self) -> judge.Op:
        op = judge.Op.parse(
            {
                "op": "ADD",
                "text": "Prefers pnpm rather than npm everywhere",
                "kind": "preference",
                "context_entries": [],
                "evidence": [{"message_id": self.message_id, "start_char": 0, "end_char": 20}],
                "reason": "restated preference",
            }
        )
        assert op is not None
        return op

    def apply_with_threshold(self, threshold: float | None):
        op = self.add_op()
        dedup_hits = extract.plan_dedup(
            self.conn,
            ops=[op],
            scope_id=self.scope,
            client=self.client,
            embedder=self.embedder,
            threshold=threshold,
        )
        with self.conn.transaction():
            return apply(
                self.conn,
                self.team,
                [op],
                source_message_ids=[self.message_id],
                dedup_hits=dedup_hits,
            )

    def count_memories(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()["n"])

    def test_near_verbatim_add_links_evidence_instead_of_inserting(self) -> None:
        outcome = self.apply_with_threshold(0.90)
        self.assertEqual((outcome.added, outcome.deduplicated), (0, 1))
        self.assertEqual(self.count_memories(), 1)
        linked = self.conn.execute(
            "SELECT memory_id FROM memory_evidence WHERE memory_id=%s", (self.existing,)
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
        self.conn.execute("DELETE FROM memories")
        self.add_memory("Prefers pnpm over npm for all projects", context={"workspace": "other"})
        outbox.drain(self.conn, self.client, self.embedder, limit=10)
        outcome = self.apply_with_threshold(0.90)
        # Same text, different context: by this repo's model, two facts.
        self.assertEqual((outcome.added, outcome.deduplicated), (1, 0))

    def test_a_twin_in_another_scope_is_not_deduplicated(self) -> None:
        """One of two identical sentences may be shared and the other private."""
        self.conn.execute("DELETE FROM memories")
        self.add_memory("Prefers pnpm over npm for all projects", scope=self.team.team_id)
        outbox.drain(self.conn, self.client, self.embedder, limit=10)
        outcome = self.apply_with_threshold(0.90)
        self.assertEqual((outcome.added, outcome.deduplicated), (1, 0))

    def test_manual_api_write_is_never_deduplicated(self) -> None:
        twin = self.add_memory("Prefers pnpm over npm for all projects", role="manual")
        self.assertNotEqual(twin, self.existing)
        self.assertEqual(self.count_memories(), 2)


if __name__ == "__main__":
    unittest.main()
