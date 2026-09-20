"""Regression contracts for identity, evidence, ownership, and bounded context."""

from __future__ import annotations

import hashlib
import unittest
from contextlib import closing
from datetime import timedelta
from unittest import mock

from memkit import (
    consolidate,
    context_assembly,
    eligibility,
    extract,
    filters,
    outbox,
    profiles,
    providers,
    retrieval,
    store,
    vectors,
)
from memkit.db import utcnow
from tests.fixtures import StubEmbedder, StubQdrant, add_messages, make_db, make_session, seed_team
from tests.test_extraction_pipeline import PipelineCase, _add, _result


class CoreReadinessTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        make_session(self.conn, self.team)
        self.scope = self.team.scope_of("alice")

    def tearDown(self):
        self.conn.close()

    def add(self, text="Uses pnpm", **kwargs):
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=kwargs.pop("scope_id", self.scope),
                author_id=self.team.alice_id,
                text=text,
                kind=kwargs.pop("kind", "fact"),
                source_role=kwargs.pop("source_role", "user"),
                **kwargs,
            )

    def update(self, memory_id, **kwargs):
        row = self.conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone()
        arguments = dict(
            text=row["text"],
            kind=row["kind"],
            context=row["context"],
            tags=row["tags"],
            importance=row["importance"],
            confidence=row["confidence"],
            valid_until=row["valid_until"],
        )
        arguments.update(kwargs)
        with self.conn.transaction():
            return store.update_memory(
                self.conn,
                memory_id=memory_id,
                scopes=[self.scope],
                expected_revision=row["revision"],
                **arguments,
            )

    def search(self, query="pnpm", **kwargs):
        return retrieval.explain(
            self.conn, StubQdrant(), StubEmbedder(), query=query, scope_ids=[self.scope], **kwargs
        )

    def test_subject_search_returns_matching_fact(self):
        memory_id = self.add(subject_id=self.team.scope_of("bob"))
        result = self.search(
            expression={"field": "subject_id", "op": "eq", "value": self.team.scope_of("bob")}
        )
        self.assertEqual([row.id for row in result.chosen], [memory_id])

    def test_explicit_null_clears_subject_omission_preserves_it(self):
        memory_id = self.add(subject_id=self.team.scope_of("bob"))
        self.assertEqual(str(self.update(memory_id)["subject_id"]), self.team.scope_of("bob"))
        self.assertIsNone(self.update(memory_id, subject_id=None)["subject_id"])

    def test_ineligible_lexical_rows_cannot_exhaust_candidates(self):
        memory_id = self.add(importance=0)
        for _ in range(65):
            self.add("pnpm pnpm pnpm", source_role="assistant")
        self.assertEqual([row.id for row in self.search(limit=1).chosen], [memory_id])

    def test_context_filter_applies_before_lexical_limit(self):
        memory_id = self.add(context={"workspace": "wanted"}, importance=0)
        for _ in range(65):
            self.add("pnpm pnpm pnpm", context={"workspace": "other"})
        result = self.search(
            limit=1, expression={"field": "context.workspace", "op": "eq", "value": "wanted"}
        )
        self.assertEqual([row.id for row in result.chosen], [memory_id])

    def test_profile_team_rules_survive_many_attributed_facts(self):
        rule = self.add("Review every release", scope_id=self.team.team_id, importance=0)
        for i in range(65):
            self.add(
                f"Bob likes tool {i}",
                scope_id=self.team.team_id,
                subject_id=self.team.scope_of("bob"),
                importance=1,
            )
        result = profiles.render(
            self.conn, own_scope_id=self.scope, team_scope_id=self.team.team_id, blocks=["team"]
        )
        self.assertEqual([row["id"] for row in result["blocks"]["team"]], [rule])

    def test_exact_dedup_does_not_collapse_subjects_validity_or_trust(self):
        self.add(subject_id=self.team.scope_of("bob"))
        duplicate = store.find_duplicate(
            self.conn,
            scope_id=self.scope,
            text="Uses pnpm",
            kind="fact",
            subject_id=None,
            source_role="user",
        )
        self.assertIsNone(duplicate)
        self.add("Uses yarn", valid_until=utcnow() - timedelta(days=1))
        self.assertIsNone(
            store.find_duplicate(
                self.conn, scope_id=self.scope, text="Uses yarn", kind="fact", source_role="user"
            )
        )
        self.add("Uses bun", source_role="assistant")
        self.assertIsNone(
            store.find_duplicate(
                self.conn, scope_id=self.scope, text="Uses bun", kind="fact", source_role="user"
            )
        )

    def test_consolidation_keeps_subject_and_expiry_boundaries(self):
        self.add(subject_id=self.team.scope_of("bob"))
        self.add(subject_id=self.scope)
        self.add("Uses yarn", valid_until=utcnow() - timedelta(days=1))
        live = self.add("Uses yarn")
        result = consolidate.run(
            self.conn, scope_ids=[self.scope], stale_days=90, demotion=0.1, dry_run=False
        )
        self.assertEqual(result.superseded, [])
        row = self.conn.execute("SELECT status FROM memories WHERE id=%s", (live,)).fetchone()
        self.assertEqual(row["status"], "active")

    def test_correction_sources_follow_revision_and_metadata_edits_preserve_them(self):
        ids = add_messages(self.conn, n=2, content="Uses npm; now uses pnpm")
        old, new = "Uses npm", "uses pnpm"
        memory_id = self.add(old)

        def cite(message_id, text):
            start = "Uses npm; now uses pnpm".index(text)
            extract._link_evidence(
                self.conn,
                memory_id,
                [
                    dict(
                        message_id=message_id,
                        start_char=start,
                        end_char=start + len(text),
                        excerpt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    )
                ],
            )

        with self.conn.transaction():
            cite(ids[0], old)
        self.update(memory_id, text="Uses pnpm")
        with self.conn.transaction():
            cite(ids[1], new)
        self.update(memory_id, importance=0.8)
        sources = store.evidence_excerpts(self.conn, [memory_id])[memory_id]
        self.assertEqual([row["excerpt"] for row in sources], [new])
        count = self.conn.execute(
            "SELECT count(*) AS n FROM memory_evidence WHERE memory_id=%s", (memory_id,)
        ).fetchone()["n"]
        self.assertEqual(count, 2)

    def test_final_context_budget_counts_raw_and_sources(self):
        memory_id = self.add()
        baseline = self.search()
        raw = [{"message_id": 1, "text": "long source " * 300}]
        sources = {memory_id: [{"message_id": 2, "excerpt": "a source " * 300}]}
        result, returned_raw, returned_sources = context_assembly.pack_context(
            baseline, raw, sources, budget_tokens=20, limit=1
        )
        self.assertLessEqual(result.used_tokens, 20)
        self.assertEqual(len(result.chosen) + len(returned_raw), 1)
        self.assertEqual(returned_sources.get(memory_id, []), [])

    def merge(self, provider, **kwargs):
        with mock.patch.object(providers, "call_merge", side_effect=provider):
            return consolidate.run(
                self.conn,
                scope_ids=[self.scope],
                stale_days=90,
                demotion=0.1,
                dry_run=False,
                embedder=StubEmbedder(),
                consolidate_cosine=0.9,
                merge=True,
                merge_model="gemini-3.5-flash-lite",
                monthly_limit_usd=10,
                **kwargs,
            )

    def test_semantic_merge_never_crosses_provenance(self):
        self.add("Prefers pnpm", source_role="user")
        self.add("Prefers using pnpm", source_role="assistant")
        provider = mock.Mock(return_value=providers.ProviderResult(raw={"text": "Uses pnpm"}))
        outcome = self.merge(provider)
        self.assertEqual(outcome.merged, [])
        provider.assert_not_called()

    def test_semantic_merge_keeps_expiry_and_requires_review(self):
        expiry = utcnow() + timedelta(days=30)
        self.add("Prefers pnpm", valid_until=expiry, review_status="confirmed")
        self.add("Prefers using pnpm", valid_until=expiry, review_status="confirmed")
        outcome = self.merge(lambda **_: providers.ProviderResult(raw={"text": "Uses pnpm"}))
        self.assertEqual(len(outcome.merged), 1)
        survivor = self.conn.execute(
            "SELECT * FROM memories WHERE id=%s", (outcome.merged[0]["survivor"],)
        ).fetchone()
        self.assertEqual(survivor["valid_until"], expiry)
        self.assertEqual(survivor["review_status"], "pending")

    def test_semantic_merge_cannot_supersede_concurrent_correction(self):
        first = self.add("Prefers pnpm")
        second = self.add("Prefers using pnpm")

        def provider(**_):
            self.update(first, text="Now uses yarn")
            return providers.ProviderResult(raw={"text": "Uses pnpm"})

        outcome = self.merge(provider)
        self.assertEqual(outcome.merged, [])
        self.assertEqual(outcome.merge_skipped[0]["reason"], "members_changed")
        rows = self.conn.execute("SELECT id,status FROM memories").fetchall()
        self.assertEqual({str(row["id"]) for row in rows}, {first, second})
        self.assertTrue(all(row["status"] == "active" for row in rows))

    def test_budget_packer_can_skip_large_first_fact_and_fill_with_later_fact(self):
        self.add("pnpm " + "detail " * 280, importance=1)
        wanted = self.add("Uses pnpm", importance=0)
        result = self.search(limit=1, budget_tokens=20)
        self.assertEqual([row.id for row in result.chosen], [wanted])

    def test_reused_citation_can_support_multiple_revisions(self):
        message_id = add_messages(self.conn, n=1, content="Uses npm or pnpm")[0]
        memory_id = self.add("Uses npm")
        evidence = dict(
            message_id=message_id,
            start_char=0,
            end_char=16,
            excerpt_sha256=hashlib.sha256(b"Uses npm or pnpm").hexdigest(),
        )
        with self.conn.transaction():
            extract._link_evidence(self.conn, memory_id, [evidence])
        self.update(memory_id, text="Uses npm or pnpm")
        with self.conn.transaction():
            extract._link_evidence(self.conn, memory_id, [evidence])
        count = self.conn.execute(
            "SELECT count(*) AS n FROM memory_revision_evidence WHERE memory_id=%s", (memory_id,)
        ).fetchone()["n"]
        self.assertEqual(count, 2)

    def test_sql_filters_match_authoritative_json_semantics(self):
        memory_id = self.add(
            context={"nested": {"items": [True], "count": 1, "null": None}}, tags=["alpha", "beta"]
        )
        row = self.conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone()
        expressions = [
            {"field": "context.nested.count", "op": "eq", "value": True},
            {"field": "context.nested.count", "op": "in", "value": [True]},
            {"field": "context.nested.count", "op": "eq", "value": 1.0},
            {"field": "tags", "op": "in", "value": ["beta"]},
            {"field": "tags", "op": "eq", "value": ["alpha", "beta"]},
            {
                "field": "context.nested",
                "op": "eq",
                "value": {"items": [1], "count": 1, "null": None},
            },
            {"field": "context.nested.items", "op": "eq", "value": [1]},
            {"field": "context.nested.items", "op": "exists"},
            {"field": "context.nested.null", "op": "absent"},
            {"field": "unknown", "op": "eq", "value": None},
            {"field": "context.nested.count", "op": "in", "value": [1, 3]},
            {"field": "tags", "op": "in", "value": []},
        ]
        for expression in expressions:
            with self.subTest(expression=expression):
                sql, parameters = eligibility.filter_sql(expression)
                found = self.conn.execute(
                    f"SELECT m.id FROM memories m WHERE {sql}", parameters
                ).fetchall()
                self.assertEqual(
                    bool(found), filters.matches(eligibility.document(row), expression)
                )

    def test_dense_and_raw_filters_work_with_actual_qdrant_payloads(self):
        from qdrant_client import QdrantClient

        with closing(QdrantClient(":memory:")) as client:
            vectors.ensure_collections(client)
            wanted = self.add(
                "Durable package preference",
                context={"project": "wanted"},
                subject_id=self.team.scope_of("bob"),
            )
            for index in range(65):
                self.add(f"Other preference {index}", context={"project": "other"})
            outbox.drain(self.conn, client, StubEmbedder(), limit=100)
            result = retrieval.explain(
                self.conn,
                client,
                StubEmbedder(),
                query="arbitrary query",
                scope_ids=[self.scope],
                limit=1,
                expression={
                    "all": [
                        {"field": "subject_id", "op": "eq", "value": self.team.scope_of("bob")},
                        {"field": "context.project", "op": "eq", "value": "wanted"},
                    ]
                },
            )
            self.assertEqual([row.id for row in result.chosen], [wanted])
            store.add_message(
                self.conn,
                session_id="s-1",
                user_id=self.team.alice_id,
                scope_id=self.scope,
                agent_id="chat",
                role="user",
                content="A retained user message with enough text",
            )
            outbox.drain(self.conn, client, StubEmbedder(), limit=100)
            raw = store.search_raw(
                self.conn,
                client,
                StubEmbedder(),
                query="arbitrary query",
                scope_ids=[self.scope],
                expression={"field": "kind", "op": "eq", "value": "evidence"},
            )
            self.assertEqual(len(raw), 1)


class ExtractionOwnershipTest(PipelineCase):
    def test_lost_message_lease_cannot_apply_facts(self):
        ids = add_messages(self.conn, n=10, content="I always use pnpm, never npm")

        def provider(**_):
            self.conn.execute(
                "UPDATE messages SET claim_token='replacement',claim_expires_at=%s",
                (utcnow() + timedelta(minutes=5),),
            )
            return _result([_add("Prefers pnpm", message_id=ids[0], quote="I always use pnpm")])

        outcome = self.run_extraction(provider, force=True)
        self.assertEqual(outcome.error, "extraction_lease_lost")
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"], 0)
        self.assertEqual(self.unprocessed(), 10)

    def test_expired_unreclaimed_lease_cannot_apply_facts(self):
        ids = add_messages(self.conn, n=10, content="I always use pnpm, never npm")

        def provider(**_):
            self.conn.execute(
                "UPDATE messages SET claim_expires_at=%s", (utcnow() - timedelta(seconds=1),)
            )
            return _result([_add("Prefers pnpm", message_id=ids[0], quote="I always use pnpm")])

        outcome = self.run_extraction(provider, force=True)
        self.assertEqual(outcome.error, "extraction_lease_lost")
        self.assertEqual(self.conn.execute("SELECT count(*) AS n FROM memories").fetchone()["n"], 0)

    def test_assistant_only_completion_is_ownership_fenced(self):
        add_messages(self.conn, n=10, role="assistant")
        original = extract.claim_window

        def stolen(*args, **kwargs):
            rows = original(*args, **kwargs)
            self.conn.execute("UPDATE messages SET claim_token='replacement'")
            return rows

        with mock.patch.object(extract, "claim_window", side_effect=stolen):
            outcome = self.run_extraction(lambda **_: _result(), force=True)
        self.assertEqual(outcome.error, "extraction_lease_lost")
        self.assertEqual(self.unprocessed(), 10)
