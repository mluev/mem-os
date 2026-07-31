"""Nightly consolidation.

Runs offline against the same stub Qdrant and stub embedder as the extraction
tests. The model call is the only part not covered; everything that happens to
SQLite and Qdrant afterwards is.

The thresholds asserted here are measured, not chosen: on this corpus a real
duplicate pair ("User's name is Maga Luev" / "User's name is Maga (or
MagaLoviev)") sits at cosine 0.9278, and the pair that must never merge ("Prefers
pnpm" / "Prefers pytest") at 0.7422.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import consolidate, providers, store  # noqa: E402
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db  # noqa: E402

MEASURED_DUPLICATE = 0.9278
MEASURED_DISTINCT = 0.7422


class ClusteringQdrant(StubQdrant):
    """Holds a cosine table keyed by fact text.

    The similarity itself runs in Qdrant, so what is testable here is the graph
    logic on top of it: which scores become edges, and how edges become components.
    The table is consumed by a patched `_neighbours` (see `TestClustering._cluster`)
    rather than by `query_points`, because the stub embedder gives every text the
    same vector and a vector search over it cannot distinguish anything.
    """

    def __init__(self, scores: dict[tuple[str, str], float] | None = None) -> None:
        super().__init__()
        self.scores = scores or {}
        self.texts: dict[str, str] = {}


def add(conn, text, *, type="fact", importance=0.6, scope="user",
        valid_until=None, updated=None, retrieved=None):
    memory_id = store.add_memory(
        conn, StubQdrant(), StubEmbedder(), owner_id=OWNER, text=text,
        type=type, scope=scope, importance=importance, valid_until=valid_until,
    )
    if updated:
        conn.execute("UPDATE memories SET updated_at=? WHERE id=?", (updated, memory_id))
    if retrieved is not None:
        conn.execute(
            "UPDATE memories SET last_retrieved_at=? WHERE id=?", (retrieved, memory_id)
        )
    conn.commit()
    return memory_id


class TestExpiry(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def test_a_past_valid_until_is_selected(self):
        old = add(self.conn, "Sprint goal", type="task", valid_until="2020-01-01T00:00:00Z")
        self.assertEqual(
            consolidate.expire_by_validity(self.conn, owner_id=OWNER), [old]
        )

    def test_a_future_valid_until_is_left_alone(self):
        add(self.conn, "Sprint goal", type="task", valid_until="2099-01-01T00:00:00Z")
        self.assertEqual(consolidate.expire_by_validity(self.conn, owner_id=OWNER), [])

    def test_no_valid_until_is_never_expired(self):
        add(self.conn, "Lives in Tashkent")
        self.assertEqual(consolidate.expire_by_validity(self.conn, owner_id=OWNER), [])

    def test_same_day_expiry_is_caught(self):
        """The comparison bug this column had everywhere else.

        Stored stamps use a literal 'T'; datetime('now') yields a space, and at
        offset 10 'T' (0x54) sorts above ' ' (0x20), so a same-day expiry read as
        still valid. The query uses strftime with the stored format instead.
        """
        expired = self.conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 hour') s"
        ).fetchone()["s"]
        memory_id = add(self.conn, "Ends today", type="task", valid_until=expired)
        self.assertIn(memory_id, consolidate.expire_by_validity(self.conn, owner_id=OWNER))


class TestDemotion(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def _stale(self, days=90):
        return {r["id"] for r in consolidate.stale_facts(
            self.conn, owner_id=OWNER, days=days
        )}

    def test_long_unretrieved_fact_is_stale(self):
        memory_id = add(self.conn, "Old preference", retrieved="2020-01-01T00:00:00Z")
        self.assertIn(memory_id, self._stale())

    def test_recently_retrieved_fact_is_not(self):
        recent = self.conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 day') s"
        ).fetchone()["s"]
        memory_id = add(self.conn, "Fresh preference", retrieved=recent)
        self.assertNotIn(memory_id, self._stale())

    def test_a_brand_new_never_retrieved_fact_gets_a_grace_period(self):
        # Extracted this morning: it has not had a chance to surface yet, and
        # demoting it would punish the extractor for the clock.
        memory_id = add(self.conn, "Just extracted")
        self.assertNotIn(memory_id, self._stale())

    def test_an_old_never_retrieved_fact_is_stale(self):
        memory_id = add(self.conn, "Never surfaced")
        self.conn.execute(
            "UPDATE memories SET created_at='2020-01-01T00:00:00Z' WHERE id=?",
            (memory_id,),
        )
        self.conn.commit()
        self.assertIn(memory_id, self._stale())

    def test_zero_importance_is_not_demoted_further(self):
        memory_id = add(self.conn, "Bottomed out", importance=0.0)
        self.conn.execute(
            "UPDATE memories SET created_at='2020-01-01T00:00:00Z' WHERE id=?",
            (memory_id,),
        )
        self.conn.commit()
        self.assertNotIn(memory_id, self._stale())


class TestClustering(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.q = ClusteringQdrant()

    def _cluster(self, threshold=0.92):
        # Wire the stub's text table from what is actually in the store.
        rows = self.conn.execute("SELECT id, text FROM memories").fetchall()
        self.q.texts = {r["id"]: r["text"] for r in rows}

        def neighbours(client, *, vector, owner_id, type_, threshold, limit):
            # Resolve text pairs from the table into ids, mirroring what a Qdrant
            # search above the threshold would return.
            out = []
            for text in self.q.texts.values():
                for (a, b), score in self.q.scores.items():
                    if text in (a, b) and score >= threshold:
                        other = b if text == a else a
                        other_id = next(
                            (i for i, t in self.q.texts.items() if t == other), None
                        )
                        if other_id:
                            out.append(other_id)
            return out

        with patch.object(consolidate, "_neighbours", neighbours):
            return consolidate.find_clusters(
                self.conn, self.q, StubEmbedder(),
                owner_id=OWNER, threshold=threshold,
            )

    def test_the_measured_duplicate_pair_clusters(self):
        a = "User's name is Maga Luev."
        b = "User's name is Maga (or MagaLoviev)."
        add(self.conn, a)
        add(self.conn, b)
        self.q.scores = {(a, b): MEASURED_DUPLICATE}
        clusters = self._cluster()
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 2)

    def test_the_measured_distinct_pair_does_not(self):
        a, b = "Prefers pnpm", "Prefers pytest"
        add(self.conn, a, type="preference")
        add(self.conn, b, type="preference")
        self.q.scores = {(a, b): MEASURED_DISTINCT}
        self.assertEqual(self._cluster(), [])

    def test_a_transitive_chain_becomes_one_component(self):
        # A close to B, B close to C, A not close to C: all three describe the same
        # subject, so a single pass over pairs would wrongly leave two clusters.
        a, b, c = "Name is Maga", "Name is Maga L.", "Name is Maga Luev"
        for text in (a, b, c):
            add(self.conn, text)
        self.q.scores = {(a, b): 0.95, (b, c): 0.95, (a, c): 0.80}
        clusters = self._cluster()
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0]), 3)

    def test_an_oversized_cluster_is_skipped_not_merged(self):
        texts = [f"Prefers thing number {i}" for i in range(consolidate.MAX_CLUSTER + 2)]
        for text in texts:
            add(self.conn, text, type="preference")
        self.q.scores = {
            (texts[0], t): 0.99 for t in texts[1:]
        }
        self.q.scores.update({(a, b): 0.99 for a in texts for b in texts if a != b})
        self.assertEqual(self._cluster(), [])

    def test_a_single_fact_is_never_a_cluster(self):
        add(self.conn, "Only one")
        self.assertEqual(self._cluster(), [])

    def test_newest_member_comes_first(self):
        # Merge rule 1 keeps the most recent state of affairs, and _apply_merge
        # inherits scope and validity from cluster[0].
        a, b = "Name is Maga", "Name is Maga Luev"
        add(self.conn, a, updated="2026-01-01T00:00:00Z")
        add(self.conn, b, updated="2026-07-01T00:00:00Z")
        self.q.scores = {(a, b): 0.95}
        clusters = self._cluster()
        self.assertEqual(clusters[0][0]["text"], b)


class TestMergeSchema(unittest.TestCase):
    def test_text_is_nullable_because_declining_is_an_answer(self):
        # Rule 4 of the merge prompt: "Prefers pnpm" and "Prefers pytest" score high
        # because both are about tooling. Merging them would invent a preference.
        schema = providers.merge_schema()
        self.assertIn("null", schema["properties"]["text"]["type"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])

    def test_anthropic_variant_is_strict_and_mirrors_it(self):
        tool = providers.merge_tool()
        self.assertTrue(tool["strict"])
        self.assertEqual(
            set(tool["input_schema"]["properties"]),
            set(providers.merge_schema()["properties"]),
        )

    def test_prompt_keeps_the_do_not_merge_escape(self):
        from memkit import prompts

        rendered = prompts.render_consolidate(
            [{"id": "a", "text": "x", "type": "fact", "importance": 0.5,
              "updated_at": "2026-07-01T00:00:00Z"}]
        )
        self.assertIn("return null", rendered)
        self.assertIn("id=a", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
