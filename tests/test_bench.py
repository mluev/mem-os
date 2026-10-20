"""The LoCoMo/LongMemEval harness, end to end against the real API.

Extraction, answering and judging use fake models, so this proves the
plumbing rather than a score: users are isolated per conversation, turns keep
their recorded dates, queued jobs finish before questions are asked, search
results map back to the dataset's evidence turns, and the report computes
accuracy, evidence recall and MemScore from what was recorded.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from eval.bench import answer, datasets, pipeline, stats
from eval.bench.client import Memkit
from memkit import api, config, job_runner, providers
from tests.fixtures import fake_provider
from tests.httpharness import ApiTestCase

ASSISTANT = stats.ASSISTANT_ONLY

LOCOMO = [
    {
        "sample_id": "conv-1",
        "conversation": {
            "speaker_a": "Caroline",
            "speaker_b": "Melanie",
            "session_1_date_time": "1:56 pm on 8 May, 2023",
            "session_1": [
                {
                    "speaker": "Caroline",
                    "dia_id": "D1:1",
                    "text": "I went to the LGBTQ support group yesterday",
                },
                {"speaker": "Melanie", "dia_id": "D1:2", "text": "That is lovely to hear"},
                {
                    "speaker": "Melanie",
                    "dia_id": "D1:3",
                    "text": "Look at this",
                    "blip_caption": "a painting of a sunset",
                },
            ],
            "session_2_date_time": "10:00 am on 20 May, 2023",
            "session_2": [
                {"speaker": "Melanie", "dia_id": "D2:1", "text": "I painted a lake sunrise"},
            ],
        },
        "qa": [
            {
                "question": "When did Caroline go to the LGBTQ support group?",
                "answer": "7 May 2023",
                "evidence": ["D1:1"],
                "category": 2,
            },
            {"question": "Unanswerable", "evidence": [], "category": 5},
        ],
    }
]

LONGMEMEVAL = [
    {
        "question_id": "q1_abs",
        "question_type": "single-session-user",
        "question": "What is my cat's name?",
        "answer": "not mentioned",
        "question_date": "2023/05/30 (Tue) 23:40",
        "haystack_session_ids": ["a", "b"],
        "haystack_dates": ["2023/05/01 (Mon) 10:00", "2023/05/02 (Tue) 11:00"],
        "haystack_sessions": [
            [{"role": "user", "content": "I have a dog"}, {"role": "assistant", "content": "Nice"}],
            [{"role": "user", "content": "   "}],
        ],
        "answer_session_ids": ["a"],
    }
]


def test_locomo_loads_speakers_dates_photos_and_categories(tmp_path: Path) -> None:
    path = tmp_path / "locomo.json"
    path.write_text(json.dumps(LOCOMO))
    [conversation] = datasets.load_locomo(path)
    first = conversation.sessions[0]
    assert first.date == datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
    # Both speakers are people: user turns, named in the text.
    assert [t.role for t in first.turns] == ["user", "user", "user"]
    assert first.turns[1].text == "Melanie: That is lovely to hear"
    assert "a painting of a sunset" in first.turns[2].text
    [question] = conversation.questions  # the adversarial one is excluded
    assert (question.category, question.evidence_sessions) == ("temporal", ["conv-1-s1"])
    assert question.question_date == datetime(2023, 5, 20, 10, 0, tzinfo=UTC)
    assert len(datasets.load_locomo(path, include_adversarial=True)[0].questions) == 2


def test_longmemeval_keeps_roles_dates_and_abstention(tmp_path: Path) -> None:
    path = tmp_path / "lme.json"
    path.write_text(json.dumps(LONGMEMEVAL))
    [conversation] = datasets.load_longmemeval(path)
    assert [t.role for t in conversation.sessions[0].turns] == ["user", "assistant"]
    assert conversation.sessions[1].turns == []
    [question] = conversation.questions
    assert question.abstention and question.evidence_sessions == ["q1_abs-a"]
    assert question.question_date == datetime(2023, 5, 30, 23, 40, tzinfo=UTC)


def test_answer_context_carries_dates_history_and_sources() -> None:
    context = answer.render_context(
        {
            "memories": [
                {
                    "text": "Caroline lives in Boston",
                    "document_date": "2023-06-01T00:00:00Z",
                    "event_dates": ["2023-05"],
                    "history": [
                        {"text": "Caroline lives in Sweden", "valid_until": "2023-06-01T00:00:00Z"}
                    ],
                    "related": [{"text": "Caroline rents", "relation": "extended_by"}],
                    "sources": [
                        {
                            "created_at": "2023-06-01T00:00:00Z",
                            "excerpt": "moved",
                            "context": "I moved to Boston",
                        }
                    ],
                }
            ],
            "raw": [{"created_at": "2023-05-02T00:00:00Z", "text": "raw words"}],
        }
    )
    for fragment in (
        "said 2023-06-01; happened 2023-05",
        "previously until 2023-06-01: Caroline lives in Sweden",
        "extended by: Caroline rents",
        "source (2023-06-01): I moved to Boston",
        "[passage 2023-05-02] raw words",
    ):
        assert fragment in context


def test_judge_prompts_follow_the_question_type() -> None:
    base = datasets.Question("q", "c", "How many days?", "18 days", "temporal-reasoning", None)
    assert "off-by-one" in answer.judge_prompt(base, "19 days")
    update = datasets.Question("q", "c", "Where?", "Boston", "knowledge-update", None)
    assert "updated answer" in answer.judge_prompt(update, "Boston")
    abstain = datasets.Question(
        "q", "c", "Cat?", "n/a", "single-session-user", None, abstention=True
    )
    assert "abstains" in answer.judge_prompt(abstain, "I don't know")


def _questions(categories: dict[str, int]) -> list[datasets.Conversation]:
    conversations = []
    for category, count in categories.items():
        for n in range(count):
            qid = f"{category}-{n}"
            conversations.append(
                datasets.Conversation(
                    qid, [], [datasets.Question(qid, qid, "?", "!", category, None)]
                )
            )
    return conversations


def test_sampling_is_stratified_deterministic_and_stable_under_additions() -> None:
    first = _questions({"temporal": 10, "multi-hop": 3, ASSISTANT: 8})
    stats.sample(first, stats.parse_sample(f"*=4,{ASSISTANT}=2"), seed=1)
    kept = sorted(q.question_id for c in first for q in c.questions)
    assert stats.category_counts(first) == {"temporal": 4, "multi-hop": 3, ASSISTANT: 2}
    again = _questions({"temporal": 10, "multi-hop": 3, ASSISTANT: 8, "knowledge-update": 5})
    stats.sample(again, stats.parse_sample(f"*=4,{ASSISTANT}=2"), seed=1)
    # A new category does not reshuffle the old ones.
    assert {q.question_id for c in again for q in c.questions} >= set(kept)
    other = _questions({"temporal": 10, "multi-hop": 3, ASSISTANT: 8})
    stats.sample(other, stats.parse_sample(f"*=4,{ASSISTANT}=2"), seed=2)
    assert sorted(q.question_id for c in other for q in c.questions) != kept


def test_a_bad_sample_spec_is_refused() -> None:
    for spec in ("temporal", "=4", "temporal=x"):
        try:
            stats.parse_sample(spec)
        except ValueError:
            continue
        raise AssertionError(f"accepted {spec!r}")


def test_weighted_accuracy_reweights_a_sample_to_the_dataset_mix() -> None:
    by_category = {"temporal": [True, True], "multi-hop": [False, False], "adversarial": [True]}
    shares = {"temporal": 30, "multi-hop": 10, "adversarial": 50}
    assert stats.weighted_accuracy(by_category, shares, exclude={"adversarial"}) == 75.0


def test_compare_pairs_questions_and_reports_interval_and_mcnemar() -> None:
    def runs(pattern: str) -> dict[str, dict]:
        return {
            f"q{i}": {"category": "temporal", "correct": mark == "1"}
            for i, mark in enumerate(pattern)
        }

    baseline = runs("0" * 20 + "1" * 20)
    candidate = runs("1" * 15 + "0" * 5 + "1" * 20)
    candidate["only-here"] = {"category": "temporal", "correct": True}
    result = stats.compare(baseline, candidate, resamples=500)
    overall = result["overall"]
    assert (overall["n"], overall["gained"], overall["lost"]) == (40, 15, 0)
    assert overall["delta"] == 37.5
    assert overall["ci95"][0] > 0
    assert overall["mcnemar_p"] < 0.001
    same = stats.compare(baseline, baseline, resamples=200)["overall"]
    assert (same["delta"], same["mcnemar_p"], same["ci95"]) == (0.0, 1.0, [0.0, 0.0])


def test_the_headline_leaves_out_adversarial_and_reports_assistant_separately() -> None:
    run = pipeline.Run(
        "r",
        Path("/nonexistent"),
        {
            "conversations": {},
            "questions": {
                "a": _judged("temporal", True),
                "b": _judged("adversarial", False),
                "c": _judged(ASSISTANT, False),
                "d": _judged(ASSISTANT, True),
            },
            "config": {"category_counts": {"temporal": 1, ASSISTANT: 1}},
        },
    )
    summary = pipeline.report(run)
    assert summary["questions"] == 3
    assert summary["accuracy"] == round(200 / 3, 2)
    assert summary["accuracy_excluding_assistant"] == 100.0
    assert summary["weighted_accuracy"] == 75.0
    assert summary["by_category"]["adversarial"] == {"n": 1, "accuracy": 0.0}


def _judged(category: str, correct: bool) -> dict:
    return {
        "category": category,
        "correct": correct,
        "latency_ms": 10.0,
        "context_tokens": 100,
        "evidence_turn_recall": None,
        "evidence_session_hit": None,
    }


def test_longmemeval_keeps_assistant_questions_unless_told_not_to(tmp_path: Path) -> None:
    path = tmp_path / "lme.json"
    path.write_text(json.dumps([{**LONGMEMEVAL[0], "question_type": ASSISTANT}]))
    assert len(datasets.load_longmemeval(path)) == 1
    assert datasets.load_longmemeval(path, include_assistant=False) == []


def test_render_context_marks_assistant_passages() -> None:
    context = answer.render_context(
        {
            "raw": [
                {
                    "created_at": "2023-05-02T00:00:00Z",
                    "text": "Try Lisboa Plaza",
                    "source_role": "assistant",
                },
                {
                    "created_at": "2023-05-02T00:00:00Z",
                    "text": "I booked it",
                    "source_role": "user",
                },
            ]
        }
    )
    assert "[passage 2023-05-02 assistant] Try Lisboa Plaza" in context
    assert "[passage 2023-05-02] I booked it" in context


class BenchEndToEndTest(ApiTestCase):
    def fake_models(self, **kwargs):
        schema = kwargs.get("schema_name")
        if schema == "emit_answer":
            return providers.ProviderResult(
                raw={"reasoning": "from memory 1", "answer": "7 May 2023"}
            )
        if schema == "emit_verdict":
            correct = "7 May 2023" in kwargs["prompt"]
            return providers.ProviderResult(raw={"correct": correct, "explanation": ""})
        if schema == "emit_dream":
            return providers.ProviderResult(raw={"links": [], "inferences": []})
        # The extractor: one dated episode per Caroline turn, quoting it whole.
        window = kwargs["prompt"].split("CONVERSATION WINDOW", 1)[1]
        operations = []
        for message_id, text in re.findall(r"^\[(\d+)\] user: (Caroline: .+)$", window, re.M):
            operations.append(
                {
                    "op": "ADD",
                    "text": "Caroline went to the LGBTQ support group on 2023-05-07",
                    "kind": "episode",
                    "reason": "stated",
                    "event_dates": ["2023-05-07"],
                    "evidence": [
                        {
                            "message_id": int(message_id),
                            "start_char": 0,
                            "end_char": 0,
                            "quote": text,
                        }
                    ],
                }
            )
        return providers.ProviderResult(operations=operations, raw={"operations": operations})

    def run_queued_jobs(self) -> None:
        for row in self.db.execute(
            "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at"
        ).fetchall():
            job_runner.run(api.app, str(row["id"]))

    def test_a_run_ingests_extracts_searches_answers_judges_and_reports(self) -> None:
        settings = config.get_settings()
        self.enterContext(patch.object(settings, "judge_model", "fake-judge"))
        for target in ("memkit.routers.evidence", "memkit.job_runner"):
            self.enterContext(patch(f"{target}.judge_configured", return_value=True))
        self.enterContext(fake_provider(self.fake_models))
        path = Path(self.enterContext(self._tmp())) / "locomo.json"
        path.write_text(json.dumps(LOCOMO))
        conversations = datasets.load_locomo(path)
        run = pipeline.Run.open("t1", Path(path.parent) / "runs")
        memkit = Memkit(
            self.client,
            admin_key=self.alice_key,
            run_id="t1",
            on_wait=self.run_queued_jobs,
            index_grace=0,
        )
        config_ = pipeline.Config(
            dataset="locomo", answer_model="fake-answer", judge_model="fake-judge", workers=1
        )
        pipeline.ingest(run, memkit, conversations, lambda _: None)

        entry = run.state["conversations"]["conv-1"]
        user = self.db.execute(
            "SELECT u.id FROM users u WHERE u.handle = 'bench-t1-conv-1'"
        ).fetchone()
        assert user is not None
        dated = self.db.execute(
            "SELECT min(created_at) AS first FROM messages WHERE user_id=%s", (user["id"],)
        ).fetchone()["first"]
        assert dated == datetime(2023, 5, 8, 13, 56, tzinfo=UTC)
        assert entry["extracted"] and entry["jobs"]
        memory = self.db.execute(
            "SELECT kind,event_dates,document_date FROM memories WHERE author_id=%s",
            (user["id"],),
        ).fetchone()
        assert memory["kind"] == "episode" and memory["event_dates"] == ["2023-05-07"]
        assert memory["document_date"] == datetime(2023, 5, 8, 13, 56, tzinfo=UTC)

        # Searches stay in the conversation's own scope, and nothing leaked.
        own = self.db.execute(
            "SELECT slug FROM entities WHERE user_id=%s AND kind='user'", (user["id"],)
        ).fetchone()
        assert own is not None and entry["scopes"]["own"] == own["slug"]
        assert entry["team_routed"] == 0

        pipeline.evaluate(
            run, memkit, config_, [q for c in conversations for q in c.questions], {}, print
        )
        summary = pipeline.report(run)
        assert summary["questions"] == 1, run.state["questions"]
        assert summary["accuracy"] == 100.0
        assert summary["evidence_turn_recall"] == 1.0
        assert summary["evidence_session_hit"] == 1.0
        assert summary["memscore"].startswith("100% / ")
        # The run resumes without repeating finished work.
        before = json.dumps(run.state, sort_keys=True)
        pipeline.ingest(run, memkit, conversations, lambda _: None)
        pipeline.evaluate(
            run, memkit, config_, [q for c in conversations for q in c.questions], {}, print
        )
        assert json.dumps(run.state, sort_keys=True) == before

        # A second run adopts the first's users: no new user, no new ingest,
        # the same questions searched again under another setting.
        users = self.db.execute("SELECT count(*) AS n FROM users").fetchone()["n"]
        again = pipeline.Run.open("t2", Path(path.parent) / "runs")
        pipeline.adopt(again, run)
        self.enterContext(patch("memkit.routers.operations.judge_configured", return_value=True))
        pipeline.ingest(again, memkit, conversations, lambda _: None, dream=True)
        assert self.db.execute("SELECT count(*) AS n FROM users").fetchone()["n"] == users
        assert again.state["conversations"]["conv-1"]["dream"]["caught_up"] is True
        pipeline.evaluate(
            again,
            memkit,
            pipeline.Config(
                dataset="locomo",
                answer_model="fake-answer",
                judge_model="fake-judge",
                workers=1,
                policy="assistant-v3",
            ),
            [q for c in conversations for q in c.questions],
            {},
            print,
        )
        [record] = again.state["questions"].values()
        assert record["policy_id"] == "core-retrieval-v3"
        assert "request_ms" in record["timings"] or "total_ms" in record["timings"]
        compared = pipeline.compare(run, again)
        assert compared["overall"]["n"] == 1

    def _tmp(self):
        import tempfile

        return tempfile.TemporaryDirectory()
