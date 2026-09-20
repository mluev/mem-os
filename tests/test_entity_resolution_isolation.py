"""Name resolution obeys the same visibility and alias rights as entity reads."""

import uuid

from psycopg.types.json import Jsonb

from memkit import entities, store
from tests.httpharness import ApiTestCase


class EntityResolutionIsolationTest(ApiTestCase):
    def private_project(self):
        return entities.create(
            self.db,
            kind="project",
            name="Private acquisition",
            slug="private-acquisition",
            description="Confidential acquisition detail",
            created_by=self.team.alice_id,
        )

    def attention(self, name="Unknown acquisition"):
        scope = entities.own_entity(self.db, self.team.bob_id)
        memory_id = store.add_memory(
            self.db,
            scope_id=str(scope["id"]),
            author_id=self.team.bob_id,
            text="A fact about an unresolved organization",
            kind="fact",
        )
        attention_id = str(uuid.uuid4())
        self.db.execute(
            """INSERT INTO needs_attention(id,user_id,scope_id,kind,ref_memory_id,payload)
                 VALUES (%s,%s,%s,'unresolved_mention',%s,%s)""",
            (attention_id, self.team.bob_id, scope["id"], memory_id, Jsonb({"name": name})),
        )
        return attention_id, memory_id

    def test_alias_resolution_does_not_expose_an_inaccessible_project(self):
        target = self.private_project()
        direct = self.client.get(f"/v1/entities/{target['slug']}", headers=self.as_bob)
        self.assertEqual(direct.status_code, 403)
        resolved = self.client.post(
            "/v1/entities/resolve", headers=self.as_bob, json={"name": target["name"]}
        )
        self.assertEqual(resolved.status_code, 403, resolved.text)
        self.assertNotIn(target["description"], resolved.text)

    def test_attention_cannot_link_or_teach_an_inaccessible_project_alias(self):
        target = self.private_project()
        attention_id, memory_id = self.attention()
        response = self.client.post(
            f"/v1/attention/{attention_id}/resolve",
            headers=self.as_bob,
            json={"action": "link_entity", "entity": target["slug"]},
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertNotIn("Unknown acquisition", entities.aliases_of(self.db, str(target["id"])))
        self.assertIsNone(self.scalar("SELECT subject_id FROM memories WHERE id=%s", memory_id))
        self.assertEqual(
            self.scalar("SELECT status FROM needs_attention WHERE id=%s", attention_id), "open"
        )

    def test_visible_readonly_entity_can_be_linked_without_teaching_a_global_alias(self):
        target = self.private_project()
        entities.set_member(
            self.db, entity_id=str(target["id"]), user_id=self.team.bob_id, role="viewer"
        )
        attention_id, memory_id = self.attention()
        response = self.client.post(
            f"/v1/attention/{attention_id}/resolve",
            headers=self.as_bob,
            json={"action": "link_entity", "entity": target["slug"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn("alias_taught", response.json())
        self.assertNotIn("Unknown acquisition", entities.aliases_of(self.db, str(target["id"])))
        self.assertEqual(
            str(self.scalar("SELECT subject_id FROM memories WHERE id=%s", memory_id)),
            str(target["id"]),
        )
