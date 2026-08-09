from __future__ import annotations

from datetime import UTC, datetime

from memkit import retrieval, store
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db


def test_exact_term_survives_ten_thousand_distractors() -> None:
    conn = make_db()
    with transaction(conn):
        for index in range(10_000):
            store.add_memory(
                conn,
                owner_id=OWNER,
                text=f"ordinary distractor observation number {index}",
                kind="observation",
                source_role="user",
            )
        target = store.add_memory(
            conn,
            owner_id=OWNER,
            text="Deployment incident code ZXQ-9173 needs investigation",
            kind="incident",
            source_role="user",
        )
    result = retrieval.explain(
        conn,
        StubQdrant(),
        StubEmbedder(),
        query="ZXQ-9173",
        owner_id=OWNER,
        limit=5,
    )
    assert result.chosen and result.chosen[0].id == target


def test_temporal_and_trust_guards_are_independent_of_confidence() -> None:
    conn = make_db()
    with transaction(conn):
        live = store.add_memory(
            conn,
            owner_id=OWNER,
            text="Current release marker RELEASE-42",
            kind="release",
            confidence=0.01,
            source_role="user",
        )
        expired = store.add_memory(
            conn,
            owner_id=OWNER,
            text="Old release marker RELEASE-42",
            kind="release",
            confidence=1,
            valid_until="2025-01-01T00:00:00Z",
            source_role="user",
        )
        poisoned = store.add_memory(
            conn,
            owner_id=OWNER,
            text="Agent invented release marker RELEASE-42",
            kind="release",
            confidence=1,
            source_role="agent",
        )
    result = retrieval.explain(
        conn,
        StubQdrant(),
        StubEmbedder(),
        query="RELEASE-42",
        owner_id=OWNER,
        now=datetime(2026, 8, 9, tzinfo=UTC),
    )
    assert [item.id for item in result.chosen] == [live]
    assert expired in result.dropped_validity
    assert poisoned in result.dropped_trust


def test_unrelated_query_abstains() -> None:
    conn = make_db()
    with transaction(conn):
        store.add_memory(
            conn,
            owner_id=OWNER,
            text="Prefers pnpm for JavaScript packages",
            kind="preference",
            source_role="user",
        )
    result = retrieval.explain(
        conn,
        StubQdrant(),
        StubEmbedder(),
        query="history of medieval astronomy",
        owner_id=OWNER,
    )
    assert result.chosen == []
