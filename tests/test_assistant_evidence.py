"""Assistant info as evidence (decisions/0082): what changes, and what must not.

Prompt v12 lets the assistant's own words support a memory written as
assistant info. Everything around that is about keeping ADR 0006's loop broken:
such a memory is labelled `assistant`, stays pending, ranks below stated claims
until confirmed, never joins a profile or a dream unconfirmed, and its raw
passages reach only a policy that trusts the assistant. The older prompts and
policies must behave exactly as before, which is what the controls check.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from memkit import (
    config,
    dream,
    extract,
    judge,
    outbox,
    profiles,
    reindex,
    retrieval,
    store,
    vectors,
)
from tests.fixtures import (
    HashEmbedder,
    StubEmbedder,
    StubQdrant,
    apply,
    make_db,
    make_session,
    seed_team,
)
from tests.httpharness import ApiTestCase
from tests.test_semantic_candidates import ScoredStub

AS_OF = datetime(2026, 10, 19, 12, tzinfo=UTC)


class AssistantRankingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")
        self.v2 = retrieval.load_policy(self.conn, "core-retrieval-v2")
        self.v3 = retrieval.load_policy(self.conn, "assistant-v3")

    def tearDown(self) -> None:
        self.conn.close()

    def add(self, text: str, source_role: str, **kw) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=self.caller.own_entity_id,
                author_id=self.team.alice_id,
                text=text,
                kind=kw.pop("kind", "fact"),
                source_role=source_role,
                **kw,
            )

    def search(self, query: str, policy) -> retrieval.Explain:
        return retrieval.explain(
            self.conn,
            StubQdrant(),
            StubEmbedder(),
            query=query,
            scope_ids=self.caller.scopes(),
            policy=policy,
            now=AS_OF,
        )

    def test_v3_extends_v2_by_trusting_the_assistant_and_nothing_else(self) -> None:
        for name in (
            "dense_weight",
            "lexical_weight",
            "entity_weight",
            "min_relevance",
            "temporal_weight",
            "inference_penalty",
        ):
            self.assertEqual(getattr(self.v2, name), getattr(self.v3, name), name)
        self.assertEqual(self.v3.allowed_source_roles - self.v2.allowed_source_roles, {"assistant"})
        self.assertGreater(self.v3.assistant_penalty, 0)
        self.assertEqual(self.v2.assistant_penalty, 0)

    def test_v2_drops_assistant_memories_and_v3_ranks_them_below_stated_ones(self) -> None:
        said = self.add("The assistant recommended Hotel Lisboa Plaza", "assistant")
        stated = self.add("Alice booked Hotel Lisboa Plaza", "user")
        v2 = self.search("Hotel Lisboa Plaza", self.v2)
        self.assertEqual([m.id for m in v2.chosen], [stated])
        v3 = self.search("Hotel Lisboa Plaza", self.v3)
        self.assertEqual([m.id for m in v3.chosen], [stated, said])
        by_id = {m.id: m for m in v3.chosen}
        self.assertEqual(by_id[said].source_role, "assistant")

    def test_a_confirmed_assistant_memory_carries_no_penalty(self) -> None:
        said = self.add("The assistant recommended Hotel Lisboa Plaza", "assistant")
        before = {m.id: m.score for m in self.search("Hotel Lisboa Plaza", self.v3).chosen}
        with self.conn.transaction():
            store.set_review_status(
                self.conn,
                memory_id=said,
                scopes=self.caller.writable_scope_ids,
                review_status="confirmed",
                reviewed_by=self.team.alice_id,
            )
        after = {m.id: m.score for m in self.search("Hotel Lisboa Plaza", self.v3).chosen}
        self.assertAlmostEqual(after[said] - before[said], self.v3.assistant_penalty)

    def test_the_profile_shows_assistant_memories_only_once_confirmed(self) -> None:
        said = self.add("The assistant recommended a 6am run", "assistant", kind="preference")

        def style() -> list[str]:
            rendered = profiles.render(
                self.conn,
                own_scope_id=self.caller.own_entity_id,
                allowed_scope_ids=self.caller.scopes(),
            )
            return [item["id"] for items in rendered["blocks"].values() for item in items]

        self.assertNotIn(said, style())
        with self.conn.transaction():
            store.set_review_status(
                self.conn,
                memory_id=said,
                scopes=self.caller.writable_scope_ids,
                review_status="confirmed",
                reviewed_by=self.team.alice_id,
            )
        self.assertIn(said, style())

    def test_assistant_memories_are_never_dream_premises(self) -> None:
        self.add("The assistant recommended Hotel Lisboa Plaza", "assistant")
        stated = self.add("Alice booked Hotel Lisboa Plaza", "user")
        fresh = dream.fresh_memories(self.conn, self.caller.own_entity_id, since=None)
        self.assertEqual([str(row["id"]) for row in fresh], [stated])
        self.assertNotIn("assistant", dream.PREMISE_ROLES)


class AssistantWritePathTest(unittest.TestCase):
    """What apply_ops writes from assistant spans, by prompt version."""

    QUESTION = "Which hotel in Lisbon do you suggest for March?"
    ANSWER = "I suggest Hotel Lisboa Plaza near Avenida da Liberdade."

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        self.scope = self.team.scope_of("alice")
        self.asked = self.message("user", self.QUESTION)
        self.answered = self.message("assistant", self.ANSWER)

    def tearDown(self) -> None:
        self.conn.close()

    def message(self, role: str, content: str) -> int:
        with self.conn.transaction():
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.scope,
                agent_id="chat",
                role=role,
                content=content,
            )
        return message_id

    def cite(self, message_id: int, quote: str) -> dict:
        return {"message_id": message_id, "start_char": 0, "end_char": 0, "quote": quote}

    def op(self, *citations: dict, **changes) -> judge.Op:
        raw = {
            "op": "ADD",
            "text": "The assistant recommended Hotel Lisboa Plaza for the user's March trip",
            "kind": "fact",
            "reason": "assistant info",
            "evidence": list(citations) or [self.cite(self.answered, "Hotel Lisboa Plaza")],
            **changes,
        }
        parsed = judge.Op.parse(raw)
        assert parsed is not None
        return parsed

    def run_ops(self, *ops: judge.Op, version: str, **kw):
        with self.conn.transaction():
            return apply(
                self.conn,
                self.team,
                list(ops),
                source_message_ids=[self.asked, self.answered],
                extraction_version=version,
                **kw,
            )

    def stated(self, text: str = "Alice is staying at Hotel Lisboa Plaza") -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=self.scope,
                author_id=self.team.alice_id,
                text=text,
                kind="fact",
                source_role="user",
            )

    def test_older_prompts_still_refuse_assistant_only_evidence(self) -> None:
        for version in ("v10", "v11"):
            outcome = self.run_ops(self.op(), version=version)
            self.assertEqual(outcome.added, 0, version)
            self.assertEqual([r["reason"] for r in outcome.rejections], ["assistant_only_source"])
        self.assertIsNone(self.conn.execute("SELECT id FROM memories").fetchone())

    def test_v12_writes_assistant_info_labelled_and_pending(self) -> None:
        outcome = self.run_ops(self.op(), version="v12")
        self.assertEqual((outcome.added, outcome.assistant_sourced), (1, 1))
        row = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertEqual((row["source_role"], row["review_status"]), ("assistant", "pending"))
        self.assertEqual(row["extraction_version"], "v12")

    def test_a_mixed_citation_is_assistant_under_v12_and_user_before(self) -> None:
        mixed = (self.cite(self.asked, "Which hotel"), self.cite(self.answered, "Lisboa Plaza"))
        self.run_ops(self.op(*mixed), version="v11")
        self.assertEqual(
            self.conn.execute("SELECT source_role FROM memories").fetchone()[0], "user"
        )
        with self.conn.transaction():
            self.conn.execute("DELETE FROM memories")
        outcome = self.run_ops(self.op(*mixed), version="v12")
        self.assertEqual((outcome.assistant_sourced, outcome.assistant_mixed), (1, 1))
        self.assertEqual(
            self.conn.execute("SELECT source_role FROM memories").fetchone()[0], "assistant"
        )

    def test_the_assistant_cannot_revise_what_a_person_stated(self) -> None:
        target = self.stated()
        update = self.op(op="UPDATE", id=target, change="correction")
        delete = self.op(op="DELETE", id=target)
        outcome = self.run_ops(update, delete, version="v12")
        self.assertEqual(
            [r["reason"] for r in outcome.rejections],
            ["assistant_cannot_revise_stated", "assistant_cannot_revise_stated"],
        )
        row = self.conn.execute(
            "SELECT status,revision FROM memories WHERE id=%s", (target,)
        ).fetchone()
        self.assertEqual((row["status"], row["revision"]), ("active", 1))

    def test_the_assistant_may_revise_its_own_assistant_info(self) -> None:
        self.run_ops(self.op(), version="v12")
        own = str(self.conn.execute("SELECT id FROM memories").fetchone()[0])
        outcome = self.run_ops(
            self.op(
                op="UPDATE",
                id=own,
                change="correction",
                text="The assistant recommended Hotel Lisboa Plaza near Avenida da Liberdade",
            ),
            version="v12",
        )
        self.assertEqual((outcome.updated, outcome.rejected), (1, 0))

    def test_an_assistant_restatement_links_evidence_without_another_mention(self) -> None:
        target = self.stated("The assistant recommended Hotel Lisboa Plaza")
        op = self.op(text="The assistant recommended Hotel Lisboa Plaza")
        index = ScoredStub()
        outbox.drain(self.conn, index, HashEmbedder())
        planned = extract.plan_dedup(
            self.conn,
            ops=[op],
            scope_id=self.scope,
            client=index,
            embedder=HashEmbedder(),
            threshold=0.9,
            subjects={0: None},
            source_roles={0: "assistant"},
        )
        self.assertEqual(planned[0], extract.DedupTarget(target, 1, reinforce=False))
        outcome = self.run_ops(op, version="v12", dedup_hits=planned)
        self.assertEqual((outcome.added, outcome.deduplicated, outcome.reinforced), (0, 1, 0))
        row = self.conn.execute("SELECT source_count FROM memories WHERE id=%s", (target,))
        self.assertEqual(row.fetchone()[0], 1)
        linked = self.conn.execute(
            "SELECT 1 FROM memory_evidence WHERE memory_id=%s AND message_id=%s",
            (target, self.answered),
        ).fetchone()
        self.assertIsNotNone(linked)

    def test_a_recount_never_raises_an_assistant_memory_above_one(self) -> None:
        self.run_ops(self.op(), version="v12")
        memory_id = str(self.conn.execute("SELECT id FROM memories").fetchone()[0])
        make_session(self.conn, self.team, session_id="s-2")
        again = None
        with self.conn.transaction():
            again, _, _ = store.add_message(
                self.conn,
                session_id="s-2",
                user_id=self.team.alice_id,
                scope_id=self.scope,
                agent_id="chat",
                role="assistant",
                content=self.ANSWER,
            )
            self.conn.execute(
                """INSERT INTO memory_evidence (memory_id,message_id,start_char,end_char,
                   excerpt_sha256) VALUES (%s,%s,0,5,'x')""",
                (memory_id, again),
            )
            self.assertEqual(store.recount_mentions(self.conn, memory_id=memory_id), 1)


class AssistantRawIndexTest(ApiTestCase):
    def raw_hits(self, ids: list[int]) -> None:
        # The index ignores role filters here on purpose: Postgres must enforce them.
        def query(collection_name, **kwargs):
            return SimpleNamespace(
                points=[SimpleNamespace(id=mid, score=0.9, payload={}) for mid in ids]
                if collection_name == vectors.RAW
                else []
            )

        self.qdrant.query_points = query

    def opted_in(self):
        settings = config.get_settings().model_copy(update={"index_assistant_turns": True})
        return patch.object(config, "_settings", settings)

    def queued(self, message_id: int) -> int:
        return self.scalar(
            "SELECT COUNT(*) FROM index_outbox WHERE collection='raw' AND entity_id=%s",
            str(message_id),
        )

    def test_assistant_turns_are_raw_indexed_only_when_the_instance_opts_in(self) -> None:
        answer = "Try Hotel Lisboa Plaza near Avenida, about 180 euros a night"
        default = self.client.post(
            "/v1/evidence/events",
            headers=self.auth,
            json={"session_id": "trip", "role": "assistant", "content": answer},
        ).json()
        self.assertEqual(default["index_status"], "not_applicable")
        self.assertEqual(self.queued(default["message_id"]), 0)
        with self.opted_in():
            opted = self.client.post(
                "/v1/evidence/events:batch",
                headers=self.auth,
                json={
                    "events": [
                        {"session_id": "trip", "role": "assistant", "content": answer + "!"},
                        {"session_id": "trip", "role": "tool", "content": answer + "?"},
                    ]
                },
            ).json()["items"]
        self.assertNotEqual(opted[0]["index_status"], "not_applicable")
        self.assertEqual(self.queued(opted[0]["message_id"]), 1)
        # Tool output is never indexed, whatever the setting.
        self.assertEqual(opted[1]["index_status"], "not_applicable")
        self.assertEqual(self.queued(opted[1]["message_id"]), 0)

    def test_raw_assistant_passages_reach_only_a_policy_that_trusts_the_assistant(self) -> None:
        asked = self.seed_message(
            session_id="trip", content="Which hotel in Lisbon did you suggest?"
        )
        with self.opted_in():
            answered = self.seed_message(
                session_id="trip",
                role="assistant",
                content="I suggested Hotel Lisboa Plaza near Avenida da Liberdade",
            )
        self.raw_hits([asked, answered])

        def raw(policy: str) -> list[tuple[int, str]]:
            response = self.client.post(
                "/v1/memories/search",
                headers=self.auth,
                json={"query": "Lisbon hotel", "include_raw": True, "policy_id": policy},
            )
            self.assertEqual(response.status_code, 200, response.text)
            return [(r["message_id"], r["source_role"]) for r in response.json()["raw"]]

        self.assertEqual(raw("neutral-v1"), [(asked, "user")])
        self.assertEqual(raw("core-retrieval-v2"), [(asked, "user")])
        self.assertEqual(sorted(raw("assistant-v3")), [(asked, "user"), (answered, "assistant")])

    def test_a_rebuild_indexes_the_same_roles_ingestion_does(self) -> None:
        asked = self.seed_message(
            session_id="trip", content="Which hotel in Lisbon did you suggest?"
        )
        answered = self.seed_message(
            session_id="trip", role="assistant", content="I suggested Hotel Lisboa Plaza"
        )

        def snapshot(roles) -> set[int]:
            _, _, raw_rows = reindex._snapshot(self.db, roles)
            return {int(row["id"]) for row in raw_rows}

        self.assertEqual(snapshot(store.USER_ONLY), {asked})
        self.assertEqual(snapshot(store.WITH_ASSISTANT), {asked, answered})


if __name__ == "__main__":
    unittest.main()
