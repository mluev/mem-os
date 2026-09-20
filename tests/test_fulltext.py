"""The two SQL candidate arms, which Postgres made real.

Under SQLite these were one FTS5 table queried twice. FTS5's tokenizer does no
stemming at all, so the lexical arm could only ever match a word the user had
typed in exactly the form it was stored in -- useless for Russian, where every
noun and verb the store holds appears in a different case or person from the one
the query uses. And because the "exact identifier" arm read the same table, it
was a subset of the lexical arm rather than an independent source of candidates.

Postgres splits them properly. The lexical arm is a generated `search_tsv` under
the `russian` configuration, which stems Cyrillic with russian_stem and ASCII
with english_stem, so one column covers both languages. The identifier arm is a
trigram `ILIKE`, which is what an error code needs precisely because it has no
lexeme to stem.

Both arms carry the same authorization predicate, and that is the property that
must not regress: a second way to find a memory is a second way to leak one.
"""

from __future__ import annotations

import unittest

from memkit import retrieval, store
from tests.fixtures import StubEmbedder, StubQdrant, make_db, seed_team

RUSSIAN_FACT = "Алиса предпочитает тёмную тему в редакторе"
ENGLISH_FACT = "We deployed the payments service on Friday"
ERROR_FACT = "Сборка упала с кодом ERR_X91Q"
TICKET_FACT = "Задача ticket-000123 закрыта"


def _folds_cyrillic_case(conn) -> bool:
    """Whether this database can lower-case Cyrillic at all.

    `to_tsvector` folds case with the database's ctype. A cluster created
    without a UTF-8 locale silently leaves Cyrillic untouched, and every
    case-insensitive claim below it becomes false.
    """
    row = conn.execute(
        "SELECT to_tsvector('russian',%s) @@ plainto_tsquery('russian',%s) AS hit",
        ("ПРЕДПОЧИТАЕТ", "предпочитаю"),
    ).fetchone()
    return bool(row["hit"])


class FullTextTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)
        self.caller = self.team.principal("alice")
        self.scopes = self.caller.scopes()

    def tearDown(self) -> None:
        self.conn.close()

    def _add(self, text: str, **kw) -> str:
        with self.conn.transaction():
            return store.add_memory(
                self.conn,
                scope_id=kw.pop("scope_id", self.caller.own_entity_id),
                author_id=kw.pop("author_id", self.team.alice_id),
                text=text,
                kind=kw.pop("kind", "fact"),
                source_role=kw.pop("source_role", "user"),
                **kw,
            )

    def _lexical(self, query: str, *, scope_ids: list[str] | None = None) -> dict[str, float]:
        return retrieval._lexical_candidates(
            self.conn,
            query=query,
            scope_ids=self.scopes if scope_ids is None else scope_ids,
            limit=50,
        )

    def _entity(self, query: str, *, scope_ids: list[str] | None = None) -> dict[str, float]:
        return retrieval._entity_candidates(
            self.conn,
            query=query,
            scope_ids=self.scopes if scope_ids is None else scope_ids,
            limit=50,
        )


class LexicalArmTest(FullTextTestCase):
    def test_a_russian_verb_is_found_by_a_different_inflection(self) -> None:
        """The whole reason the lexical arm moved to Postgres.

        Nobody searching their own memory types the third person singular. FTS5
        matched literal tokens, so `предпочитаю` never found `предпочитает`.
        """
        memory_id = self._add(RUSSIAN_FACT)
        self.assertEqual(list(self._lexical("предпочитаю")), [memory_id])

    def test_a_russian_noun_is_found_in_another_case(self) -> None:
        memory_id = self._add(RUSSIAN_FACT)
        self.assertEqual(list(self._lexical("тема редактора")), [memory_id])

    def test_an_english_verb_is_found_by_its_stem(self) -> None:
        """One configuration covers both languages, so neither needs a branch."""
        memory_id = self._add(ENGLISH_FACT)
        self.assertEqual(list(self._lexical("deploy")), [memory_id])
        self.assertEqual(list(self._lexical("payment")), [memory_id])

    def test_a_capitalised_cyrillic_word_matches_a_lower_case_query(self) -> None:
        """Every Russian sentence starts with a capital and every name has one.

        Case folding belongs to the database, and it only happens when the
        cluster has a UTF-8 locale. Under `LC_CTYPE=C` Postgres cannot
        lower-case Cyrillic, the stemmer keeps the leading capital, and this
        arm quietly becomes case-sensitive for exactly the words that matter --
        so the capability is checked rather than assumed.
        """
        if not _folds_cyrillic_case(self.conn):
            self.skipTest("database locale cannot case-fold Cyrillic")
        memory_id = self._add("ПРЕДПОЧИТАЕТ тёмную тему")
        self.assertEqual(list(self._lexical("предпочитаю")), [memory_id])

    def test_an_ascii_word_matches_whatever_case_it_was_typed_in(self) -> None:
        memory_id = self._add(ENGLISH_FACT)
        self.assertEqual(list(self._lexical("DEPLOYED")), [memory_id])

    def test_the_best_hit_is_normalised_to_one(self) -> None:
        """`ts_rank_cd` is unbounded, and the fusion weights assume a cosine.

        Without normalisation the arm's contribution depends on corpus
        statistics, so an equally relevant second result can fall below the
        abstention floor for no reason a reader could name.
        """
        first = self._add(ENGLISH_FACT)
        second = self._add("We deployed the billing service on Monday")
        scores = self._lexical("deploy")
        self.assertEqual(set(scores), {first, second})
        self.assertAlmostEqual(max(scores.values()), 1.0)
        self.assertTrue(all(0.0 < value <= 1.0 for value in scores.values()))

    def test_an_archived_memory_is_not_a_candidate(self) -> None:
        memory_id = self._add(ENGLISH_FACT)
        with self.conn.transaction():
            store.set_memory_status(
                self.conn, memory_id=memory_id, scopes=self.scopes, status="archived"
            )
        self.assertEqual(self._lexical("deploy"), {})

    def test_only_the_scopes_the_caller_holds_are_searched(self) -> None:
        self._add(ENGLISH_FACT, scope_id=self.team.scope_of("bob"), author_id=self.team.bob_id)
        self.assertEqual(self._lexical("deploy"), {})

    def test_a_query_with_no_usable_terms_reads_nothing(self) -> None:
        """An empty candidate set has to come from an early return, not a scan."""
        self._add(ENGLISH_FACT)
        self.assertEqual(self._lexical("   "), {})
        self.assertEqual(self._lexical("deploy", scope_ids=[]), {})


class EntityArmTest(FullTextTestCase):
    def test_a_substring_of_an_identifier_is_reachable_only_by_the_entity_arm(self) -> None:
        """The two arms are genuinely independent, not one a subset of the other.

        The tokenizer splits `err_x91q` into lexemes, so the halves are findable
        lexically; `91Q` sits inside one of them and is not a lexeme of
        anything. Substring reach is the entity arm's whole reason to exist, and
        under FTS5 both arms queried the same table, which made the claim
        untestable.
        """
        memory_id = self._add("The deploy failed with ERR_X91Q on retry")
        self.assertEqual(self._lexical("91Q"), {})
        self.assertIn(memory_id, self._entity("91Q"))

    def test_a_ticket_number_is_found_by_its_digits_alone(self) -> None:
        memory_id = self._add(TICKET_FACT)
        self.assertEqual(self._lexical("000123"), {})
        self.assertEqual(self._entity("000123"), {memory_id: 1.0})

    def test_the_identifier_arm_ignores_ordinary_prose(self) -> None:
        """Otherwise every common word would fan out over a trigram scan."""
        self._add(ERROR_FACT)
        self._add(ENGLISH_FACT)
        self.assertEqual(self._entity("what did we deploy on friday"), {})

    def test_an_identifier_matches_whatever_case_it_was_typed_in(self) -> None:
        memory_id = self._add(ERROR_FACT)
        self.assertEqual(self._entity("err_x91q"), {memory_id: 1.0})

    def test_only_the_scopes_the_caller_holds_are_searched(self) -> None:
        self._add(ERROR_FACT, scope_id=self.team.scope_of("bob"), author_id=self.team.bob_id)
        self.assertEqual(self._entity("ERR_X91Q"), {})


class FusedArmsTest(FullTextTestCase):
    """What the two arms do once the scorer has them, on a stub dense index."""

    def _search(self, query: str, **kw):
        return retrieval.explain(
            self.conn,
            StubQdrant(),
            StubEmbedder(),
            query=query,
            scope_ids=kw.pop("scope_ids", self.scopes),
            **kw,
        )

    def test_a_russian_paraphrase_reaches_the_reader(self) -> None:
        memory_id = self._add(RUSSIAN_FACT)
        result = self._search("что предпочитаю")
        self.assertEqual([item.id for item in result.chosen], [memory_id])
        self.assertGreater(result.chosen[0].lexical, 0.0)

    def test_an_identifier_alone_clears_the_abstention_floor(self) -> None:
        """0.30 lexical plus 0.10 entity, with no dense contribution at all."""
        memory_id = self._add(ERROR_FACT)
        [hit] = self._search("ERR_X91Q").chosen
        self.assertEqual(hit.id, memory_id)
        self.assertAlmostEqual(hit.lexical, 1.0)
        self.assertAlmostEqual(hit.entity, 1.0)
        self.assertEqual(hit.similarity, 0.0)

    def test_the_scope_predicate_applies_to_both_arms(self) -> None:
        """A teammate's private note is unreachable by wording and by code alike."""
        bob_scope = self.team.scope_of("bob")
        self._add(RUSSIAN_FACT, scope_id=bob_scope, author_id=self.team.bob_id)
        self._add(ERROR_FACT, scope_id=bob_scope, author_id=self.team.bob_id)
        self.assertEqual(self._lexical("предпочитаю"), {})
        self.assertEqual(self._entity("ERR_X91Q"), {})
        self.assertEqual(self._search("предпочитаю").chosen, [])
        self.assertEqual(self._search("ERR_X91Q").chosen, [])
        # And they are found by the person who owns them, so the empty result
        # above is the predicate and not a broken fixture.
        bob = self.team.principal("bob")
        self.assertTrue(self._search("ERR_X91Q", scope_ids=bob.scopes()).chosen)


if __name__ == "__main__":
    unittest.main()
