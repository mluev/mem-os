"""Retrieval policy v2: time, order, decay, reinforcement and inference.

Each signal is tested against the v1 policy as a control, because v2's claim is
additive: with the same store, v1 must rank exactly as before and v2 must move
only what its signal is about. The stub index returns no dense hits, so these
tests rank through the lexical arm, which is enough to hold relevance equal
while one signal varies.
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from memkit import api, config, graph, retrieval, store
from tests.fixtures import StubEmbedder, StubQdrant, make_db, seed_team
from tests.httpharness import ApiTestCase

AS_OF = datetime(2026, 9, 29, 12, tzinfo=UTC)


class PolicyV2RankingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")
        self.v1 = retrieval.load_policy(self.conn, "neutral-v1")
        self.v2 = retrieval.load_policy(self.conn, "core-retrieval-v2")

    def tearDown(self) -> None:
        self.conn.close()

    def add(self, text: str, **kw) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=self.caller.own_entity_id,
                author_id=self.team.alice_id,
                text=text,
                kind=kw.pop("kind", "episode"),
                source_role=kw.pop("source_role", "user"),
                **kw,
            )

    def search(self, query: str, policy, **kw) -> list[retrieval.Scored]:
        return retrieval.explain(
            self.conn,
            StubQdrant(),
            StubEmbedder(),
            query=query,
            scope_ids=self.caller.scopes(),
            policy=policy,
            now=AS_OF,
            **kw,
        ).chosen

    def test_the_seeded_v2_policy_extends_v1_without_retuning_it(self) -> None:
        for name in ("dense_weight", "lexical_weight", "entity_weight", "min_relevance"):
            self.assertEqual(getattr(self.v1, name), getattr(self.v2, name), name)
        self.assertIn("inference", self.v2.allowed_source_roles)
        self.assertNotIn("inference", self.v1.allowed_source_roles)
        self.assertEqual(self.v1.temporal_weight, 0.0)

    def test_a_named_window_boosts_what_happened_inside_it(self) -> None:
        march = self.add("The user went hiking in Sintra", event_dates=["2026-03-10"])
        august = self.add("The user went hiking in Arrabida", event_dates=["2026-08-15"])
        ranked = self.search("hiking last month", self.v2)
        self.assertEqual(ranked[0].id, august)
        self.assertGreater(ranked[0].temporal, 0)
        self.assertEqual(next(r for r in ranked if r.id == march).temporal, 0)
        control = self.search("hiking last month", self.v1)
        self.assertTrue(all(item.temporal == 0 for item in control))

    def test_the_window_resolves_against_the_question_date(self) -> None:
        early = self.add("The user went hiking in Sintra", event_dates=["2023-04-02"])
        self.add("The user went hiking in Arrabida", event_dates=["2026-08-15"])
        asked = datetime(2023, 5, 20, tzinfo=UTC)
        ranked = self.search("hiking last month", self.v2, as_of=asked)
        self.assertEqual(ranked[0].id, early)

    def test_first_and_latest_order_relevant_claims_by_time(self) -> None:
        first = self.add("The user tried sushi in Lisbon", event_dates=["2024-02-01"])
        latest = self.add("The user tried sushi in Tokyo", event_dates=["2026-06-01"])
        self.assertEqual(self.search("when did I first try sushi", self.v2)[0].id, first)
        self.assertEqual(self.search("the latest sushi I tried", self.v2)[0].id, latest)

    def test_ordinary_episodes_fade_from_when_they_happened(self) -> None:
        old = self.add("The user watched a Benfica match", event_dates=["2024-09-01"])
        [v1_hit] = [r for r in self.search("Benfica match", self.v1) if r.id == old]
        [v2_hit] = [r for r in self.search("Benfica match", self.v2) if r.id == old]
        # v1 ages from the write (today); v2 from the event two years ago.
        self.assertGreater(v1_hit.recency, 0.99)
        self.assertLess(v2_hit.recency, 0.01)

    def test_a_significant_episode_does_not_fade(self) -> None:
        wedding = self.add(
            "The user got married in Porto", event_dates=["2024-09-01"], importance=0.9
        )
        [hit] = [r for r in self.search("married Porto", self.v2) if r.id == wedding]
        self.assertGreater(hit.recency, 0.99)

    def test_repetition_across_sessions_outranks_a_single_mention(self) -> None:
        once = self.add("The user prefers green tea", kind="preference")
        often = self.add("The user prefers oolong tea", kind="preference", source_count=6)
        ranked = self.search("tea preference", self.v2)
        self.assertEqual(ranked[0].id, often)
        self.assertEqual({r.id for r in ranked}, {once, often})

    def test_an_unconfirmed_inference_ranks_below_a_stated_fact(self) -> None:
        stated = self.add("The user works on payments at Stripe", kind="fact")
        guessed = self.add(
            "The user works on payments infrastructure", kind="fact", source_role="inference"
        )
        ranked = self.search("payments work", self.v2)
        self.assertEqual([r.id for r in ranked], [stated, guessed])
        # v1 never trusted the label at all.
        self.assertNotIn(guessed, [r.id for r in self.search("payments work", self.v1)])

    def test_a_time_range_is_a_filter_not_a_boost(self) -> None:
        inside = self.add("The user visited Madrid", event_dates=["2026-05-02"])
        self.add("The user visited Madrid again", event_dates=["2025-05-02"])
        ranked = self.search(
            "Madrid",
            self.v2,
            time_range=(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 12, 31, tzinfo=UTC)),
        )
        self.assertEqual([r.id for r in ranked], [inside])

    def test_history_and_related_neighbours_respect_scopes(self) -> None:
        porto = self.add("The user lives in Porto", kind="fact")
        lisbon = self.add("The user lives in Lisbon", kind="fact")
        detail = self.add("The user lives in Alfama, Lisbon", kind="fact")
        with self.conn.transaction():
            store.supersede(
                self.conn, old_id=porto, new_id=lisbon, scopes=self.caller.writable_scope_ids
            )
            store.add_relation(self.conn, from_id=detail, to_id=lisbon, relation="extends")
        mine = graph.expand(
            self.conn,
            [lisbon],
            scope_ids=self.caller.scopes(),
            include_history=True,
            include_related=True,
        )[lisbon]
        self.assertEqual([(h["id"], h["relation"]) for h in mine["history"]], [(porto, "replaces")])
        self.assertEqual(
            [(r["id"], r["relation"]) for r in mine["related"]], [(detail, "extended_by")]
        )
        bob = self.team.principal("bob")
        theirs = graph.expand(
            self.conn, [lisbon], scope_ids=bob.scopes(), include_history=True, include_related=True
        )[lisbon]
        self.assertEqual(theirs, {"history": [], "related": []})

    def test_neighbours_bring_back_nothing_the_search_filtered_out(self) -> None:
        porto = self.add("The user lives in Porto", kind="fact")
        lisbon = self.add("The user lives in Lisbon", kind="fact")
        echo = self.add("The user lives near the river", kind="fact", source_role="assistant")
        with self.conn.transaction():
            store.supersede(
                self.conn, old_id=porto, new_id=lisbon, scopes=self.caller.writable_scope_ids
            )
            store.add_relation(self.conn, from_id=echo, to_id=lisbon, relation="extends")
        trusted = graph.expand(
            self.conn,
            [lisbon],
            scope_ids=self.caller.scopes(),
            include_history=True,
            include_related=True,
            allowed_roles=self.v2.allowed_source_roles,
        )[lisbon]
        self.assertEqual(trusted["related"], [])
        self.assertEqual([h["id"] for h in trusted["history"]], [porto])

        with self.conn.transaction():
            store.set_memory_status(
                self.conn, memory_id=porto, scopes=self.caller.writable_scope_ids, status="archived"
            )
        history = store.history_of(self.conn, lisbon, scope_ids=self.caller.scopes())
        self.assertEqual(history, [], "a deleted claim is not history")

    def test_restoring_a_superseded_claim_makes_it_current_again(self) -> None:
        porto = self.add("The user lives in Porto", kind="fact")
        lisbon = self.add("The user lives in Lisbon", kind="fact")
        with self.conn.transaction():
            store.supersede(
                self.conn, old_id=porto, new_id=lisbon, scopes=self.caller.writable_scope_ids
            )
            restored = store.set_memory_status(
                self.conn, memory_id=porto, scopes=self.caller.writable_scope_ids, status="active"
            )
        self.assertIsNone(restored["valid_until"])
        self.assertIsNone(restored["superseded_by"])
        self.assertEqual(store.history_of(self.conn, lisbon, scope_ids=self.caller.scopes()), [])
        self.assertIn(porto, [r.id for r in self.search("Porto", self.v1)])

    def test_a_window_finds_old_claims_outside_the_unwindowed_top(self) -> None:
        inside = self.add("The user ran a marathon", event_dates=["2019-04-07"])
        # Each decoy outranks it lexically, and there are more of them than
        # the Postgres arms fetch.
        for index in range(60):
            self.add(
                f"Marathon {index}: the user ran the marathon again", event_dates=["2026-04-07"]
            )
        ranked = self.search(
            "marathon",
            self.v1,
            limit=5,
            time_range=(datetime(2019, 1, 1, tzinfo=UTC), datetime(2019, 12, 31, tzinfo=UTC)),
        )
        self.assertEqual([r.id for r in ranked], [inside])


class SearchApiV2Test(ApiTestCase):
    def test_search_returns_dates_history_and_source_context(self) -> None:
        message = self.seed_message(
            content="Last Saturday I moved to Lisbon from Porto and it rained the whole drive"
        )
        porto = self.seed_memory(text="Alice lives in Porto", kind="fact")
        lisbon = self.seed_memory(
            text="Alice moved to Lisbon on 2026-03-14",
            kind="episode",
            event_dates=["2026-03-14"],
        )
        alice_scope = str(
            self.scalar("SELECT id FROM entities WHERE user_id=%s", self.team.alice_id)
        )
        with self.db.transaction():
            store.supersede(self.db, old_id=porto, new_id=lisbon, scopes=[alice_scope])
            quote = "moved to Lisbon"
            start = "Last Saturday I moved".index("moved")
            self.db.execute(
                """INSERT INTO memory_evidence
                   (memory_id,message_id,start_char,end_char,excerpt_sha256)
                   VALUES (%s,%s,%s,%s,%s)""",
                (
                    lisbon,
                    message,
                    start,
                    start + len(quote),
                    hashlib.sha256(quote.encode()).hexdigest(),
                ),
            )
        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={
                "query": "moved to Lisbon last march",
                "policy_id": "core-retrieval-v2",
                "as_of": "2026-04-10T00:00:00Z",
                "include_sources": True,
                "source_context_chars": 200,
                "include_history": True,
                "budget_tokens": 2000,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["temporal"]["window"]["start"][:7], "2026-03")
        [hit] = [m for m in body["memories"] if m["id"] == lisbon]
        self.assertEqual(hit["event_dates"], ["2026-03-14"])
        self.assertGreater(hit["temporal"], 0)
        self.assertEqual([h["id"] for h in hit["history"]], [porto])
        [source] = hit["sources"]
        self.assertEqual(source["excerpt"], "moved to Lisbon")
        self.assertIn("rained", source["context"])

    def test_the_v1_policy_is_still_available_by_name(self) -> None:
        self.seed_memory(text="Alice prefers pnpm")
        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={"query": "pnpm", "policy_id": "neutral-v1"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["policy_id"], "core-retrieval-neutral-v1")
        self.assertIsNone(response.json()["temporal"])

    def test_a_search_naming_no_policy_uses_the_server_default(self) -> None:
        self.seed_memory(text="Alice prefers pnpm")
        settings = config.get_settings().model_copy(update={"default_policy": "temporal-v2"})
        with patch.object(config, "_settings", settings):
            response = self.client.post(
                "/v1/memories/search", headers=self.auth, json={"query": "pnpm"}
            )
            named = self.client.post(
                "/v1/memories/search",
                headers=self.auth,
                json={"query": "pnpm", "policy_id": "neutral-v1"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["policy_id"], "core-retrieval-v2")
        self.assertEqual(named.json()["policy_id"], "core-retrieval-neutral-v1")

    def test_an_unknown_default_policy_refuses_to_start(self) -> None:
        settings = config.get_settings().model_copy(update={"default_policy": "nuetral-v1"})
        with self.assertRaisesRegex(RuntimeError, "nuetral-v1"):
            api.check_default_policy(self.db, settings)
        api.check_default_policy(self.db, config.get_settings())

    def test_an_inverted_time_range_is_refused(self) -> None:
        response = self.client.post(
            "/v1/memories/search",
            headers=self.auth,
            json={
                "query": "pnpm",
                "since": "2026-05-01T00:00:00Z",
                "until": "2026-01-01T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 422)
