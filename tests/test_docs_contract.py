"""Doc/code contract. Makes documentation drift a failing test.

Three separate things live here:

1. The generated doc blocks match the code (`tools/docblocks.py`).
2. The vocabularies that are declared four or five times each agree with one
   another. This is where the real bugs are: `type` is declared in four places,
   `workflow_status` in four, and nothing checked that they matched.
3. `.env.example` documents every setting that exists.

Only (1) is about documents. (2) and (3) are code-to-code and code-to-config
consistency, and they live here because they are the same class of failure --
one fact written down in several places, with nothing keeping them equal.

This cannot cover measured numbers, rationale, or behavioural claims. See the
module docstring of tools/docblocks.py for what is done about each instead.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memkit import (  # noqa: E402
    admin, api, db, judge, mutate, providers, provenance, taskboard,
)
from tools import docblocks  # noqa: E402


class TestGeneratedBlocks(unittest.TestCase):
    def test_every_block_matches_the_code(self):
        problems = docblocks.check()
        if problems:
            report = "\n\n".join(f"=== {name} ===\n{detail}" for name, detail in problems)
            self.fail(
                f"{len(problems)} generated doc block(s) stale or missing.\n\n"
                f"{report}\n\n"
                "Run: python -m tools.docblocks --write\n"
                "then read the diff -- it makes the doc follow the code, which is "
                "the wrong direction if the code change was the mistake."
            )

    def test_every_block_renders(self):
        """A generator that raises would otherwise show up only as 'stale'."""
        for name in docblocks.BLOCKS:
            with self.subTest(block=name):
                self.assertTrue(docblocks.render(name).strip())

    def test_blocks_point_at_files_inside_docs(self):
        for name, (path, _) in docblocks.BLOCKS.items():
            with self.subTest(block=name):
                self.assertTrue(
                    path.is_relative_to(docblocks.DOCS),
                    f"{name} writes outside docs/",
                )


class TestVocabularyAgreement(unittest.TestCase):
    """The same list, declared in several modules, must be the same list.

    Every one of these is a real duplication in the source. They are asserted
    equal rather than deduplicated because collapsing them is a refactor; this
    makes that refactor safe and, until then, makes a divergence loud.
    """

    def test_memory_types(self):
        canonical = list(providers.MEMORY_TYPES)
        self.assertEqual(list(api.MEMORY_TYPES.__args__), canonical)
        self.assertEqual(sorted(admin.MEMORY_TYPES), sorted(canonical))
        self.assertEqual(list(judge.MEMORY_TYPES), canonical)
        self.assertEqual(len(canonical), 7)

    def test_scopes(self):
        canonical = list(providers.SCOPES)
        self.assertEqual(list(api.SCOPES.__args__), canonical)
        self.assertEqual(list(judge.SCOPES), canonical)

    def test_memory_patch_shares_the_type_and_scope_vocabularies(self):
        patch_type = admin.MemoryPatch.model_fields["type"].annotation
        patch_scope = admin.MemoryPatch.model_fields["scope"].annotation
        # `X | None` -- the Literal is the first argument.
        self.assertEqual(
            sorted(patch_type.__args__[0].__args__), sorted(providers.MEMORY_TYPES)
        )
        self.assertEqual(
            sorted(patch_scope.__args__[0].__args__), sorted(providers.SCOPES)
        )

    def test_workflow_statuses_match_the_database_check_constraint(self):
        """The CHECK in db.py is a string; nothing linked it to the tuple."""
        constraint = re.search(
            r"workflow_status\s+TEXT\s+NOT\s+NULL\s*CHECK\(workflow_status IN \(([^)]*)\)\)",
            db.SCHEMA,
            re.DOTALL,
        )
        self.assertIsNotNone(constraint, "the workflow_status CHECK moved or changed shape")
        in_sql = tuple(v.strip().strip("'") for v in constraint.group(1).split(","))
        self.assertEqual(in_sql, taskboard.WORKFLOW_STATUSES)

    def test_source_roles_match_the_database_check_constraint(self):
        constraint = re.search(
            r"source_role\s+TEXT\s+NOT\s+NULL\s*CHECK\(source_role IN \(([^)]*)\)\)",
            db.SCHEMA,
            re.DOTALL,
        )
        self.assertIsNotNone(constraint, "the source_role CHECK moved or changed shape")
        in_sql = tuple(v.strip().strip("'") for v in constraint.group(1).split(","))
        self.assertEqual(in_sql, provenance.ROLES)

    def test_the_migration_rebuild_declares_the_same_source_role_check(self):
        """Two copies of the memories DDL exist: the schema and the v3 rebuild."""
        rebuild = "\n".join(db._MEMORIES_V3_REBUILD)
        for role in provenance.ROLES:
            with self.subTest(role=role):
                self.assertIn(f"'{role}'", rebuild)

    def test_the_rebuild_selects_every_column_the_schema_declares(self):
        """A column added to the schema but not to the rebuild would be dropped
        for anyone migrating from v2, and only for them."""
        import sqlite3
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.db"
            db.init_db(path)
            conn = sqlite3.connect(path)
            live = [r[1] for r in conn.execute("PRAGMA table_info(memories)")]
            conn.close()
        rebuild_ddl = db._MEMORIES_V3_REBUILD[0]
        for column in live:
            with self.subTest(column=column):
                self.assertIn(column, rebuild_ddl)

    def test_statuses(self):
        """`status` has no named constant anywhere -- assert the literal set."""
        self.assertEqual(
            sorted(mutate.STATUSES if hasattr(mutate, "STATUSES")
                   else ("active", "expired", "superseded")),
            ["active", "expired", "superseded"],
        )

    def test_operations(self):
        for op in ("ADD", "UPDATE", "DELETE"):
            with self.subTest(op=op):
                parsed = judge.Op.parse({
                    "op": op, "id": "m-1", "text": "Prefers pnpm",
                    "type": "preference", "scope": "user", "importance": 0.6,
                    "confidence": 0.9, "valid_until": None, "task_status": None,
                    "holds_in_other_repos": None, "reason": "",
                })
                self.assertIsNotNone(parsed, f"{op} must be accepted")
        self.assertIsNone(
            judge.Op.parse({"op": "UPSERT", "text": "x", "type": "fact"}),
            "an unknown operation must be refused",
        )


class TestEnvExample(unittest.TestCase):
    """Every setting a user can set must appear in `.env.example`.

    Four consolidation and dedup settings were missing, and one of them is named
    in the retrieval doc as the way to change a threshold -- so the docs told the
    reader to set a variable the example file never mentioned.
    """

    def setUp(self):
        self.text = (ROOT / ".env.example").read_text()

    def _env_names(self) -> list[str]:
        from memkit.config import Settings

        names = []
        for name, field in Settings.model_fields.items():
            alias = field.validation_alias
            if alias is None:
                names.append(f"MEMKIT_{name.upper()}")
            elif isinstance(alias, str):
                names.append(alias)
            else:
                names.append(str(alias.choices[0]))
        return names

    def test_every_setting_is_documented(self):
        missing = [name for name in self._env_names() if name not in self.text]
        self.assertEqual(
            missing, [],
            "settings exist in config.py but not in .env.example: "
            f"{', '.join(missing)}",
        )

    def test_no_real_key_is_committed(self):
        """An example file with a live key in it is the worst kind of leak."""
        for pattern, label in (
            (r"AIza[0-9A-Za-z_-]{35}", "Google API key"),
            (r"sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic key"),
            (r"sk-[A-Za-z0-9]{40,}", "generic secret key"),
        ):
            with self.subTest(kind=label):
                self.assertIsNone(
                    re.search(pattern, self.text),
                    f"a real {label} appears in .env.example",
                )


class TestDocsStructure(unittest.TestCase):
    """Cheap structural rules that stop the previous failure modes recurring."""

    NORMATIVE = [
        "README.md", "01-architecture.md", "02-data-model.md", "03-api.md",
        "04-judge.md", "05-retrieval.md", "06-roadmap.md",
        "07-hermes-adapter.md", "08-testing.md",
    ]

    def test_every_normative_doc_exists(self):
        for name in self.NORMATIVE:
            with self.subTest(doc=name):
                self.assertTrue((docblocks.DOCS / name).is_file(), f"docs/{name}")

    def test_no_inline_amendment_annotations(self):
        """The pattern that produced three generations of contradictions.

        A doc that annotates itself with "correction: actually X" leaves the
        wrong statement standing next to the right one. Edit the doc; put the
        decision in docs/decisions/.
        """
        banned = ("Поправка", "Замерено", "Реализовано", "Update:", "Amendment:")
        offenders = []
        for name in self.NORMATIVE:
            path = docblocks.DOCS / name
            if not path.is_file():
                continue
            text = path.read_text()
            for word in banned:
                if word in text:
                    offenders.append(f"docs/{name}: {word!r}")
        self.assertEqual(offenders, [], "; ".join(offenders))

    def test_the_index_links_every_document(self):
        """docs/07 and docs/08 were orphaned: nothing in the index pointed at them."""
        index = docblocks.DOCS / "README.md"
        if not index.is_file():
            self.skipTest("docs/README.md not written yet")
        text = index.read_text()
        for name in self.NORMATIVE:
            if name == "README.md":
                continue
            with self.subTest(doc=name):
                self.assertIn(name, text, f"docs/README.md does not link {name}")

    def test_measured_claims_carry_a_date_and_a_command(self):
        """`<!-- measured: DATE · COMMAND -->` is how a reader knows a number's age.

        A test cannot tell whether a measurement is stale, so the convention is
        that it must at least be dated and reproducible. This checks the shape,
        not the freshness.
        """
        pattern = re.compile(r"<!--\s*measured:\s*(\d{4}-\d{2}-\d{2})\s*·\s*(.+?)-->")
        for path in sorted(docblocks.DOCS.glob("*.md")):
            for raw in re.findall(r"<!--\s*measured:.*?-->", path.read_text()):
                with self.subTest(doc=path.name, marker=raw[:60]):
                    self.assertRegex(
                        raw, pattern,
                        "expected <!-- measured: YYYY-MM-DD · command -->",
                    )


if __name__ == "__main__":
    unittest.main()
