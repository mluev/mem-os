"""Owned review items cannot expose another scope's current content or spend."""

import uuid

from psycopg.types.json import Jsonb

from memkit import entities, store
from tests.fixtures import make_judge_run
from tests.httpharness import ApiTestCase


class ReviewIsolationTest(ApiTestCase):
    def test_owned_attention_survives_revocation_without_inaccessible_memory_text(self):
        own = entities.own_entity(self.db, self.team.bob_id)
        memory_id = store.add_memory(
            self.db,
            scope_id=str(own["id"]),
            author_id=self.team.bob_id,
            text="Original statement about an unresolved person",
            kind="fact",
        )
        attention_id = str(uuid.uuid4())
        self.db.execute(
            """INSERT INTO needs_attention(id,user_id,scope_id,kind,ref_memory_id,payload)
                 VALUES (%s,%s,%s,'unresolved_mention',%s,%s)""",
            (
                attention_id,
                self.team.bob_id,
                own["id"],
                memory_id,
                Jsonb({"name": "Unresolved person"}),
            ),
        )
        moved = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.as_bob,
            json={"expected_revision": 1, "scope": self.team.project_id, "move_scope": True},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        entities.remove_member(self.db, entity_id=self.team.project_id, user_id=self.team.bob_id)
        changed = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 2, "text": "Confidential project change after removal"},
        )
        self.assertEqual(changed.status_code, 200, changed.text)
        response = self.client.get("/v1/review?kind=unresolved_mention", headers=self.as_bob)
        self.assertEqual(response.status_code, 200, response.text)
        item = next(row for row in response.json()["items"] if row["id"] == attention_id)
        self.assertEqual(item["title"], "Unresolved person")
        self.assertIsNone(item["detail"])
        self.assertNotIn("Confidential project change", response.text)
        self.assertEqual(
            self.scalar("SELECT status FROM needs_attention WHERE id=%s", attention_id), "open"
        )

    def test_instance_budget_warning_is_administrator_only(self):
        make_judge_run(self.db, cost=0.9, user_id=self.team.alice_id)
        nonadmin = self.client.get("/v1/review?kind=budget", headers=self.as_bob)
        self.assertEqual(nonadmin.status_code, 200, nonadmin.text)
        self.assertEqual(nonadmin.json()["items"], [])
        admin = self.client.get("/v1/review?kind=budget", headers=self.auth)
        self.assertEqual(admin.status_code, 200, admin.text)
        self.assertEqual([item["kind"] for item in admin.json()["items"]], ["budget"])
