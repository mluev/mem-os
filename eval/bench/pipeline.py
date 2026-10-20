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
from . import stats
from .client import Memkit
from .datasets import Conversation, Question

DEFAULT_RUNS = Path("data/bench-runs")


@dataclass
class Config:
    dataset: str
    mode: str = "memories"  # memories | hybrid | raw
    budget_tokens: int = 4000
    # memorybench's searchLimit since its protocol fix (PR #96).
    limit: int = 30
    rewrite: bool = False
    # Retrieval policy named on every search; empty means the server default.
    policy: str = ""
    answer_model: str = "gemini-3.5-flash"
    judge_model: str = "gemini-3.5-flash"
    workers: int = 4
    # Dream each conversation's scope until it has caught up, before asking.
    dream: bool = False
    # Ceiling on the answering and judging models' spend; 0 is no ceiling.
    budget_usd: float = 0.0

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
            # Created 0600, never chmodded after the fact: the keys must not be
            # readable for even the moment between write and chmod.
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as handle:
                handle.write(json.dumps(self.state, indent=1, sort_keys=True))
            temporary.replace(path)

    def update(self, record: dict[str, Any], values: dict[str, Any]) -> None:
        """Change one question's record and checkpoint it.

        Workers share `state`; mutating it outside the lock races `save`, which
        serialises the whole tree.
        """
        with self.lock:
            record.update(values)
        self.save()


class BudgetSpent(RuntimeError):
    pass


def adopt(run: Run, source: Run) -> None:
    """Search again over what `source` ingested (and dreamed), without paying twice.

    The per-conversation users carry over, so retrieval settings -- a policy,
    rewrites, a reranker, a mode -- are compared on exactly the same memories,
    as memorybench's --source-run does. A dream run on the adopted users
    changes them for every later run that adopts them too, which is why
    `dreamed` is carried over and reported.
    """
    for name, entry in source.state["conversations"].items():
        run.state["conversations"].setdefault(name, dict(entry))
    run.save()


def ingest(
    run: Run,
    memkit: Memkit,
    conversations: list[Conversation],
    log: Callable,
    *,
    dream: bool = False,
) -> None:
    for conversation in conversations:
        entry = run.state["conversations"].setdefault(conversation.conversation_id, {})
        if entry.get("extracted"):
            _settle(run, memkit, conversation.conversation_id, entry, log, dream=dream)
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
        _settle(run, memkit, conversation.conversation_id, entry, log, dream=dream)


def _settle(
    run: Run, memkit: Memkit, name: str, entry: dict[str, Any], log: Callable, *, dream: bool
) -> None:
    """After extraction: which scope to search, what leaked to the team, dreams."""
    if "scopes" not in entry:
        entry["scopes"] = memkit.scopes(entry["key"])
        entry["team_routed"] = memkit.team_routed(entry["key"], entry["scopes"])
        run.save()
    if dream and not entry.get("dreamed"):
        entry["dream"] = memkit.dream(entry["key"])
        entry["dreamed"] = True
        run.save()
        log(f"dreamed {name}: {entry['dream']}")


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
    with run.lock:
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
            policy=config.policy,
            scope=(conversation.get("scopes") or {}).get("own", ""),
        )
        context = answering.render_context(payload)
        found = retrieved_turns(payload, conversation["mapping"])
        turns = {turn for turn, _ in found}
        sessions = {session for _, session in found}
        run.update(
            record,
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
                "rewrites": list(payload.get("rewrites") or []),
                "policy_id": payload.get("policy_id"),
                "timings": payload.get("timings") or {},
                "search": True,
            },
        )

    def spent(cost: float) -> None:
        with run.lock:
            run.state["eval_cost_usd"] = run.state.get("eval_cost_usd", 0.0) + cost

    def affordable() -> None:
        if config.budget_usd and run.state.get("eval_cost_usd", 0.0) >= config.budget_usd:
            raise BudgetSpent(f"answer/judge budget of ${config.budget_usd} spent")

    if "answer" not in record:
        affordable()
        reply = answering.ask(
            config.answer_model,
            answering.answer_prompt(question, record["context"]),
            answering.ANSWER_SCHEMA,
            "emit_answer",
            keys,
            on_cost=spent,
        )
        run.update(
            record,
            {
                "answer": str(reply.get("answer") or ""),
                "reasoning": str(reply.get("reasoning") or ""),
            },
        )
    if "correct" not in record:
        affordable()
        verdict = answering.ask(
            config.judge_model,
            answering.judge_prompt(question, record["answer"]),
            answering.JUDGE_SCHEMA,
            "emit_verdict",
            keys,
            on_cost=spent,
        )
        run.update(
            record,
            {
                "correct": bool(verdict.get("correct")),
                "explanation": str(verdict.get("explanation") or ""),
                "expected": question.answer,
                "question": question.question,
            },
        )


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
    every = [r for r in run.state["questions"].values() if "correct" in r]
    if not every:
        return {"questions": 0}
    by_category: dict[str, list[bool]] = {}
    for record in every:
        by_category.setdefault(record["category"], []).append(record["correct"])
    # LoCoMo's adversarial questions never count toward the headline, as in
    # every published comparison; they are still reported by category.
    judged = [r for r in every if r["category"] != stats.ADVERSARIAL]
    if not judged:
        judged = every
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
    without_assistant = [r for r in judged if r["category"] != stats.ASSISTANT_ONLY]
    config = run.state.get("config") or {}
    conversations = run.state["conversations"].values()
    return {
        "questions": len(judged),
        "accuracy": round(accuracy, 2),
        # Comparable across prompts that can and cannot answer what the
        # assistant said: v12 is judged on both.
        "accuracy_excluding_assistant": round(
            100 * sum(r["correct"] for r in without_assistant) / len(without_assistant), 2
        )
        if without_assistant
        else None,
        "weighted_accuracy": stats.weighted_accuracy(
            by_category, config.get("category_counts") or {}, exclude={stats.ADVERSARIAL}
        ),
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
        # Facts the extractor sent to the team scope, invisible to own-scope
        # search: the cost of routing, measured rather than hidden.
        "team_routed": sum(int(entry.get("team_routed") or 0) for entry in conversations),
        "dreamed": sum(1 for entry in conversations if entry.get("dreamed")),
        "spend_usd": {
            **(run.state.get("spend") or {}),
            "answer_and_judge": round(run.state.get("eval_cost_usd", 0.0), 4),
        },
        "config": config,
    }


def compare(baseline: Run, candidate: Run) -> dict[str, Any]:
    """Candidate minus baseline on the questions both runs judged (stats.compare)."""
    left = baseline.state.get("config") or {}
    right = candidate.state.get("config") or {}
    if left.get("data_sha256") != right.get("data_sha256"):
        raise ValueError("the two runs measured different dataset files")
    return {
        "baseline": baseline.run_id,
        "candidate": candidate.run_id,
        **stats.compare(baseline.state["questions"], candidate.state["questions"]),
    }
