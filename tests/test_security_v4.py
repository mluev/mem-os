from __future__ import annotations

import json
from unittest.mock import patch

from memkit import judge, platform, providers, store
from memkit.db import transaction
from tests.fixtures import OWNER, make_db

SECRET = "super-secret-token-value"


def test_secrets_are_scrubbed_from_every_authoritative_write() -> None:
    conn = make_db()
    with transaction(conn):
        message_id, _, _ = store.add_message(
            conn,
            session_id="secure",
            owner_id=OWNER,
            agent_id="chat",
            role="user",
            content=f"API_KEY={SECRET}",
            context={"authorization": f"Bearer {SECRET}"},
        )
        memory_id = store.add_memory(
            conn,
            owner_id=OWNER,
            text=f"PASSWORD={SECRET}",
            kind="observation",
            context={"secret": SECRET},
            tags=[f"token={SECRET}"],
        )
        platform.create_namespace(conn, owner_id=OWNER, name="secure")
        platform.create_collection(
            conn,
            owner_id=OWNER,
            namespace="secure",
            name="records",
            schema={"type": "object", "additionalProperties": True},
        )
        record, _ = platform.create_record(
            conn,
            owner_id=OWNER,
            namespace="secure",
            collection_name="records",
            value={"password": f"PASSWORD={SECRET}"},
            metadata={"token": f"token={SECRET}"},
            context={"url": f"postgres://user:{SECRET}@host/db"},
        )
    serialized = json.dumps(
        {
            "message": dict(
                conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            ),
            "memory": dict(
                conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            ),
            "record": record,
        }
    )
    assert SECRET not in serialized


def test_provider_never_receives_a_secret() -> None:
    conn = make_db()
    captured: list[str] = []

    def provider_stub(**kwargs):
        captured.append(kwargs["prompt"])
        return providers.ProviderResult(raw={"operations": []})

    with patch("memkit.providers.call", side_effect=provider_stub):
        result = judge.extract(
            conn,
            window=[{"id": 1, "role": "user", "content": f"API_KEY={SECRET}"}],
            candidates=[],
            monthly_limit_usd=1,
            model=judge.DEFAULT_MODEL,
            context={"authorization": f"Bearer {SECRET}"},
            owner_id=OWNER,
        )
    assert result.error is None
    assert SECRET not in captured[0]
    stored_input = conn.execute(
        "SELECT input_json FROM judge_runs WHERE id=?", (result.judge_run_id,)
    ).fetchone()[0]
    assert SECRET not in stored_input
