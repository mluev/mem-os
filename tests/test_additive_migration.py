"""Upgrade a populated v1 schema without inventing or losing provenance."""

import hashlib

from memkit import db, store
from tests.fixtures import seed_team


def test_v1_data_and_migration_checksum_survive_upgrade(database_url, clean_database):
    conn = clean_database
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
    assert (
        dict(conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone())
        == original
    )
    assert before == hashlib.sha256(db.DDL_V1.encode()).hexdigest()
    assert conn.execute("SELECT count(*) AS n FROM memory_revision_evidence").fetchone()["n"] == 0
    db.init_db(database_url)  # Repeated startup is idempotent.
    assert [
        r["version"] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    ] == [1, 2]
