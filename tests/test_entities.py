"""Entities: who a memory can be about, and how a name finds them.

The routing layer is only as good as this module. If an alias resolves to the
wrong entity, a fact about one person lands on another person's page and no
later check catches it — the memory is well-formed, cited, and about the wrong
human. So the claims worth testing here are mostly about refusing to guess.
"""

from __future__ import annotations

import unittest

from memkit import entities, judge, store, users
from memkit.db import slugify
from tests.fixtures import PASSWORD, make_db, seed_team


class UserScaffoldingTest(unittest.TestCase):
    """A user is unusable without a private scope, so both are made at once."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_creating_a_user_creates_their_private_entity(self) -> None:
        own = entities.own_entity(self.conn, self.team.alice_id)
        self.assertIsNotNone(own)
        self.assertEqual(own["kind"], "user")
        self.assertEqual(own["name"], "Alice Ivanova")

    def test_creating_a_user_joins_them_to_the_team(self) -> None:
        """The shared rules are not opt-in: a user who cannot read them would
        silently get different behaviour from everyone else."""
        handles = {row["handle"] for row in entities.members(self.conn, self.team.team_id)}
        self.assertEqual(handles, {"alice", "bob"})

    def test_a_private_scope_is_writable_by_its_owner_only(self) -> None:
        alice_scope = self.team.scope_of("alice")
        self.assertIn(alice_scope, entities.writable_by(self.conn, self.team.alice_id))
        self.assertNotIn(alice_scope, entities.writable_by(self.conn, self.team.bob_id))


class SlugTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _create(self, name: str, **kw):
        with self.conn.transaction():
            return entities.create(
                self.conn, kind="project", name=name, created_by=self.team.alice_id, **kw
            )

    def test_a_slug_is_derived_from_the_name(self) -> None:
        self.assertEqual(self._create("Billing Service")["slug"], "billing-service")

    def test_a_cyrillic_name_still_yields_a_usable_slug(self) -> None:
        """Slugs reach URLs and CLI arguments, so they have to be ASCII."""
        slug = str(self._create("Магазин")["slug"])
        self.assertEqual(slug, slugify("Магазин"))
        self.assertTrue(slug.isascii() and slug)

    def test_a_colliding_slug_is_suffixed_rather_than_rejected(self) -> None:
        first = self._create("Billing Service")
        second = self._create("Billing Service", aliases=["billing two"])
        self.assertEqual(first["slug"], "billing-service")
        self.assertEqual(second["slug"], "billing-service-2")


class AliasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _project(self, name: str, aliases: list[str] | None = None):
        with self.conn.transaction():
            return entities.create(
                self.conn,
                kind="project",
                name=name,
                created_by=self.team.alice_id,
                aliases=aliases or [],
            )

    def test_an_alias_is_claimed_by_the_first_entity_only(self) -> None:
        """Two entities answering to one name makes routing undecidable."""
        first = self._project("Shop", aliases=["магазин"])
        second = self._project("Storefront")
        with self.conn.transaction():
            added = entities.add_aliases(
                self.conn, entity_id=str(second["id"]), aliases=["магазин"]
            )
        self.assertEqual(added, [])
        resolved = entities.resolve_alias(self.conn, "магазин")
        self.assertEqual(str(resolved["id"]), str(first["id"]))

    def test_alias_matching_folds_cyrillic_case(self) -> None:
        """Case folding, not lowering: Cyrillic is why the distinction matters."""
        project = self._project("Sasha's desk", aliases=["Саша"])
        for spelling in ("Саша", "САША", "саша", "  саша  "):
            resolved = entities.resolve_alias(self.conn, spelling)
            self.assertIsNotNone(resolved, spelling)
            self.assertEqual(str(resolved["id"]), str(project["id"]), spelling)

    def test_case_insensitivity_also_governs_uniqueness(self) -> None:
        self._project("Sasha's desk", aliases=["Саша"])
        other = self._project("Another desk")
        with self.conn.transaction():
            added = entities.add_aliases(self.conn, entity_id=str(other["id"]), aliases=["САША"])
        self.assertEqual(added, [])

    def test_resolve_alias_is_exact_and_never_guesses(self) -> None:
        """A near miss returns None on purpose.

        Guessing attaches a claim to the wrong person, which no later step can
        detect. An unresolved name becomes a needs-attention item instead.
        """
        self._project("Sasha's desk", aliases=["Саша"])
        for near_miss in ("Сашка", "Саш", "Сашa", "sasha"):
            self.assertIsNone(entities.resolve_alias(self.conn, near_miss), near_miss)

    def test_an_archived_entity_stops_answering_to_its_name(self) -> None:
        project = self._project("Shop", aliases=["магазин"])
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE entities SET archived_at=now() WHERE id=%s", (str(project["id"]),)
            )
        self.assertIsNone(entities.resolve_alias(self.conn, "магазин"))

    def test_removing_an_alias_frees_it_for_another_entity(self) -> None:
        first = self._project("Shop", aliases=["магазин"])
        second = self._project("Storefront")
        with self.conn.transaction():
            self.assertTrue(
                entities.remove_alias(self.conn, entity_id=str(first["id"]), alias="МАГАЗИН")
            )
            entities.add_aliases(self.conn, entity_id=str(second["id"]), aliases=["магазин"])
        resolved = entities.resolve_alias(self.conn, "магазин")
        self.assertEqual(str(resolved["id"]), str(second["id"]))


class VisibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _slugs(self, who: str) -> set[str]:
        user_id = self.team.alice_id if who == "alice" else self.team.bob_id
        return {str(row["slug"]) for row in entities.visible_to(self.conn, user_id)}

    def test_a_teammates_private_scope_is_not_visible(self) -> None:
        """A person is a visible subject; their private space is not."""
        bob_own = entities.own_entity(self.conn, self.team.bob_id)
        self.assertNotIn(str(bob_own["slug"]), self._slugs("alice"))

    def test_archiving_hides_an_entity_but_keeps_its_memories(self) -> None:
        """Archiving is a shelf, not an eraser.

        The project is over; the decisions taken inside it are still the record
        of why the code looks the way it does.
        """
        with self.conn.transaction():
            memory_id = store.add_memory(
                self.conn,
                scope_id=self.team.project_id,
                author_id=self.team.alice_id,
                text="Mem OS stores memories in Postgres",
                kind="decision",
                source_role="user",
                review_status="confirmed",
            )
            self.conn.execute(
                "UPDATE entities SET archived_at=now() WHERE id=%s", (self.team.project_id,)
            )
        self.assertNotIn("mem-os", self._slugs("alice"))
        row = self.conn.execute("SELECT * FROM memories WHERE id=%s", (memory_id,)).fetchone()
        self.assertEqual(row["status"], "active")
        self.assertEqual(str(row["scope_id"]), self.team.project_id)

    def test_an_archived_entity_is_no_longer_writable(self) -> None:
        with self.conn.transaction():
            self.conn.execute(
                "UPDATE entities SET archived_at=now() WHERE id=%s", (self.team.project_id,)
            )
        self.assertNotIn(self.team.project_id, entities.writable_by(self.conn, self.team.alice_id))

    def test_a_viewer_may_read_a_scope_but_not_write_to_it(self) -> None:
        with self.conn.transaction():
            entities.set_member(
                self.conn,
                entity_id=self.team.project_id,
                user_id=self.team.bob_id,
                role="viewer",
            )
        self.assertIn("mem-os", self._slugs("bob"))
        self.assertNotIn(self.team.project_id, entities.writable_by(self.conn, self.team.bob_id))

    def test_an_ordinary_member_may_write(self) -> None:
        self.assertIn(self.team.project_id, entities.writable_by(self.conn, self.team.bob_id))

    def test_teammates_lists_the_other_users_entities(self) -> None:
        names = [str(row["name"]) for row in entities.teammates(self.conn, self.team.alice_id)]
        self.assertEqual(names, ["Bob Petrov"])
        self.assertEqual(
            [str(row["name"]) for row in entities.teammates(self.conn, self.team.bob_id)],
            ["Alice Ivanova"],
        )

    def test_a_disabled_user_stops_being_a_teammate(self) -> None:
        """Nobody should be routed a fact about someone who has left."""
        with self.conn.transaction():
            users.update(self.conn, user_id=self.team.bob_id, disabled=True)
        self.assertEqual(entities.teammates(self.conn, self.team.alice_id), [])


class PromptBlockTest(unittest.TestCase):
    """The ENTITIES block the extractor routes by."""

    def setUp(self) -> None:
        self.conn = make_db(seed=False)
        self.team = seed_team(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_the_speaker_and_the_team_come_first(self) -> None:
        """Order is the contract: the block is capped, and operations refer to
        positions in it, so the speaker must never be the entry that is cut."""
        block = entities.for_prompt(self.conn, user_id=self.team.alice_id)
        self.assertEqual(block[0]["label"], "you, the speaker")
        self.assertEqual(block[0]["name"], "Alice Ivanova")
        self.assertEqual(block[1]["kind"], "team")
        labels = [item["label"] for item in block]
        self.assertEqual(labels.index("project") < labels.index("teammate"), True)

    def test_every_entry_carries_the_names_people_actually_say(self) -> None:
        project = next(
            item
            for item in entities.for_prompt(self.conn, user_id=self.team.alice_id)
            if item["kind"] == "project"
        )
        self.assertEqual(project["aliases"], ["memkit"])

    def test_the_entity_a_name_belongs_to_is_never_repeated(self) -> None:
        block = entities.for_prompt(self.conn, user_id=self.team.alice_id)
        ids = [item["id"] for item in block]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_block_is_numbered_from_one(self) -> None:
        """The model may answer only with numbers, so they have to be there."""
        block = entities.for_prompt(self.conn, user_id=self.team.alice_id)
        rendered = judge.render_entities([{**item, "ref": i + 1} for i, item in enumerate(block)])
        lines = rendered.splitlines()
        self.assertEqual(len(lines), len(block))
        self.assertTrue(lines[0].startswith("1. you, the speaker: Alice Ivanova"))
        self.assertIn("aliases: memkit", rendered)

    def test_the_block_is_capped(self) -> None:
        with self.conn.transaction():
            for index in range(6):
                entities.create(
                    self.conn,
                    kind="project",
                    name=f"Project {index}",
                    created_by=self.team.alice_id,
                )
        self.assertEqual(
            len(entities.for_prompt(self.conn, user_id=self.team.alice_id, limit=3)), 3
        )

    def test_a_second_instance_of_a_handle_is_refused(self) -> None:
        """Handles are how a person is named at the door; two would be a fork."""
        with self.assertRaises(Exception), self.conn.transaction():
            users.create(self.conn, handle="alice", display_name="Impostor", password=PASSWORD)


if __name__ == "__main__":
    unittest.main()
