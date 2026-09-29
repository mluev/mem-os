"""Time, supersession, links and reinforcement on the extraction path.

Prompt v11 lets the extractor say *when* something happened, whether an UPDATE
corrects a wrong claim or records that a true one stopped being true, and which
existing memory a new one adds detail to. These tests drive `run_extraction`
with a fake provider and read the rows back, because the guarantees live in the
database: an edge never crosses a scope, the past stays queryable with the date
it ended, and a repeated mention is counted once per session.
"""

from __future__ import annotations

from memkit import db, extract, providers, store
from tests.fixtures import add_messages, make_session
from tests.test_extraction_pipeline import MODEL, PipelineCase, _add


def _result(operations):
    return providers.ProviderResult(operations=operations, raw={"operations": operations})


def _said(conn, message_ids, when: str) -> None:
    with conn.transaction():
        conn.execute(
            "UPDATE messages SET created_at=%s WHERE id = ANY(%s)", (when, list(message_ids))
        )


class GraphExtractionTest(PipelineCase):
    def memory(self, text: str):
        return self.conn.execute("SELECT * FROM memories WHERE text=%s", (text,)).fetchone()

    def seed_memory(self, text: str, *, kind: str = "fact", events=None) -> str:
        ids = add_messages(self.conn, n=1, content=text, session="s-seed")
        _said(self.conn, ids, "2026-01-05T09:00:00Z")
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.team.scope_of("alice"),
                author_id=self.team.alice_id,
                text=text,
                kind=kind,
                source_role="user",
                document_date="2026-01-05T09:00:00Z",
                event_dates=events,
            )
        return memory_id

    def setUp(self) -> None:
        super().setUp()
        make_session(self.conn, self.team, session_id="s-seed")

    def test_an_episode_keeps_when_it_happened_and_when_it_was_said(self) -> None:
        ids = add_messages(self.conn, n=10, content="Last Saturday I ran the Lisbon half marathon")
        _said(self.conn, ids, "2026-03-18T12:00:00Z")
        op = _add(
            "The user ran the Lisbon half marathon on 2026-03-14",
            message_id=ids[0],
            quote="I ran the Lisbon half marathon",
        )
        op.update(kind="episode", event_dates=["2026-03-14", "not a date"])
        outcome = self.run_extraction(lambda **_: _result([op]), force=True)

        self.assertEqual(outcome.added, 1, outcome.as_dict())
        row = self.memory("The user ran the Lisbon half marathon on 2026-03-14")
        self.assertEqual(row["kind"], "episode")
        self.assertEqual(row["event_dates"], ["2026-03-14"])
        self.assertEqual(db.iso(row["event_start"]), "2026-03-14T00:00:00Z")
        self.assertEqual(db.iso(row["event_end"]), "2026-03-14T23:59:59Z")
        # Said on the 18th, written today: the document date is the former.
        self.assertEqual(db.iso(row["document_date"]), "2026-03-18T12:00:00Z")
        self.assertEqual(row["extraction_version"], "v11")

    def test_a_state_change_supersedes_and_keeps_the_past_as_dated_history(self) -> None:
        old = self.seed_memory("The user lives in Porto")
        ids = add_messages(self.conn, n=10, content="I moved to Lisbon last month")
        _said(self.conn, ids, "2026-04-02T10:00:00Z")
        op = _add("The user lives in Lisbon", message_id=ids[0], quote="I moved to Lisbon")
        op.update(op="UPDATE", id="1", kind="fact", change="supersede")

        outcome = self.run_extraction(lambda **_: _result([op]), force=True)

        self.assertEqual(outcome.superseded, 1, outcome.as_dict())
        new = self.memory("The user lives in Lisbon")
        previous = self.conn.execute("SELECT * FROM memories WHERE id=%s", (old,)).fetchone()
        self.assertEqual(new["status"], "active")
        self.assertEqual(previous["status"], "superseded")
        self.assertEqual(str(previous["superseded_by"]), str(new["id"]))
        # True until the replacement was said -- not until the write.
        self.assertEqual(db.iso(previous["valid_until"]), "2026-04-02T10:00:00Z")
        history = store.history_of(self.conn, str(new["id"]), scope_ids=[self.team.scope_of()])
        self.assertEqual([str(row["id"]) for row in history], [old])
        relation = self.conn.execute("SELECT * FROM memory_relations").fetchone()
        self.assertEqual(
            (str(relation["from_id"]), str(relation["to_id"]), relation["relation"]),
            (str(new["id"]), old, "updates"),
        )

    def test_an_older_window_replayed_late_becomes_history_not_the_truth(self) -> None:
        current = self.seed_memory("The user lives in Lisbon")  # said 2026-01-05
        ids = add_messages(self.conn, n=10, content="I live in Porto these days")
        _said(self.conn, ids, "2025-06-01T10:00:00Z")
        op = _add("The user lives in Porto", message_id=ids[0], quote="I live in Porto")
        op.update(op="UPDATE", id="1", kind="fact", change="supersede")

        outcome = self.run_extraction(lambda **_: _result([op]), force=True)

        self.assertEqual(outcome.superseded, 1, outcome.as_dict())
        porto = self.memory("The user lives in Porto")
        lisbon = self.conn.execute("SELECT * FROM memories WHERE id=%s", (current,)).fetchone()
        self.assertEqual((lisbon["status"], porto["status"]), ("active", "superseded"))
        self.assertEqual(str(porto["superseded_by"]), current)
        self.assertEqual(db.iso(porto["valid_until"]), "2026-01-05T09:00:00Z")

    def test_a_correction_rewrites_in_place_and_keeps_its_event_dates(self) -> None:
        old = self.seed_memory(
            "The user adopted a dog on 2026-02-01", kind="episode", events=["2026-02-01"]
        )
        ids = add_messages(
            self.conn, n=10, content="Actually Max is a beagle, not a dog in general"
        )
        op = _add(
            "The user adopted a beagle named Max on 2026-02-01",
            message_id=ids[0],
            quote="Max is a beagle",
        )
        op.update(op="UPDATE", id="1", kind="episode", change="correction")

        outcome = self.run_extraction(lambda **_: _result([op]), force=True)

        self.assertEqual((outcome.updated, outcome.superseded), (1, 0), outcome.as_dict())
        row = self.conn.execute("SELECT * FROM memories WHERE id=%s", (old,)).fetchone()
        self.assertEqual(row["text"], "The user adopted a beagle named Max on 2026-02-01")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["event_dates"], ["2026-02-01"])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM memory_relations").fetchone())

    def test_an_add_links_to_the_candidate_it_extends(self) -> None:
        base = self.seed_memory("Alex is a PM at Stripe")
        ids = add_messages(self.conn, n=10, content="Alex leads a team of five on payments")
        op = _add("Alex leads a team of five", message_id=ids[0], quote="Alex leads a team of five")
        op.update(kind="fact", extends=1)

        outcome = self.run_extraction(lambda **_: _result([op]), force=True)

        self.assertEqual((outcome.added, outcome.extended), (1, 1), outcome.as_dict())
        new = self.memory("Alex leads a team of five")
        relation = self.conn.execute("SELECT * FROM memory_relations").fetchone()
        self.assertEqual(
            (str(relation["from_id"]), str(relation["to_id"]), relation["relation"]),
            (str(new["id"]), base, "extends"),
        )

    def test_a_fabricated_link_drops_the_link_and_keeps_the_claim(self) -> None:
        ids = add_messages(self.conn, n=10, content="I play the cello on weekends")
        op = _add("The user plays the cello", message_id=ids[0], quote="I play the cello")
        op.update(extends=42)

        outcome = self.run_extraction(lambda **_: _result([op]), force=True)

        self.assertEqual((outcome.added, outcome.dropped_links), (1, 1), outcome.as_dict())
        self.assertIsNone(self.conn.execute("SELECT 1 FROM memory_relations").fetchone())

    def test_the_candidate_block_shows_when_each_claim_was_said(self) -> None:
        self.seed_memory("The user lives in Porto")
        add_messages(self.conn, n=10, content="just chatting")
        seen: dict[str, str] = {}

        def handler(**kwargs):
            seen["prompt"] = kwargs["prompt"]
            return _result([])

        self.run_extraction(handler, force=True)
        self.assertIn("said=2026-01-05", seen["prompt"])
        self.assertIn("event_dates", seen["prompt"])


class StoreGraphTest(PipelineCase):
    def write(self, text: str, *, who: str = "alice", scope: str | None = None) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=scope or self.team.scope_of(who),
                author_id=self.team.alice_id if who == "alice" else self.team.bob_id,
                text=text,
                kind="fact",
            )

    def test_an_edge_never_crosses_a_scope(self) -> None:
        mine = self.write("Alice's private claim")
        theirs = self.write("Bob's private claim", who="bob")
        with self.assertRaises(ValueError), self.conn.transaction():
            store.add_relation(self.conn, from_id=mine, to_id=theirs, relation="extends")

    def test_reading_edges_rechecks_both_ends(self) -> None:
        a = self.write("First claim")
        b = self.write("Second claim")
        with self.conn.transaction():
            store.add_relation(self.conn, from_id=b, to_id=a, relation="extends")
        self.assertEqual(
            len(store.relations_for(self.conn, [a], scope_ids=[self.team.scope_of("alice")])), 1
        )
        self.assertEqual(
            store.relations_for(self.conn, [a], scope_ids=[self.team.scope_of("bob")]), []
        )

    def test_an_export_carries_the_edges_between_exported_memories(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from memkit import privacy

        a = self.write("The user lives in Porto")
        b = self.write("The user lives in Lisbon")
        with self.conn.transaction():
            store.supersede(self.conn, old_id=a, new_id=b, scopes=[self.team.scope_of("alice")])
        with tempfile.TemporaryDirectory() as directory:
            result = privacy.export_user(
                self.conn,
                user_id=self.team.alice_id,
                export_dir=Path(directory),
                private_scope_id=self.team.scope_of("alice"),
            )
            payload = json.loads(Path(result["path"]).read_text())
        self.assertEqual(result["memory_relations"], 1)
        [edge] = payload["memory_relations"]
        self.assertEqual((edge["from_id"], edge["to_id"], edge["relation"]), (b, a, "updates"))

    def test_a_mention_counts_once_per_new_session(self) -> None:
        make_session(self.conn, self.team, session_id="s-2")
        first = add_messages(self.conn, n=1, content="I prefer tea")
        again = add_messages(self.conn, n=1, content="I prefer tea still")
        later = add_messages(self.conn, n=1, content="Tea, as always", session="s-2")
        memory_id = self.write("The user prefers tea")
        with self.conn.transaction():
            extract._link_evidence(
                self.conn,
                memory_id,
                [
                    {
                        "message_id": first[0],
                        "start_char": 0,
                        "end_char": 5,
                        "excerpt_sha256": "x",
                    }
                ],
            )
            self.assertFalse(store.reinforce(self.conn, memory_id=memory_id, message_ids=again))
            self.assertTrue(store.reinforce(self.conn, memory_id=memory_id, message_ids=later))
        row = self.conn.execute(
            "SELECT source_count FROM memories WHERE id=%s", (memory_id,)
        ).fetchone()
        self.assertEqual(row["source_count"], 2)


# The default prompt is the one production renders; see test_judge for the
# registry invariant this depends on.
assert MODEL.startswith("fake-")
