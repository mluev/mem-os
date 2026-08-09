from __future__ import annotations

from memkit import providers, retrieval, store
from memkit.db import transaction
from tests.fixtures import OWNER, StubEmbedder, StubQdrant, make_db


def test_custom_judge_provider_is_replaceable() -> None:
    calls: list[str] = []

    def fake(**kwargs):
        calls.append(kwargs["model"])
        return providers.ProviderResult(raw={"operations": []})

    providers.register_provider("test", model_prefix="test-", call=fake)
    result = providers.call(model="test-small", prompt="hello")
    assert result.error is None
    assert calls == ["test-small"]


def test_custom_reranker_is_applied() -> None:
    conn = make_db()
    with transaction(conn):
        first = store.add_memory(
            conn, owner_id=OWNER, text="alpha exact", kind="fact", source_role="user"
        )
        second = store.add_memory(
            conn, owner_id=OWNER, text="alpha second", kind="fact", source_role="user"
        )

    class Reverse:
        def rerank(self, query, candidates):
            return sorted(candidates, key=lambda item: item.id != second)

    result = retrieval.explain(
        conn,
        StubQdrant(),
        StubEmbedder(),
        query="alpha",
        owner_id=OWNER,
        reranker=Reverse(),
    )
    assert {item.id for item in result.chosen} == {first, second}
    assert result.chosen[0].id == second
