from __future__ import annotations

import sqlite3

import pytest

from memkit import provenance, store
from memkit.db import transaction
from tests.fixtures import OWNER, make_db


@pytest.mark.parametrize("role", provenance.ROLES)
def test_every_source_role_is_explicit_and_orderable(role: str) -> None:
    assert provenance.source_role_for({role}) == role
    assert provenance.weakest({role}) == role


def test_model_only_evidence_cannot_author_a_memory() -> None:
    assert not provenance.may_write(op="ADD", roles={"assistant"})
    assert not provenance.may_write(op="UPDATE", roles={"agent", "assistant"})
    assert provenance.may_write(op="DELETE", roles={"assistant"})


def test_source_role_is_required_and_checked_by_sqlite() -> None:
    conn = make_db()
    with pytest.raises(ValueError), transaction(conn):
        store.add_memory(conn, owner_id=OWNER, text="x", kind="fact", source_role="robot")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO memories
               (id,owner_id,kind,text,importance,confidence,status,valid_from,
                created_at,updated_at,extraction_version,context_json,tags_json)
               VALUES ('x',?,'fact','x',.5,.5,'active','x','x','x','manual','{}','[]')""",
            (OWNER,),
        )
