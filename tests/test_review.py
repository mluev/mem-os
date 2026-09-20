"""Review: what a person is asked to confirm, and what happens while they wait.

The product decision this file exists to protect is that an unconfirmed fact is
*live*. Extraction writes pending, and pending memories are retrieved, injected
and profiled exactly like confirmed ones. A queue that gated usefulness would
make the system worthless on the day it is installed and would punish anyone
who did not keep up with it; review is a correction channel, not a gate.

The second half is the attention queue, whose only interesting action is
placing a name nobody could resolve. Linking teaches the alias in the same step
as it attributes the fact -- otherwise the same sentence produces the same
question tomorrow.
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from memkit import entities, jobs, judge, retrieval, store
from tests.fixtures import HashEmbedder, SearchableQdrant, apply, make_db, make_session, seed_team
from tests.httpharness import ApiTestCase


class ExtractionWritesPendingTest(unittest.TestCase):
    """The default review status is a claim about the product, not a detail."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        with self.conn.transaction():
            message_id, _, _ = store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.team.scope_of("alice"),
                agent_id="chat",
                role="user",
                content="I prefer pnpm over npm",
            )
        self.message_id = message_id

    def tearDown(self) -> None:
        self.conn.close()

    def _op(self, **changes) -> judge.Op:
        raw = {
            "op": "ADD",
            "text": "Prefers pnpm over npm",
            "kind": "preference",
            "importance": 0.8,
            "confidence": 0.9,
            "evidence": [{"message_id": self.message_id, "start_char": 0, "end_char": 22}],
            "reason": "direct statement",
        }
        raw.update(changes)
        parsed = judge.Op.parse(raw)
        assert parsed is not None
        return parsed

    def _extract(self, *ops: judge.Op, **kw):
        kw.setdefault("source_message_ids", [self.message_id])
        with self.conn.transaction():
            return apply(self.conn, self.team, list(ops), **kw)

    def test_an_extracted_memory_starts_pending(self) -> None:
        self.assertEqual(self._extract(self._op()).added, 1)
        row = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertEqual(row["review_status"], "pending")
        self.assertEqual(row["status"], "active")

    def test_a_pending_memory_is_retrievable(self) -> None:
        """Unconfirmed does not mean invisible. This is the whole design."""
        self._extract(self._op())
        client, embedder = SearchableQdrant(), HashEmbedder()
        from memkit import outbox

        outbox.drain(self.conn, client, embedder, limit=50)
        caller = self.team.principal("alice")
        found, _ = retrieval.search(
            self.conn,
            client,
            embedder,
            query="pnpm",
            scope_ids=caller.scopes(),
            limit=10,
        )
        self.assertEqual([item.review_status for item in found], ["pending"])

    def test_an_unresolvable_name_leaves_the_fact_private_and_flags_it(self) -> None:
        """Attaching the claim to a guessed person is worse than not attaching it."""
        self._extract(self._op(subject_name="Саша"))
        memory = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertIsNone(memory["subject_id"])
        self.assertEqual(str(memory["scope_id"]), self.team.scope_of("alice"))
        item = self.conn.execute("SELECT * FROM needs_attention").fetchone()
        self.assertEqual(item["kind"], "unresolved_mention")
        self.assertEqual(item["payload"]["name"], "Саша")
        self.assertEqual(str(item["ref_memory_id"]), str(memory["id"]))


class ReviewTransitionsTest(ApiTestCase):
    """Confirm, decline, undo -- and what each one does to retrievability."""

    def _pending(self, **kw) -> str:
        """A memory in the shared project scope, which never self-confirms."""
        body = {
            "text": "Deploys go out on Coolify",
            "kind": "decision",
            "source_role": "user",
            "scope": "mem-os",
            **kw,
        }
        response = self.client.post("/v1/memories", json=body, headers=self.auth)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["review_status"], "pending")
        return response.json()["id"]

    def _row(self, memory_id: str):
        return self.sql("SELECT * FROM memories WHERE id=%s", memory_id)[0]

    def _review(self, memory_id: str, decision: str, **body):
        return self.client.post(
            f"/v1/memories/{memory_id}/review",
            json={"decision": decision, **body},
            headers=self.auth,
        )

    def test_a_users_own_manual_save_is_confirmed_on_arrival(self) -> None:
        """They just said it; asking them to confirm it again is noise."""
        memory_id = self.seed_memory()
        self.assertEqual(self._row(memory_id)["review_status"], "confirmed")

    def test_a_write_into_a_shared_scope_starts_pending(self) -> None:
        self.assertEqual(self._row(self._pending())["review_status"], "pending")

    def test_confirming_leaves_the_memory_active(self) -> None:
        memory_id = self._pending()
        response = self._review(memory_id, "confirm")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["review_status"], "confirmed")
        self.assertEqual(response.json()["status"], "active")
        row = self._row(memory_id)
        self.assertEqual(str(row["reviewed_by"]), self.team.alice_id)
        self.assertIsNotNone(row["reviewed_at"])

    def test_declining_archives_so_the_decision_actually_takes_effect(self) -> None:
        """A rejected fact that kept being retrieved would make the label a lie."""
        memory_id = self._pending()
        response = self._review(memory_id, "decline")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["review_status"], "declined")
        self.assertEqual(self._row(memory_id)["status"], "archived")
        self.assertIn(memory_id, self.qdrant.deleted)

    def test_undo_puts_a_declined_memory_back(self) -> None:
        """A decline is reversible from the queue, not only from the history."""
        memory_id = self._pending()
        self._review(memory_id, "decline")
        response = self._review(memory_id, "undo")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["review_status"], "pending")
        row = self._row(memory_id)
        self.assertEqual(row["status"], "active")
        self.assertIn(memory_id, self.qdrant.points)

    def test_every_decision_appends_a_revision(self) -> None:
        memory_id = self._pending()
        for decision in ("confirm", "decline", "undo"):
            self._review(memory_id, decision)
        statuses = [
            row["review_status"]
            for row in self.sql(
                "SELECT review_status FROM memory_revisions WHERE memory_id=%s ORDER BY revision",
                memory_id,
            )
        ]
        self.assertEqual(statuses, ["pending", "confirmed", "declined", "pending"])

    def test_a_stale_revision_is_refused(self) -> None:
        """Two reviewers on the same item must not silently overwrite each other."""
        memory_id = self._pending()
        self._review(memory_id, "confirm")
        response = self._review(memory_id, "decline", expected_revision=1)
        self.assertEqual(response.status_code, 409, response.text)

    def test_a_teammate_cannot_review_a_memory_in_a_scope_they_cannot_write(self) -> None:
        memory_id = self.seed_memory()
        response = self.client.post(
            f"/v1/memories/{memory_id}/review",
            json={"decision": "confirm"},
            headers=self.as_bob,
        )
        self.assertEqual(response.status_code, 404, response.text)


class ReviewQueueTest(ApiTestCase):
    """One queue, four sources, because they all ask the same question."""

    def setUp(self) -> None:
        super().setUp()
        # The seeded Team carries the seeder's closed connection; the queue
        # tests need the live request-path pool instead.
        self.team = replace(self.team, conn=self.db)

    def _queue(self, **params):
        response = self.client.get("/v1/review", params=params, headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def _pending_memory(self) -> str:
        response = self.client.post(
            "/v1/memories",
            json={
                "text": "Deploys go out on Coolify",
                "kind": "decision",
                "source_role": "user",
                "scope": "mem-os",
            },
            headers=self.auth,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _unresolved_mention(self) -> tuple[str, str]:
        """Produce a real mention through extraction, not a hand-written row."""
        message_id = self.seed_message(content="Саша is on holiday until March")
        op = judge.Op.parse(
            {
                "op": "ADD",
                "text": "Саша is on holiday until March",
                "kind": "fact",
                "importance": 0.6,
                "confidence": 0.9,
                "subject_name": "Саша",
                "evidence": [{"message_id": message_id, "start_char": 0, "end_char": 30}],
                "reason": "direct statement",
            }
        )
        assert op is not None
        conn = self.db
        with conn.transaction():
            apply(conn, self.team, [op], source_message_ids=[message_id])
        row = conn.execute("SELECT * FROM needs_attention").fetchone()
        return str(row["id"]), str(row["ref_memory_id"])

    def test_a_pending_memory_appears_with_the_two_decisions_it_offers(self) -> None:
        memory_id = self._pending_memory()
        item = next(item for item in self._queue() if item["kind"] == "memory")
        self.assertEqual(item["id"], memory_id)
        self.assertEqual(item["actions"], ["confirm", "decline"])
        self.assertEqual(item["author"], "alice")

    def test_a_confirmed_memory_leaves_the_queue(self) -> None:
        memory_id = self._pending_memory()
        self.client.post(
            f"/v1/memories/{memory_id}/review", json={"decision": "confirm"}, headers=self.auth
        )
        self.assertEqual([item for item in self._queue() if item["kind"] == "memory"], [])

    def test_an_extractor_rewrite_returns_a_confirmed_fact_with_its_old_wording(self) -> None:
        """The reviewer is deciding on a change, so they need what it replaced.

        Only the extractor sends a confirmed fact back for review; a person
        editing one is already the reviewer.
        """
        memory_id = self.seed_memory(text="Deploys go out on Fly.io", kind="decision")
        message_id = self.seed_message(content="we moved deploys to Coolify")
        op = judge.Op.parse(
            {
                "op": "UPDATE",
                "id": memory_id,
                "text": "Deploys go out on Coolify",
                "kind": "decision",
                "importance": 0.7,
                "confidence": 0.9,
                "evidence": [{"message_id": message_id, "start_char": 0, "end_char": 27}],
                "reason": "the user stated the change",
            }
        )
        assert op is not None
        conn = self.db
        with conn.transaction():
            outcome = apply(conn, self.team, [op], source_message_ids=[message_id])
        self.assertEqual(outcome.updated, 1)
        item = next(item for item in self._queue() if item["id"] == memory_id)
        self.assertEqual(item["title"], "Deploys go out on Coolify")
        self.assertEqual(item["previous_text"], "Deploys go out on Fly.io")

    def test_an_unresolved_mention_appears_with_the_name_that_did_not_resolve(self) -> None:
        item_id, _ = self._unresolved_mention()
        item = next(item for item in self._queue() if item["kind"] == "unresolved_mention")
        self.assertEqual(item["id"], item_id)
        self.assertEqual(item["title"], "Саша")
        self.assertEqual(item["actions"], ["link_entity", "dismiss"])

    def test_a_recent_failed_job_appears(self) -> None:
        conn = self.db
        job_id = jobs.create(conn, kind="extraction", user_id=self.team.alice_id)
        claimed = jobs.claim(conn, job_id)
        jobs.finish(
            conn,
            job_id,
            holder=claimed["holder"],
            status="failed",
            error="provider timed out",
            error_code="timeout",
        )
        item = next(item for item in self._queue() if item["kind"] == "failed_job")
        self.assertEqual(item["id"], job_id)
        self.assertEqual(item["error_code"], "timeout")
        self.assertEqual(item["detail"], "provider timed out")

    def test_spend_near_the_monthly_limit_raises_a_warning(self) -> None:
        """Budget belongs in the same queue: it is one more thing to decide."""
        conn = self.db
        with conn.transaction():
            conn.execute(
                """INSERT INTO judge_runs (user_id,kind,model,prompt_version,input,cost_usd)
                   VALUES (%s,'extract',%s,%s,'{}'::jsonb,0.95)""",
                (self.team.alice_id, judge.DEFAULT_MODEL, judge.PROMPT_VERSION),
            )
        item = next(item for item in self._queue() if item["kind"] == "budget")
        self.assertIn("95%", item["title"])

    def test_the_queue_can_be_narrowed_to_one_kind(self) -> None:
        self._pending_memory()
        self._unresolved_mention()
        kinds = {item["kind"] for item in self._queue(kind="memory")}
        self.assertEqual(kinds, {"memory"})

    def test_another_users_pending_memory_is_not_in_this_queue(self) -> None:
        self.client.post(
            "/v1/memories",
            json={"text": "Bob's own note", "kind": "fact", "source_role": "assistant"},
            headers=self.as_bob,
        )
        texts = [item.get("title") for item in self._queue()]
        self.assertNotIn("Bob's own note", texts)


class AttentionResolutionTest(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.team = replace(self.team, conn=self.db)
        message_id = self.seed_message(content="Саша is on holiday until March")
        op = judge.Op.parse(
            {
                "op": "ADD",
                "text": "Саша is on holiday until March",
                "kind": "fact",
                "importance": 0.6,
                "confidence": 0.9,
                "subject_name": "Саша",
                "evidence": [{"message_id": message_id, "start_char": 0, "end_char": 30}],
                "reason": "direct statement",
            }
        )
        assert op is not None
        conn = self.db
        with conn.transaction():
            apply(conn, self.team, [op], source_message_ids=[message_id])
        row = conn.execute("SELECT * FROM needs_attention").fetchone()
        self.item_id = str(row["id"])
        self.memory_id = str(row["ref_memory_id"])
        self.bob_slug = str(entities.own_entity(conn, self.team.bob_id)["slug"])

    def _resolve(self, **body):
        return self.client.post(
            f"/v1/attention/{self.item_id}/resolve", json=body, headers=self.auth
        )

    def test_linking_attributes_the_fact_to_the_person(self) -> None:
        response = self._resolve(action="link_entity", entity=self.bob_slug)
        self.assertEqual(response.status_code, 200, response.text)
        row = self.sql("SELECT * FROM memories WHERE id=%s", self.memory_id)[0]
        bob_entity = entities.own_entity(self.db, self.team.bob_id)
        self.assertEqual(str(row["subject_id"]), str(bob_entity["id"]))

    def test_linking_moves_the_fact_where_the_team_can_see_it(self) -> None:
        """This is what routing would have done had the name resolved in time."""
        self._resolve(action="link_entity", entity=self.bob_slug)
        row = self.sql("SELECT * FROM memories WHERE id=%s", self.memory_id)[0]
        self.assertEqual(str(row["scope_id"]), self.team.team_id)

    def test_linking_teaches_the_alias_so_the_question_is_asked_once(self) -> None:
        response = self._resolve(action="link_entity", entity=self.bob_slug)
        self.assertEqual(response.json()["alias_taught"], "Саша")
        resolved = entities.resolve_alias(self.db, "саша")
        self.assertEqual(str(resolved["user_id"]), self.team.bob_id)

    def test_resolving_closes_the_item(self) -> None:
        self._resolve(action="link_entity", entity=self.bob_slug)
        row = self.sql("SELECT * FROM needs_attention WHERE id=%s", self.item_id)[0]
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(str(row["resolved_by"]), self.team.alice_id)
        self.assertEqual(self._resolve(action="dismiss").status_code, 404)

    def test_dismissing_closes_the_item_without_touching_the_memory(self) -> None:
        response = self._resolve(action="dismiss")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "resolved")
        row = self.sql("SELECT * FROM memories WHERE id=%s", self.memory_id)[0]
        self.assertIsNone(row["subject_id"])
        self.assertEqual(str(row["scope_id"]), self.team.scope_of("alice"))

    def test_linking_to_an_unknown_entity_is_refused(self) -> None:
        self.assertEqual(
            self._resolve(action="link_entity", entity="no-such-entity").status_code, 404
        )

    def test_link_entity_without_an_entity_is_refused(self) -> None:
        self.assertEqual(self._resolve(action="link_entity").status_code, 422)

    def test_another_users_attention_item_is_invisible(self) -> None:
        response = self.client.post(
            f"/v1/attention/{self.item_id}/resolve",
            json={"action": "dismiss"},
            headers=self.as_bob,
        )
        self.assertEqual(response.status_code, 404, response.text)


if __name__ == "__main__":
    unittest.main()
