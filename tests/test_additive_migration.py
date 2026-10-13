"""Upgrade a populated v1 schema without inventing or losing provenance."""

import hashlib

from memkit import db, store
from tests.fixtures import downgrade_to_v2, seed_team


def test_v1_data_and_migration_checksum_survive_upgrade(database_url, clean_database):
    conn = clean_database
    downgrade_to_v2(conn)
    conn.execute("DROP TABLE memory_revision_evidence")
    conn.execute("ALTER TABLE jobs DROP COLUMN available_at")
    conn.execute("DELETE FROM schema_migrations WHERE version=2")
    team = seed_team(conn)
    # This insert models a stored v1 row, before the new write helpers exist.
    memory_id = "00000000-0000-4000-8000-000000000001"
    conn.execute(
        """INSERT INTO memories(id,scope_id,author_id,kind,text,importance,confidence,
             status,valid_from,extraction_version,source_role,content_hash)
           VALUES (%s,%s,%s,'fact','Preserve the original claim',0.6,0.9,
             'active',now(),'manual','manual',%s)""",
        (
            memory_id,
            team.scope_of("alice"),
            team.alice_id,
            store.content_hash("Preserve the original claim"),
        ),
    )
    original = dict(conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone())
    before = conn.execute("SELECT checksum FROM schema_migrations WHERE version=1").fetchone()[
        "checksum"
    ]
    db.init_db(database_url)
    upgraded = dict(conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone())
    assert {key: upgraded[key] for key in original} == original
    # v3 backfills: a row with no evidence was said when it was written, once.
    assert upgraded["document_date"] == original["created_at"]
    assert upgraded["source_count"] == 1
    assert upgraded["event_dates"] == []
    assert before == hashlib.sha256(db.DDL_V1.encode()).hexdigest()
    assert conn.execute("SELECT count(*) AS n FROM memory_revision_evidence").fetchone()["n"] == 0
    db.init_db(database_url)  # Repeated startup is idempotent.
    assert [
        r["version"] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    ] == [1, 2, 3]


def test_v2_evidence_backfills_document_date_and_mentions(database_url, clean_database):
    conn = clean_database
    team = seed_team(conn)
    downgrade_to_v2(conn)
    scope = team.scope_of("alice")
    conn.execute(
        """INSERT INTO sessions(id,user_id,scope_id,agent_id,started_at)
           VALUES ('s1',%s,%s,'test','2025-01-02T00:00:00Z'),
                  ('s2',%s,%s,'test','2025-03-04T00:00:00Z')""",
        (team.alice_id, scope, team.alice_id, scope),
    )
    ids = [
        conn.execute(
            """INSERT INTO messages(session_id,user_id,role,content,created_at)
               VALUES (%s,%s,'user','I prefer tea',%s) RETURNING id""",
            (session, team.alice_id, when),
        ).fetchone()["id"]
        for session, when in (("s1", "2025-01-02T10:00:00Z"), ("s2", "2025-03-04T10:00:00Z"))
    ]
    memory_id = "00000000-0000-4000-8000-000000000002"
    conn.execute(
        """INSERT INTO memories(id,scope_id,author_id,kind,text,importance,confidence,
             status,valid_from,extraction_version,source_role,content_hash)
           VALUES (%s,%s,%s,'preference','Prefers tea',0.6,0.9,
             'active',now(),'v10','user',%s)""",
        (memory_id, scope, team.alice_id, store.content_hash("Prefers tea")),
    )
    for message_id in ids:
        conn.execute(
            """INSERT INTO memory_evidence(memory_id,message_id,start_char,end_char,excerpt_sha256)
               VALUES (%s,%s,2,12,'x')""",
            (memory_id, message_id),
        )
    db.init_db(database_url)
    row = conn.execute(
        "SELECT document_date,source_count FROM memories WHERE id=%s", (memory_id,)
    ).fetchone()
    assert db.iso(row["document_date"]) == "2025-01-02T10:00:00Z"
    assert row["source_count"] == 2
