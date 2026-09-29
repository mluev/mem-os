"""Ingest -> extract -> search -> answer -> judge -> report, resumable.

Every phase writes its result into one state file per run before moving on, so
an interrupted run resumes where it stopped and a finished run can be
re-reported, or re-judged with a different model, without paying for
ingestion again. The state file holds the per-conversation API keys; it is
written 0600 under data/, which is ignored by git.
"""

from __future__ import annotations

import json
import os
import statistics
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memkit.retrieval import _token_count

from . import answer as answering
from .client import Memkit
from .datasets import Conversation, Question

DEFAULT_RUNS = Path("data/bench-runs")


@dataclass
class Config:
    dataset: str
    mode: str = "memories"  # memories | hybrid | raw
    budget_tokens: int = 4000
    limit: int = 20
    rewrite: bool = False
    answer_model: str = "gemini-3.5-flash"
    judge_model: str = "gemini-3.5-flash"
    workers: int = 4

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class Run:
    run_id: str
    directory: Path
    state: dict[str, Any] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def open(cls, run_id: str, root: Path = DEFAULT_RUNS) -> Run:
        directory = root / run_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "state.json"
        state = json.loads(path.read_text()) if path.exists() else {}
        state.setdefault("conversations", {})
        state.setdefault("questions", {})
        return cls(run_id, directory, state)

    def save(self) -> None:
        with self.lock:
            path = self.directory / "state.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.state, indent=1, sort_keys=True))
            os.chmod(temporary, 0o600)
            temporary.replace(path)


def ingest(run: Run, memkit: Memkit, conversations: list[Conversation], log: Callable) -> None:
    for conversation in conversations:
        entry = run.state["conversations"].setdefault(conversation.conversation_id, {})
        if entry.get("extracted"):
            continue
        if "key" not in entry:
            entry["key"] = memkit.provision(conversation)
            run.save()
        if "mapping" not in entry:
            mapping = memkit.ingest(entry["key"], conversation)
            sessions = {
                turn.turn_id: session.session_id
                for session in conversation.sessions
                for turn in session.turns
            }
            entry["mapping"] = {str(mid): [tid, sessions[tid]] for mid, tid in mapping.items()}
            run.save()
            log(f"ingested {conversation.conversation_id}: {len(mapping)} turns")
        entry["jobs"] = memkit.wait(entry["key"])
        entry["extracted"] = True
        run.save()
        log(f"extracted {conversation.conversation_id}: {entry['jobs']}")


def retrieved_turns(payload: dict[str, Any], mapping: dict[str, list[str]]) -> set[tuple[str, str]]:
    ids = [
        source["message_id"]
        for memory in payload.get("memories") or []
        for source in memory.get("sources") or []
    ] + [passage["message_id"] for passage in payload.get("raw") or []]
    return {tuple(mapping[str(mid)]) for mid in ids if str(mid) in mapping}  # type: ignore[misc]


def evaluate_question(
    run: Run,
    memkit: Memkit,
    config: Config,
    question: Question,
    keys: dict[str, str],
) -> None:
    record = run.state["questions"].setdefault(question.question_id, {})
    conversation = run.state["conversations"][question.conversation_id]
    if "search" not in record:
        payload, latency = memkit.search(
            conversation["key"],
            question,
            mode=config.mode,
            budget_tokens=config.budget_tokens,
            limit=config.limit,
            rewrite=config.rewrite,
        )
        context = answering.render_context(payload)
        found = retrieved_turns(payload, conversation["mapping"])
        turns = {turn for turn, _ in found}
        sessions = {session for _, session in found}
        record.update(
            {
                "category": question.category,
                "abstention": question.abstention,
                "latency_ms": round(latency, 1),
                "context": context,
                "context_tokens": _token_count(context),
                "memories": len(payload.get("memories") or []),
                "evidence_turn_recall": (
                    len(turns & set(question.evidence_turns)) / len(question.evidence_turns)
                    if question.evidence_turns
                    else None
                ),
                "evidence_session_hit": (
                    bool(sessions & set(question.evidence_sessions))
                    if question.evidence_sessions
                    else None
                ),
                "search": True,
            }
        )
        run.save()
    if "answer" not in record:
        reply = answering.ask(
            config.answer_model,
            answering.answer_prompt(question, record["context"]),
            answering.ANSWER_SCHEMA,
            "emit_answer",
            keys,
        )
        record["answer"] = str(reply.get("answer") or "")
        record["reasoning"] = str(reply.get("reasoning") or "")
        run.save()
    if "correct" not in record:
        verdict = answering.ask(
            config.judge_model,
            answering.judge_prompt(question, record["answer"]),
            answering.JUDGE_SCHEMA,
            "emit_verdict",
            keys,
        )
        record["correct"] = bool(verdict.get("correct"))
        record["explanation"] = str(verdict.get("explanation") or "")
        record["expected"] = question.answer
        record["question"] = question.question
        run.save()


def evaluate(
    run: Run,
    memkit: Memkit,
    config: Config,
    questions: list[Question],
    keys: dict[str, str],
    log: Callable,
) -> None:
    def one(question: Question) -> None:
        try:
            evaluate_question(run, memkit, config, question, keys)
        except Exception as exc:  # recorded and retried on the next resume
            with run.lock:
                run.state["questions"].setdefault(question.question_id, {})["error"] = str(exc)
            log(f"{question.question_id}: {exc}")

    with ThreadPoolExecutor(max_workers=max(1, config.workers)) as pool:
        list(pool.map(one, questions))
    run.save()


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


def report(run: Run) -> dict[str, Any]:
    judged = [r for r in run.state["questions"].values() if "correct" in r]
    if not judged:
        return {"questions": 0}
    by_category: dict[str, list[bool]] = {}
    for record in judged:
        by_category.setdefault(record["category"], []).append(record["correct"])
    latencies = [r["latency_ms"] for r in judged]
    tokens = [r["context_tokens"] for r in judged]
    turn_recall = [
        r["evidence_turn_recall"] for r in judged if r["evidence_turn_recall"] is not None
    ]
    session_hits = [
        r["evidence_session_hit"] for r in judged if r["evidence_session_hit"] is not None
    ]
    accuracy = 100 * sum(r["correct"] for r in judged) / len(judged)
    latency = statistics.fmean(latencies)
    context = statistics.fmean(tokens)
    return {
        "questions": len(judged),
        "accuracy": round(accuracy, 2),
        "by_category": {
            name: {"n": len(values), "accuracy": round(100 * sum(values) / len(values), 2)}
            for name, values in sorted(by_category.items())
        },
        "evidence_turn_recall": round(statistics.fmean(turn_recall), 4) if turn_recall else None,
        "evidence_session_hit": round(statistics.fmean(session_hits), 4) if session_hits else None,
        "latency_ms": {
            "mean": round(latency, 1),
            "p50": round(_percentile(latencies, 0.5), 1),
            "p95": round(_percentile(latencies, 0.95), 1),
        },
        "context_tokens": round(context, 1),
        # Supermemory's MemoryBench composite: quality, speed and cost together.
        "memscore": f"{accuracy:.0f}% / {latency:.0f}ms / {context:.0f}tok",
        "errors": sum(
            1 for r in run.state["questions"].values() if "error" in r and "correct" not in r
        ),
        "config": run.state.get("config"),
    }
