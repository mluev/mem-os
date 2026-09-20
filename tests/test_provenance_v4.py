"""Provenance: every stored claim says who said it, and the column cannot lapse.

The loop this closes is a model reading its own assertion back as established
fact. A prompt rule is a request; a NOT NULL column with a CHECK and a predicate
at the write is the guarantee, so both halves are asserted here -- the ordering
functions in Python, and the constraint in Postgres.
"""

from __future__ import annotations

import pytest
from psycopg import errors

from memkit import provenance, store
from tests.fixtures import make_db, seed_team


@pytest.mark.parametrize("role", provenance.ROLES)
def test_every_source_role_is_explicit_and_orderable(role: str) -> None:
    assert provenance.source_role_for({role}) == role
    assert provenance.weakest({role}) == role


def test_model_only_evidence_cannot_author_a_memory() -> None:
    assert not provenance.may_write(op="ADD", roles={"assistant"})
    assert not provenance.may_write(op="UPDATE", roles={"agent", "assistant"})
    assert provenance.may_write(op="DELETE", roles={"assistant"})


def test_source_role_is_required_and_checked_by_postgres() -> None:
    conn = make_db(seed=False)
    team = seed_team(conn)
    with pytest.raises(ValueError), conn.transaction():
        store.add_memory(
            conn,
            scope_id=team.scope_of("alice"),
            author_id=team.alice_id,
            text="x",
            kind="fact",
            source_role="robot",
        )
    with pytest.raises(errors.NotNullViolation), conn.transaction():
        conn.execute(
            """INSERT INTO memories
               (id,scope_id,author_id,kind,text,importance,confidence,status,valid_from,
                extraction_version,content_hash)
               VALUES (gen_random_uuid(),%s,%s,'fact','x',.5,.5,'active',now(),'manual','h')""",
            (team.scope_of("alice"), team.alice_id),
        )
    conn.close()
