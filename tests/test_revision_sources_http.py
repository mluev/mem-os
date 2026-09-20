"""A correction cannot cite its predecessor's evidence as current support."""

import hashlib

from tests.httpharness import ApiTestCase


class RevisionSourcesHttpTest(ApiTestCase):
    def check_correction(self, *, versioned):
        text = "I prefer pnpm for all projects"
        message_id = self.seed_message(content=text)
        memory_id = self.seed_memory(text=text)
        self.db.execute(
            """INSERT INTO memory_evidence
                 (memory_id,message_id,start_char,end_char,excerpt_sha256)
               VALUES (%s,%s,0,%s,%s)""",
            (memory_id, message_id, len(text), hashlib.sha256(text.encode()).hexdigest()),
        )
        if versioned:
            self.db.execute(
                """INSERT INTO memory_revision_evidence
                     (memory_id,revision,message_id,start_char,end_char)
                   VALUES (%s,1,%s,0,%s)""",
                (memory_id, message_id, len(text)),
            )
        original = self.client.get(f"/v1/memories/{memory_id}/sources", headers=self.auth)
        self.assertEqual(original.status_code, 200)
        self.assertEqual(len(original.json()["evidence"]), 1)
        corrected = self.client.patch(
            f"/v1/memories/{memory_id}",
            headers=self.auth,
            json={"expected_revision": 1, "text": "I now prefer npm for all projects"},
        )
        self.assertEqual(corrected.status_code, 200, corrected.text)
        response = self.client.get(f"/v1/memories/{memory_id}/sources", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["evidence"], [])
        historical = response.json()["historical_evidence"]
        self.assertEqual(historical[0]["excerpt"], text)
        self.assertEqual(historical[0]["supported_revisions"], [1] if versioned else [])
        self.assertEqual(
            historical[0]["evidence_status"], "historical" if versioned else "legacy_unversioned"
        )
        forbidden = self.client.get(f"/v1/memories/{memory_id}/sources", headers=self.as_bob)
        self.assertEqual(forbidden.status_code, 404)

    def test_versioned_evidence_remains_with_its_revision(self):
        self.check_correction(versioned=True)

    def test_legacy_evidence_is_not_assigned_to_a_corrected_claim(self):
        self.check_correction(versioned=False)
