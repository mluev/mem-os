"""Extraction pipeline tests.

Runs entirely offline with a stub Qdrant client and a stub embedder, so the whole
apply path is verified without an API key or a running container:

    python3 -m unittest discover -s tests -t .   (needs the venv for pydantic)
    uv run python -m unittest discover -s tests -t .

The judge's network call is the only part not covered here; everything that
happens to SQLite and Qdrant afterwards is.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import extract, judge, prompts, providers, retrieval  # noqa: E402
from memkit.db import connect, ensure_owner, ensure_session, init_db  # noqa: E402

OWNER = "u-test"


class StubEmbedder:
    """Deterministic unit vectors — no model load, no MPS."""

    def encode_one(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 1023

    def encode(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        return [self.encode_one(t) for t in texts]


class StubQdrant:
    def __init__(self) -> None:
        self.points: dict[str, dict] = {}
        self.deleted: list[str] = []

    def upsert(self, collection_name, points, wait=True):
        for p in points:
            self.points[str(p.id)] = p.payload

    def delete(self, collection_name, points_selector, wait=True):
        for pid in points_selector:
            self.deleted.append(str(pid))
            self.points.pop(str(pid), None)

    def set_payload(self, collection_name, points, payload, wait=True):
        for pid in points:
            self.points[str(pid)].update(payload)

    def query_points(self, collection_name, **kwargs):
        """Candidate lookup returns nothing.

        Enough for the pipeline tests: what they assert is what happens to SQLite
        and Qdrant after the judge answers, and an empty CANDIDATES block is the
        common case in production anyway.
        """
        return SimpleNamespace(points=[])


def make_db():
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    init_db(tmp)
    conn = connect(tmp)
    ensure_owner(conn, OWNER, "test")
    ensure_session(conn, "s-1", OWNER, "chat")
    return conn


def make_judge_run(conn, cost=0.002) -> int:
    """Insert a real judge_runs row and return its id.

    memories.judge_run_id is a foreign key, so a fabricated id is rejected —
    provenance cannot point at a judge run that never happened. Production
    always has a real row here because judge.extract() logs before applying.
    """
    cur = conn.execute(
        """INSERT INTO judge_runs
           (kind, model, prompt_version, input_json, cost_usd, created_at)
           VALUES ('extract', ?, ?, '{}', ?, '2026-07-01T00:00:00Z')""",
        (judge.DEFAULT_MODEL, judge.PROMPT_VERSION, cost),
    )
    conn.commit()
    return int(cur.lastrowid)


def add_messages(conn, n=10, role="user", content="hello there friend"):
    ids = []
    for i in range(n):
        cur = conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) "
            "VALUES ('s-1', ?, ?, '2026-07-01T00:00:00Z')",
            (role, f"{content} {i}"),
        )
        ids.append(int(cur.lastrowid))
    conn.commit()
    return ids


def apply(conn, q, ops, **kw):
    run_id = kw.get("judge_run_id")
    if run_id is None:
        run_id = make_judge_run(conn)
    return extract.apply_ops(
        conn, q, StubEmbedder(), ops=ops, owner_id=OWNER,
        agent_id=kw.get("agent_id", "chat"), scope_key=kw.get("scope_key"),
        judge_run_id=run_id,
        source_message_ids=kw.get("source_message_ids", []),
    )


# --------------------------------------------------------------------------
# Schema-adjacent validation. strict mode cannot express "text is required when
# op is ADD", so Op.parse enforces the cross-field rules.
# --------------------------------------------------------------------------
class TestOpParse(unittest.TestCase):
    def test_valid_add(self):
        op = judge.Op.parse({
            "op": "ADD", "text": "Prefers pnpm", "type": "preference",
            "scope": "user", "importance": 0.8, "confidence": 0.9,
            "id": None, "valid_until": None, "reason": "said so",
        })
        self.assertIsNotNone(op)
        self.assertEqual(op.op, "ADD")
        self.assertEqual(op.importance, 0.8)

    def test_lowercase_op_accepted(self):
        op = judge.Op.parse({"op": "add", "text": "x", "type": "fact", "reason": "r"})
        self.assertIsNotNone(op)
        self.assertEqual(op.op, "ADD")

    def test_unknown_op_rejected(self):
        self.assertIsNone(judge.Op.parse({"op": "MERGE", "reason": "r"}))

    def test_task_status_is_validated_and_non_task_status_is_ignored(self):
        task = judge.Op.parse(
            {
                "op": "ADD",
                "text": "Ship the release",
                "type": "task",
                "task_status": "doing",
                "reason": "explicitly in progress",
            }
        )
        fact = judge.Op.parse(
            {
                "op": "ADD",
                "text": "Uses pnpm",
                "type": "fact",
                "task_status": "done",
                "reason": "not a task",
            }
        )
        invalid = judge.Op.parse(
            {
                "op": "ADD",
                "text": "Ship the release",
                "type": "task",
                "task_status": "blocked",
                "reason": "unsupported status",
            }
        )
        self.assertEqual(task.task_status, "doing")
        self.assertIsNone(fact.task_status)
        self.assertIsNone(invalid.task_status)

    def test_add_without_text_rejected(self):
        self.assertIsNone(
            judge.Op.parse({"op": "ADD", "type": "fact", "text": "", "reason": "r"})
        )

    def test_add_with_whitespace_only_text_rejected(self):
        self.assertIsNone(
            judge.Op.parse({"op": "ADD", "type": "fact", "text": "   ", "reason": "r"})
        )

    def test_add_with_bad_type_rejected(self):
        self.assertIsNone(
            judge.Op.parse({"op": "ADD", "text": "x", "type": "vibe", "reason": "r"})
        )

    def test_update_without_id_rejected(self):
        self.assertIsNone(judge.Op.parse({"op": "UPDATE", "text": "x", "reason": "r"}))

    def test_delete_without_id_rejected(self):
        self.assertIsNone(judge.Op.parse({"op": "DELETE", "reason": "r"}))

    def test_delete_needs_no_text(self):
        op = judge.Op.parse({"op": "DELETE", "id": "m-1", "reason": "stale"})
        self.assertIsNotNone(op)

    def test_importance_out_of_range_clamped(self):
        hi = judge.Op.parse({"op": "ADD", "text": "x", "type": "fact",
                             "importance": 4.2, "reason": "r"})
        lo = judge.Op.parse({"op": "ADD", "text": "x", "type": "fact",
                             "importance": -1, "reason": "r"})
        self.assertEqual(hi.importance, 1.0)
        self.assertEqual(lo.importance, 0.0)

    def test_non_numeric_importance_falls_back(self):
        op = judge.Op.parse({"op": "ADD", "text": "x", "type": "fact",
                            "importance": "very", "reason": "r"})
        self.assertEqual(op.importance, 0.6)

    def test_scope_defaults_to_user(self):
        op = judge.Op.parse({"op": "ADD", "text": "x", "type": "fact",
                            "scope": None, "reason": "r"})
        self.assertEqual(op.scope, "user")

    def test_out_of_vocabulary_scope_falls_back_to_user(self):
        # An unrecognised scope satisfies no branch of the read path's filter, so
        # the fact would be written to both stores and never be retrievable.
        # 'user' is the one scope that is always readable.
        for bogus in ("global", "session", "PROJECT", "", 7):
            op = judge.Op.parse({"op": "ADD", "text": "x", "type": "fact",
                                 "scope": bogus, "reason": "r"})
            self.assertEqual(op.scope, "user", repr(bogus))

    def test_every_valid_scope_survives_parse(self):
        for scope in providers.SCOPES:
            op = judge.Op.parse({"op": "ADD", "text": "x", "type": "fact",
                                 "scope": scope, "reason": "r"})
            self.assertEqual(op.scope, scope)


class TestTravelTest(unittest.TestCase):
    """The v6 scope correction.

    Measured under v4: 41 of 62 facts came back scope=project and roughly 17 of
    those were personal preferences bound to a repository only by their wording,
    leaving 34% of the store reachable without naming a project. v6 makes the model
    answer "would this sentence still be true in another project?" and the mapping
    to `scope` lives in code, so the repository name has nowhere to leak into.
    """

    def _parse(self, **extra):
        raw = {"op": "ADD", "text": "Prefers modal editors", "type": "preference",
               "reason": "r"}
        raw.update(extra)
        return judge.Op.parse(raw)

    def test_project_is_promoted_when_the_fact_travels(self):
        op = self._parse(scope="project", holds_in_other_repos=True)
        self.assertEqual(op.scope, "user")
        self.assertIs(op.holds_in_other_repos, True)

    def test_project_stays_when_the_fact_is_repo_bound(self):
        op = self._parse(scope="project", holds_in_other_repos=False)
        self.assertEqual(op.scope, "project")

    def test_user_is_never_demoted(self):
        # One-directional by design: the correction must not be able to regress the
        # direction that was measured.
        for answer in (True, False, None):
            op = self._parse(scope="user", holds_in_other_repos=answer)
            self.assertEqual(op.scope, "user", repr(answer))

    def test_task_scope_is_left_alone(self):
        for answer in (True, False, None):
            op = self._parse(scope="task", type="task", holds_in_other_repos=answer)
            self.assertEqual(op.scope, "task", repr(answer))

    def test_versions_that_do_not_ask_are_unaffected(self):
        # v2..v5 never mention the field, so the model returns null and the fact is
        # scoped exactly as it was before the schema grew. This is what keeps older
        # versions comparable on the same eval.
        for absent in ({}, {"holds_in_other_repos": None}):
            op = self._parse(scope="project", **absent)
            self.assertEqual(op.scope, "project")
            self.assertIsNone(op.holds_in_other_repos)

    def test_non_boolean_answers_are_discarded(self):
        for junk in ("true", "yes", 1, 0, [], "maybe"):
            op = self._parse(scope="project", holds_in_other_repos=junk)
            self.assertEqual(op.scope, "project", repr(junk))
            self.assertIsNone(op.holds_in_other_repos, repr(junk))


class TestToolSchema(unittest.TestCase):
    def test_strict_mode_requirements(self):
        # docs/04-judge.md claims tool use alone guarantees well-formed JSON.
        # That is only true in strict mode, which also requires
        # additionalProperties: false and every property in required.
        self.assertTrue(providers.anthropic_tool()["strict"])
        schema = providers.anthropic_tool()["input_schema"]
        self.assertFalse(schema["additionalProperties"])
        item = schema["properties"]["operations"]["items"]
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(set(item["required"]), set(item["properties"]))

    def test_gemini_schema_mirrors_the_anthropic_one(self):
        # Same operation fields on both providers, so Op.parse and every
        # downstream test stay provider-neutral.
        a = providers.anthropic_tool()["input_schema"]["properties"]["operations"]["items"]
        g = providers.gemini_schema()["properties"]["operations"]["items"]
        self.assertEqual(set(a["properties"]), set(g["properties"]))
        self.assertEqual(set(a["required"]), set(g["required"]))
        self.assertFalse(g["additionalProperties"])

    def test_gemini_optional_enums_are_constrained_and_nullable(self):
        # Optional fields stay nullable, but their values are constrained by enum
        # rather than by prose. Description-only was the earlier choice, on the
        # reasoning that Op.parse is the real gate -- but it let the model return
        # any string for scope, and a scope outside the vocabulary produces a fact
        # no read-path filter can match. Both layers now enforce it.
        g = providers.gemini_schema()["properties"]["operations"]["items"]["properties"]
        for field, allowed in (
            ("type", providers.MEMORY_TYPES),
            ("scope", providers.SCOPES),
            ("task_status", ["unknown", "todo", "doing", "done"]),
        ):
            self.assertEqual(g[field]["enum"], [*allowed, None], field)
            self.assertEqual(g[field]["type"], ["string", "null"], field)
        self.assertIn("preference", g["type"]["description"])
        self.assertEqual(g["op"]["enum"], ["ADD", "UPDATE", "DELETE"])

    def test_gemini_value_vocabularies_match_anthropic(self):
        # A scope allowed by one provider and not the other would make the same
        # window yield different facts depending on which judge ran it.
        a = providers.anthropic_tool()["input_schema"]["properties"]["operations"]["items"]["properties"]
        g = providers.gemini_schema()["properties"]["operations"]["items"]["properties"]
        for field in ("op", "type", "scope", "task_status"):
            self.assertEqual(set(a[field]["enum"]), set(g[field]["enum"]), field)

    def test_missing_credentials_becomes_an_error_not_an_exception(self):
        self.assertIn("GEMINI_API_KEY",
                      providers.call(model="gemini-3.5-flash-lite",
                                     prompt="x").error)
        self.assertIn("ANTHROPIC_API_KEY",
                      providers.call(model="claude-sonnet-5",
                                     prompt="x", anthropic_api_key="").error)

    def test_gemini_api_key_does_not_force_vertex(self):
        response = MagicMock()
        response.text = '{"operations": []}'
        response.usage_metadata.prompt_token_count = 4
        response.usage_metadata.candidates_token_count = 3
        response.usage_metadata.thoughts_token_count = 0

        with patch("google.genai.Client") as client_cls:
            client_cls.return_value.models.generate_content.return_value = response
            result = providers.call_vertex(
                model="gemini-3.5-flash-lite", prompt="x", api_key="test-key"
            )

        client_cls.assert_called_once_with(api_key="test-key")
        self.assertIsNone(result.error)

    def test_vertex_project_still_selects_vertex(self):
        response = MagicMock()
        response.text = '{"operations": []}'
        response.usage_metadata.prompt_token_count = 4
        response.usage_metadata.candidates_token_count = 3
        response.usage_metadata.thoughts_token_count = 0

        with patch("google.genai.Client") as client_cls:
            client_cls.return_value.models.generate_content.return_value = response
            providers.call_vertex(
                model="gemini-3.5-flash-lite", prompt="x", api_key="",
                project="project-1", location="global",
            )

        client_cls.assert_called_once_with(
            vertexai=True, project="project-1", location="global", api_key=None
        )

    def _production_prompt(self, **context: object) -> str:
        """Exactly what production sends, through the one real prompt path.

        Asserted against `build_prompt` rather than a module-level literal on
        purpose: a literal is what let production and the eval diverge.
        """
        return judge.build_prompt(
            window=[{"id": 1, "role": "user", "content": "i prefer pnpm"}],
            candidates=[],
            **context,
        )

    def test_credentials_rule_present(self):
        # Folded in from docs/07-hermes-adapter.md: the judge is a cloud API, so
        # this belongs in the prompt, not only in the adapter that feeds it.
        self.assertIn("Never store credentials", self._production_prompt())

    def test_assistant_content_rule_present(self):
        self.assertIn(
            "Do NOT store what the\n   assistant did", self._production_prompt()
        )

    def test_prompt_bounds_fact_length(self):
        # v1 produced a 2161-char "fact" — an entire session changelog. The cap
        # is the single most important thing the prompt has to enforce.
        prompt = self._production_prompt()
        self.assertIn("UNDER 200 CHARACTERS", prompt)
        self.assertIn("changelog is not a memory", prompt)

    def test_prompt_asks_for_all_three_scopes(self):
        # Project and task facts are wanted by design — the v1 problem was that
        # *only* project facts appeared, not that they appeared at all.
        prompt = self._production_prompt()
        for scope in ("scope=user", "scope=project", "scope=task"):
            self.assertIn(scope, prompt)

    def test_prompt_anchors_full_importance_range(self):
        prompt = self._production_prompt()
        for band in ("0.9-1.0", "0.7-0.8", "0.4-0.6", "0.1-0.3"):
            self.assertIn(band, prompt)

    def test_production_prompt_is_the_active_registry_version(self):
        """The defect this test exists to catch.

        judge.py held its own copy of v2 while stamping every fact "v4", so the
        version column lied and every number in docs/08 measured a prompt
        production never ran. The five assertions above did not catch it, because
        v2 satisfies all of them. What separates the versions is the blocks v4
        added, so those are what get pinned here.
        """
        self.assertEqual(judge.PROMPT_VERSION, prompts.DEFAULT_VERSION)
        prompt = self._production_prompt()
        for marker in (
            "WHERE THIS CONVERSATION HAPPENED",
            "WHAT TO LOOK FOR",
            "WHAT IS NOT A MEMORY",
            "Identity and contact details are never below 0.7",
        ):
            self.assertIn(marker, prompt)

    def test_the_travel_question_is_asked_by_the_schema(self):
        """Asked in the schema, deliberately not in the prompt text.

        Spelling the question out as a prompt rule cost 3-5x recall on real
        windows (0.10-0.20 facts per window against v4's 0.35-0.60): an extra
        mandatory judgement per fact made the model bail on marginal ones. The
        schema field carries the same question, and the model answers it there
        without the emission path acquiring a new gate.
        """
        for schema in (
            providers.anthropic_tool()["input_schema"]["properties"]["operations"],
            providers.gemini_schema()["properties"]["operations"],
        ):
            field = schema["items"]["properties"]["holds_in_other_repos"]
            self.assertIn("switched to a different project", field["description"])
            self.assertIn("null", field["type"])
        self.assertNotIn("holds_in_other_repos", self._production_prompt())

    def test_active_version_stops_binding_personal_facts_to_a_repo(self):
        """The actual root cause of the scope drift.

        v4 rule 2 said "never write 'this project' -- name the project", which
        made the model write "For frontend-second, prefers modal editors". Every
        decision downstream then correctly followed that phrasing: asked whether
        the sentence holds elsewhere, the model said no, because the sentence it
        wrote names the repository. Rule 2 was fighting rule 5.
        """
        prompt = self._production_prompt()
        self.assertIn("ONLY when the fact is about that repository", prompt)
        self.assertIn("do NOT mention the repository at all", prompt)

    def test_active_version_no_longer_dictates_fact_language(self):
        # Dropped in v6: measured at ~70% non-compliance (20% of input Russian
        # against 6% of facts) and it buys nothing, since a Russian query reaches
        # the matching English fact at rank 1.
        self.assertNotIn(
            "same language the user used", self._production_prompt()
        )

    def test_prompt_carries_session_context_not_only_today(self):
        """Relative dates resolve against the conversation, not the run.

        The corpus spans ten months, so rendering "last month" against today
        misdates every backfilled window. judge.extract accepted session_date,
        scope_key and agent_id and dropped all three on the floor.
        """
        prompt = self._production_prompt(
            session_date="2026-03-14", scope_key="memkit", agent_id="claude-code"
        )
        self.assertIn("2026-03-14", prompt)
        self.assertIn("memkit", prompt)
        self.assertIn("claude-code", prompt)


class TestWindowRendering(unittest.TestCase):
    def test_assistant_turns_are_truncated(self):
        long_log = "I edited 40 files. " * 200
        rendered = judge.render_window(
            [{"id": 1, "role": "assistant", "content": long_log}]
        )
        self.assertLess(len(rendered), 400)
        self.assertIn("truncated", rendered)

    def test_user_turns_are_never_truncated(self):
        # The user's own words are the source material; clipping them would
        # discard exactly what we are trying to extract.
        long_ask = "I really prefer pnpm because " * 100
        rendered = judge.render_window(
            [{"id": 1, "role": "user", "content": long_ask}]
        )
        self.assertIn(long_ask.strip()[:200], rendered)
        self.assertNotIn("truncated", rendered)

    def test_short_assistant_turn_left_alone(self):
        rendered = judge.render_window(
            [{"id": 1, "role": "assistant", "content": "Done."}]
        )
        self.assertNotIn("truncated", rendered)
        self.assertIn("Done.", rendered)


class TestModelRegistry(unittest.TestCase):
    def test_default_is_the_cheapest_known_model(self):
        cheapest = min(judge.MODELS, key=lambda m: judge.MODELS[m]["price"][0])
        self.assertEqual(judge.DEFAULT_MODEL, cheapest)

    def test_provider_routing(self):
        self.assertEqual(providers.provider_of("gemini-3.5-flash-lite"), "gemini")
        self.assertEqual(providers.provider_of("claude-sonnet-5"), "anthropic")
        with self.assertRaises(ValueError):
            providers.provider_of("llama-9")

    def test_gemini_is_the_cheapest_and_the_default(self):
        # Flash-Lite is both cheapest and recommended by Google for JSON
        # extraction.
        self.assertEqual(judge.DEFAULT_MODEL, "gemini-3.5-flash-lite")
        g = judge.cost_of(1300, 200, model="gemini-3.5-flash-lite")
        for other in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"):
            self.assertLess(g, judge.cost_of(1300, 200, model=other))

    def test_flash_lite_output_is_far_dearer_than_input(self):
        # $0.30 in against $2.50 out, and reasoning bills as output — which is
        # why the prompt caps fact length and thinking is MINIMAL.
        p_in, p_out = judge.price_per_mtok("gemini-3.5-flash-lite")
        self.assertGreater(p_out / p_in, 8)

    def test_haiku_is_half_the_price_of_sonnet(self):
        h = judge.cost_of(1200, 150, model="claude-haiku-4-5")
        s_ = judge.cost_of(1200, 150, model="claude-sonnet-5", when=date(2026, 7, 28))
        self.assertAlmostEqual(h * 2, s_, places=9)

    def test_unknown_model_priced_at_the_most_expensive(self):
        # An unrecognised id must never quietly under-report against the ceiling.
        unknown = judge.price_per_mtok("some-new-model")
        self.assertEqual(unknown, max(m["price"] for m in judge.MODELS.values()))


class TestGate(unittest.TestCase):
    def test_counter(self):
        self.assertFalse(judge.should_extract(messages_since_last=9, session_closed=False))
        self.assertTrue(judge.should_extract(messages_since_last=10, session_closed=False))

    def test_session_close_forces(self):
        self.assertTrue(judge.should_extract(messages_since_last=1, session_closed=True))

    def test_remember_stems(self):
        for text in ("запомни это", "запомнить надо", "не забудь про pnpm",
                     "remember that I use Vue", "don't forget the token",
                     "keep in mind I prefer tabs"):
            self.assertTrue(
                judge.should_extract(messages_since_last=1, session_closed=False, text=text),
                text,
            )

    def test_ordinary_text_does_not_trigger(self):
        for text in ("fix the bug", "почини это", "run the tests"):
            self.assertFalse(
                judge.should_extract(messages_since_last=1, session_closed=False, text=text),
                text,
            )


class TestPricing(unittest.TestCase):
    def test_sonnet_intro_then_standard(self):
        m = "claude-sonnet-5"
        self.assertEqual(judge.price_per_mtok(m, date(2026, 8, 31)), (2.0, 10.0))
        self.assertEqual(judge.price_per_mtok(m, date(2026, 9, 1)), (3.0, 15.0))

    def test_flat_priced_model_ignores_the_intro_date(self):
        for when in (date(2026, 8, 31), date(2027, 1, 1)):
            self.assertEqual(
                judge.price_per_mtok("claude-haiku-4-5", when), (1.0, 5.0)
            )

    def test_cost_math_sonnet_intro(self):
        self.assertAlmostEqual(
            judge.cost_of(1200, 150, date(2026, 7, 28), model="claude-sonnet-5"),
            1200 * 2 / 1e6 + 150 * 10 / 1e6, places=9,
        )

    def test_cost_math_default_is_flash_lite(self):
        self.assertAlmostEqual(
            judge.cost_of(1200, 150),
            1200 * 0.30 / 1e6 + 150 * 2.50 / 1e6, places=9,
        )


# --------------------------------------------------------------------------
# The apply path: what actually lands in SQLite and Qdrant.
# --------------------------------------------------------------------------
class TestApplyOps(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        self.q = StubQdrant()
        self.msg_ids = add_messages(self.conn)

    def test_add_writes_memory_sources_and_point(self):
        op = judge.Op(op="ADD", reason="r", text="Prefers pnpm over npm",
                      type="preference", scope="user", importance=0.8, confidence=0.9)
        run_id = make_judge_run(self.conn)
        out = apply(self.conn, self.q, [op], judge_run_id=run_id,
                    source_message_ids=self.msg_ids)
        self.assertEqual(out.added, 1)

        row = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertEqual(row["text"], "Prefers pnpm over npm")
        self.assertEqual(row["status"], "active")
        # correction #5: the memory -> judge_run link exists, and the FK means
        # it can only point at a run that really happened.
        self.assertEqual(row["judge_run_id"], run_id)
        self.assertEqual(row["extraction_version"], judge.PROMPT_VERSION)

        n = self.conn.execute(
            "SELECT COUNT(*) n FROM memory_sources WHERE memory_id = ?", (row["id"],)
        ).fetchone()["n"]
        self.assertEqual(n, len(self.msg_ids))
        self.assertIn(row["id"], self.q.points)

    def test_add_project_scope_carries_scope_key(self):
        op = judge.Op(op="ADD", reason="r", text="Auth lives in auth/",
                      type="project", scope="project", importance=0.7, confidence=0.9)
        apply(self.conn, self.q, [op], scope_key="memkit")
        row = self.conn.execute("SELECT scope, scope_key FROM memories").fetchone()
        self.assertEqual((row["scope"], row["scope_key"]), ("project", "memkit"))

    def test_task_scope_does_not_inherit_the_project_key(self):
        # Only scope='project' is keyed by the session's project. A task fact
        # keyed with a project name matches nothing on the read path — that key is
        # compared against the current *task*, so the fact became write-only.
        op = judge.Op(op="ADD", reason="r", text="Fix the flaky auth test",
                      type="task", scope="task", importance=0.4, confidence=0.9)
        apply(self.conn, self.q, [op], scope_key="memkit")
        row = self.conn.execute("SELECT id, scope, scope_key FROM memories").fetchone()
        self.assertEqual((row["scope"], row["scope_key"]), ("task", None))
        self.assertIsNone(self.q.points[row["id"]]["scope_key"])
        # ...and the read path now admits it.
        self.assertEqual(
            retrieval.scope_boost("task", row["scope_key"], project=None, task=None),
            1.0,
        )

    def test_task_add_and_update_write_workflow_status_to_board_and_vector(self):
        add = judge.Op(
            op="ADD",
            reason="started",
            text="Ship the release",
            type="task",
            scope="project",
            importance=0.6,
            confidence=0.9,
            task_status="doing",
        )
        apply(self.conn, self.q, [add], scope_key="memkit")
        memory = self.conn.execute("SELECT * FROM memories").fetchone()
        board = self.conn.execute(
            "SELECT * FROM task_board WHERE memory_id=?", (memory["id"],)
        ).fetchone()
        self.assertEqual((board["workflow_status"], board["project_key"]), ("doing", "memkit"))
        self.assertEqual(self.q.points[memory["id"]]["task_status"], "doing")

        update = judge.Op(
            op="UPDATE",
            id=memory["id"],
            reason="finished",
            text="Ship the release",
            type="task",
            task_status="done",
        )
        apply(self.conn, self.q, [update], scope_key="memkit")
        self.assertEqual(
            self.conn.execute(
                "SELECT workflow_status FROM task_board WHERE memory_id=?",
                (memory["id"],),
            ).fetchone()["workflow_status"],
            "done",
        )
        self.assertEqual(self.q.points[memory["id"]]["task_status"], "done")

    def test_user_scope_never_gets_scope_key(self):
        # A user-scope fact must not be pinned to whatever project happened to
        # be open, or stage-3 scope filtering will hide it everywhere else.
        op = judge.Op(op="ADD", reason="r", text="Lives in Tashkent",
                      type="fact", scope="user", importance=0.9, confidence=0.9)
        apply(self.conn, self.q, [op], scope_key="memkit")
        row = self.conn.execute("SELECT scope_key FROM memories").fetchone()
        self.assertIsNone(row["scope_key"])

    def test_update_modifies_in_place_and_refreshes_updated_at(self):
        add = judge.Op(op="ADD", reason="r", text="Uses React",
                       type="preference", scope="user", importance=0.7, confidence=0.9)
        apply(self.conn, self.q, [add])
        before = self.conn.execute("SELECT * FROM memories").fetchone()
        self.conn.execute(
            "UPDATE memories SET updated_at = '2020-01-01T00:00:00Z' WHERE id = ?",
            (before["id"],),
        )

        upd = judge.Op(op="UPDATE", reason="switched", id=before["id"],
                       text="Moved from React to Vue (June 2026)",
                       type="preference", importance=0.85, confidence=0.95)
        run_id = make_judge_run(self.conn)
        out = apply(self.conn, self.q, [upd], judge_run_id=run_id)
        self.assertEqual((out.updated, out.added), (1, 0))

        after = self.conn.execute("SELECT * FROM memories").fetchone()
        self.assertEqual(after["text"], "Moved from React to Vue (June 2026)")
        self.assertEqual(after["importance"], 0.85)
        self.assertEqual(after["judge_run_id"], run_id)
        # docs/05-retrieval.md ages facts from updated_at, so a fact confirmed
        # today must read as fresh even though it was created long ago.
        self.assertGreater(after["updated_at"], "2020-01-01T00:00:00Z")
        self.assertEqual(after["created_at"], before["created_at"])
        # Exactly one row: UPDATE must not fork a duplicate.
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM memories").fetchone()["n"], 1
        )

    def test_update_with_hallucinated_id_is_skipped(self):
        op = judge.Op(op="UPDATE", reason="r", id="does-not-exist", text="ghost")
        out = apply(self.conn, self.q, [op])
        self.assertEqual((out.updated, out.skipped, out.added), (0, 1, 0))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM memories").fetchone()["n"], 0
        )

    def test_delete_is_soft_and_removes_point(self):
        add = judge.Op(op="ADD", reason="r", text="Temporary task",
                       type="task", scope="user", importance=0.3, confidence=0.8)
        apply(self.conn, self.q, [add])
        mem_id = self.conn.execute("SELECT id FROM memories").fetchone()["id"]

        out = apply(self.conn, self.q, [judge.Op(op="DELETE", reason="done", id=mem_id)])
        self.assertEqual(out.deleted, 1)

        row = self.conn.execute("SELECT status FROM memories WHERE id = ?",
                                (mem_id,)).fetchone()
        self.assertEqual(row["status"], "expired")   # row kept, never hard-deleted
        self.assertIn(mem_id, self.q.deleted)
        self.assertNotIn(mem_id, self.q.points)

    def test_delete_twice_is_skipped_not_double_counted(self):
        add = judge.Op(op="ADD", reason="r", text="x", type="task",
                       scope="user", importance=0.3, confidence=0.8)
        apply(self.conn, self.q, [add])
        mem_id = self.conn.execute("SELECT id FROM memories").fetchone()["id"]
        apply(self.conn, self.q, [judge.Op(op="DELETE", reason="d", id=mem_id)])
        out = apply(self.conn, self.q, [judge.Op(op="DELETE", reason="d", id=mem_id)])
        self.assertEqual((out.deleted, out.skipped), (0, 1))

    def test_expired_memory_excluded_from_reindex_source(self):
        # correction #3: reindex must load status='active' only, or every fact
        # ever deleted comes back on the next rebuild.
        for text, keep in (("keep me", True), ("drop me", False)):
            apply(self.conn, self.q, [judge.Op(
                op="ADD", reason="r", text=text, type="fact",
                scope="user", importance=0.5, confidence=0.9)])
        drop = self.conn.execute(
            "SELECT id FROM memories WHERE text = 'drop me'"
        ).fetchone()["id"]
        apply(self.conn, self.q, [judge.Op(op="DELETE", reason="d", id=drop)])

        active = self.conn.execute(
            "SELECT text FROM memories WHERE status = 'active'"
        ).fetchall()
        self.assertEqual([r["text"] for r in active], ["keep me"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM memories").fetchone()["n"], 2
        )

    def test_mixed_batch_counts_each_kind(self):
        apply(self.conn, self.q, [judge.Op(
            op="ADD", reason="r", text="first", type="fact",
            scope="user", importance=0.5, confidence=0.9)])
        existing = self.conn.execute("SELECT id FROM memories").fetchone()["id"]
        out = apply(self.conn, self.q, [
            judge.Op(op="ADD", reason="r", text="second", type="fact",
                     scope="user", importance=0.5, confidence=0.9),
            judge.Op(op="UPDATE", reason="r", id=existing, text="first, refined"),
            judge.Op(op="DELETE", reason="r", id="ghost"),
        ])
        self.assertEqual((out.added, out.updated, out.deleted, out.skipped),
                         (1, 1, 0, 1))
        self.assertEqual(out.applied, 2)


class TestCostCeiling(unittest.TestCase):
    def test_extraction_refuses_once_month_spend_exceeds_limit(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO judge_runs
               (kind, model, prompt_version, input_json, cost_usd, created_at)
               VALUES ('extract', 'm', 'v1', '{}', 20.0, strftime('%Y-%m-%dT%H:%M:%SZ','now'))"""
        )
        conn.commit()
        self.assertGreater(judge.month_spend_usd(conn), 15.0)

        # No API key needed: the ceiling is checked before the client is built,
        # because one runaway loop can spend a month of budget in an hour.
        result = judge.extract(
            conn, window=[], candidates=[], api_key="unused",
            monthly_limit_usd=15.0,
        )
        self.assertEqual(result.error, "monthly_cost_limit_reached")
        self.assertEqual(result.ops, [])
        self.assertIsNone(result.judge_run_id)

    def test_spend_below_limit_does_not_block(self):
        conn = make_db()
        conn.execute(
            """INSERT INTO judge_runs
               (kind, model, prompt_version, input_json, cost_usd, created_at)
               VALUES ('extract','m','v1','{}', 1.5, strftime('%Y-%m-%dT%H:%M:%SZ','now'))"""
        )
        conn.commit()
        self.assertLess(judge.month_spend_usd(conn), 15.0)


class TestWindowAbandonment(unittest.TestCase):
    """A failing window must not be re-bought on every new message.

    A failed call deliberately leaves its messages unprocessed so a transient
    fault gets retried. But the gate fires again on the next message, so a
    *systematic* fault (a revoked key, a schema the model keeps breaking) turned
    into one paid call per incoming message until the monthly ceiling stopped it.
    """

    def setUp(self):
        self.conn = make_db()
        self.ids = add_messages(self.conn)

    def _log_failure(self, message_ids, error="empty_response"):
        self.conn.execute(
            """INSERT INTO judge_runs
               (kind, model, prompt_version, input_json, error, created_at)
               VALUES ('extract', 'm', 'v4', ?, ?, '2026-07-01T00:00:00Z')""",
            (json.dumps({"message_ids": message_ids}), error),
        )
        self.conn.commit()

    def test_attempts_are_counted_per_window_head(self):
        self.assertEqual(extract.failed_attempts(self.conn, self.ids), 0)
        self._log_failure(self.ids)
        self.assertEqual(extract.failed_attempts(self.conn, self.ids), 1)
        # A different window is a different counter.
        self.assertEqual(extract.failed_attempts(self.conn, [999, 1000]), 0)

    def test_successful_runs_do_not_count(self):
        self.conn.execute(
            """INSERT INTO judge_runs
               (kind, model, prompt_version, input_json, error, created_at)
               VALUES ('extract','m','v4', ?, NULL, '2026-07-01T00:00:00Z')""",
            (json.dumps({"message_ids": self.ids}),),
        )
        self.conn.commit()
        self.assertEqual(extract.failed_attempts(self.conn, self.ids), 0)

    def test_window_is_abandoned_without_calling_the_judge(self):
        for _ in range(extract.MAX_WINDOW_ATTEMPTS):
            self._log_failure(self.ids)
        with patch.object(judge, "extract") as judge_extract:
            outcome = extract.run_extraction(
                self.conn, StubQdrant(), StubEmbedder(),
                session_id="s-1", owner_id=OWNER, monthly_limit_usd=15.0,
                force=True,
            )
        judge_extract.assert_not_called()
        self.assertEqual(outcome.abandoned, len(self.ids))
        # Marked processed so the session drains; the messages themselves stay.
        self.assertEqual(extract.messages_since_last(self.conn, "s-1"), 0)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) n FROM messages").fetchone()["n"],
            len(self.ids),
        )

    def test_one_failure_short_of_the_cap_still_calls_the_judge(self):
        for _ in range(extract.MAX_WINDOW_ATTEMPTS - 1):
            self._log_failure(self.ids)
        with patch.object(judge, "extract") as judge_extract:
            judge_extract.return_value = judge.JudgeResult(
                ops=[], judge_run_id=1, input_tokens=0, output_tokens=0,
                cost_usd=0.0, latency_ms=1, error="empty_response",
            )
            outcome = extract.run_extraction(
                self.conn, StubQdrant(), StubEmbedder(),
                session_id="s-1", owner_id=OWNER, monthly_limit_usd=15.0,
                force=True,
            )
        judge_extract.assert_called_once()
        self.assertEqual(outcome.abandoned, 0)
        # The error left the window unprocessed on purpose: still retryable.
        self.assertEqual(extract.messages_since_last(self.conn, "s-1"), len(self.ids))

    def test_budget_refusal_is_retryable_forever(self):
        # judge.extract returns before logging a run when the ceiling is hit, so
        # a budget refusal never accumulates toward the abandonment cap.
        self.conn.execute(
            """INSERT INTO judge_runs
               (kind, model, prompt_version, input_json, cost_usd, created_at)
               VALUES ('extract','m','v4','{}', 20.0,
                       strftime('%Y-%m-%dT%H:%M:%SZ','now'))"""
        )
        self.conn.commit()
        for _ in range(extract.MAX_WINDOW_ATTEMPTS + 2):
            outcome = extract.run_extraction(
                self.conn, StubQdrant(), StubEmbedder(),
                session_id="s-1", owner_id=OWNER, monthly_limit_usd=15.0,
                force=True,
            )
            self.assertEqual(outcome.error, "monthly_cost_limit_reached")
        self.assertEqual(extract.failed_attempts(self.conn, self.ids), 0)
        self.assertEqual(extract.messages_since_last(self.conn, "s-1"), len(self.ids))


class TestWindowAndCandidates(unittest.TestCase):
    def test_window_is_oldest_unprocessed_in_order(self):
        conn = make_db()
        ids = add_messages(conn, n=15)
        window = extract.unprocessed_window(conn, "s-1", limit=10)
        self.assertEqual([r["id"] for r in window], ids[:10])

    def test_processed_messages_excluded(self):
        conn = make_db()
        ids = add_messages(conn, n=12)
        conn.executemany("UPDATE messages SET processed = 1 WHERE id = ?",
                         [(i,) for i in ids[:5]])
        conn.commit()
        window = extract.unprocessed_window(conn, "s-1", limit=10)
        self.assertEqual([r["id"] for r in window], ids[5:12])
        self.assertEqual(extract.messages_since_last(conn, "s-1"), 7)

    def test_window_includes_assistant_turns(self):
        # Assistant text is what lets the judge resolve "it" and "that project".
        # Prompt rule 3 is what stops it becoming a fact about the user.
        conn = make_db()
        add_messages(conn, n=2, role="user")
        add_messages(conn, n=2, role="assistant", content="I suggest Vue because")
        roles = {r["role"] for r in extract.unprocessed_window(conn, "s-1")}
        self.assertEqual(roles, {"user", "assistant"})

    def test_render_window_labels_message_ids(self):
        conn = make_db()
        ids = add_messages(conn, n=2)
        text = judge.render_window(extract.unprocessed_window(conn, "s-1"))
        self.assertIn(f"[{ids[0]}] user:", text)

    def test_candidate_query_uses_user_turns_only(self):
        # The query vector must represent what the user said. Windows here run
        # about nine assistant turns to one user turn, so concatenating everything
        # made it a summary of the work log and returned candidates matching the
        # log instead of the fact.
        window = [
            {"id": 1, "role": "assistant", "content": "I edited 40 files. " * 200},
            {"id": 2, "role": "user", "content": "use pnpm, not npm"},
            {"id": 3, "role": "assistant", "content": "Ran 162 suites, all green."},
        ]
        text = extract.candidate_query_text(window)
        self.assertEqual(text, "use pnpm, not npm")
        self.assertNotIn("edited 40 files", text)
        self.assertNotIn("162 suites", text)

    def test_candidate_query_joins_every_user_turn(self):
        window = [
            {"id": 1, "role": "user", "content": "first thing"},
            {"id": 2, "role": "assistant", "content": "noted"},
            {"id": 3, "role": "user", "content": "second thing"},
        ]
        self.assertEqual(
            extract.candidate_query_text(window), "first thing\nsecond thing"
        )

    def test_candidate_query_falls_back_when_there_is_no_user_turn(self):
        # run_extraction never gets here, but eval/experiment.py can.
        window = [{"id": 1, "role": "assistant", "content": "Done."}]
        self.assertIn("Done.", extract.candidate_query_text(window))

    def test_render_candidates_empty(self):
        self.assertEqual(judge.render_candidates([]), "(none)")

    def test_render_candidates_exposes_ids(self):
        rendered = judge.render_candidates(
            [{"id": "m-1", "text": "Uses React", "type": "preference", "importance": 0.7}]
        )
        # The judge can only emit UPDATE if it can see the candidate's id.
        self.assertIn("id=m-1", rendered)
        self.assertIn("Uses React", rendered)


if __name__ == "__main__":
    unittest.main(verbosity=2)
