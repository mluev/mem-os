"""LoCoMo and LongMemEval, loaded into one shape.

A benchmark is conversations, each a list of dated sessions of turns, plus
questions asked after them. LongMemEval gives every question its own haystack,
so each LongMemEval question is its own conversation; LoCoMo asks many
questions of one long conversation between two people.

Both LoCoMo speakers are people, and only user-role words can support a memory
in this service (provenance.may_write), so both are ingested as `user` turns
prefixed with the speaker's name. LongMemEval keeps its user/assistant roles:
its assistant turns are context, never evidence, exactly as in production.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
LONGMEMEVAL_URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/"
    "longmemeval_s_cleaned.json"
)

# LoCoMo's integer categories, named as the dataset's authors describe them.
# Category 5 questions are unanswerable by construction ("adversarial") and have
# no `answer`; they are excluded by default, as in most published comparisons.
LOCOMO_CATEGORIES = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}


@dataclass
class Turn:
    turn_id: str
    role: str
    speaker: str
    text: str


@dataclass
class Session:
    session_id: str
    date: datetime | None
    turns: list[Turn]


@dataclass
class Question:
    question_id: str
    conversation_id: str
    question: str
    answer: str
    category: str
    question_date: datetime | None
    evidence_turns: list[str] = field(default_factory=list)
    evidence_sessions: list[str] = field(default_factory=list)
    abstention: bool = False


@dataclass
class Conversation:
    conversation_id: str
    sessions: list[Session]
    questions: list[Question]


def _locomo_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text.strip(), "%I:%M %p on %d %B, %Y").replace(tzinfo=UTC)
    except ValueError:
        return None


def load_locomo(path: Path, *, include_adversarial: bool = False) -> list[Conversation]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    conversations = []
    for sample in data:
        conv_id = str(sample["sample_id"])
        convo = sample["conversation"]
        numbers = sorted(
            int(match.group(1)) for key in convo if (match := re.fullmatch(r"session_(\d+)", key))
        )
        sessions = []
        for number in numbers:
            turns = []
            for raw in convo[f"session_{number}"]:
                text = str(raw.get("text") or "").strip()
                caption = raw.get("blip_caption")
                if caption:
                    text = f"{text} [shares a photo of {caption}]".strip()
                if not text:
                    continue
                turns.append(
                    Turn(
                        turn_id=str(raw["dia_id"]),
                        role="user",
                        speaker=str(raw["speaker"]),
                        text=f"{raw['speaker']}: {text}",
                    )
                )
            sessions.append(
                Session(
                    session_id=f"{conv_id}-s{number}",
                    date=_locomo_date(convo.get(f"session_{number}_date_time")),
                    turns=turns,
                )
            )
        asked = max((s.date for s in sessions if s.date), default=None)
        questions = []
        for index, qa in enumerate(sample["qa"]):
            category = LOCOMO_CATEGORIES.get(int(qa.get("category", 0)), "unknown")
            if category == "adversarial" and not include_adversarial:
                continue
            evidence = [str(e) for e in qa.get("evidence") or []]
            questions.append(
                Question(
                    question_id=f"{conv_id}-q{index}",
                    conversation_id=conv_id,
                    question=str(qa["question"]),
                    answer=str(qa.get("answer", "")),
                    category=category,
                    question_date=asked,
                    evidence_turns=evidence,
                    evidence_sessions=sorted(
                        {f"{conv_id}-s{e.split(':')[0][1:]}" for e in evidence if ":" in e}
                    ),
                    abstention=category == "adversarial",
                )
            )
        conversations.append(Conversation(conv_id, sessions, questions))
    return conversations


def _longmemeval_date(text: str | None) -> datetime | None:
    if not text:
        return None
    match = re.match(r"(\d{4})/(\d{2})/(\d{2})\s*\([^)]*\)\s*(\d{2}):(\d{2})", text)
    if not match:
        return None
    year, month, day, hour, minute = (int(part) for part in match.groups())
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def load_longmemeval(path: Path) -> list[Conversation]:
    data: list[dict[str, Any]] = json.loads(Path(path).read_text(encoding="utf-8"))
    conversations = []
    for item in data:
        qid = str(item["question_id"])
        session_ids = item.get("haystack_session_ids") or [
            f"{qid}-h{i}" for i in range(len(item["haystack_sessions"]))
        ]
        sessions = []
        for index, (raw_session, date) in enumerate(
            zip(item["haystack_sessions"], item["haystack_dates"], strict=False)
        ):
            sid = f"{qid}-{session_ids[index]}"
            turns = [
                Turn(
                    turn_id=f"{sid}:{turn_index}",
                    role="assistant" if message["role"] == "assistant" else "user",
                    speaker=message["role"],
                    text=str(message["content"]).strip(),
                )
                for turn_index, message in enumerate(raw_session)
                if str(message.get("content") or "").strip()
            ]
            sessions.append(Session(sid, _longmemeval_date(date), turns))
        question_type = str(item["question_type"])
        conversations.append(
            Conversation(
                qid,
                sessions,
                [
                    Question(
                        question_id=qid,
                        conversation_id=qid,
                        question=str(item["question"]),
                        answer=str(item["answer"]),
                        category=question_type,
                        question_date=_longmemeval_date(item.get("question_date")),
                        evidence_sessions=[
                            f"{qid}-{sid}" for sid in item.get("answer_session_ids") or []
                        ],
                        abstention=qid.endswith("_abs"),
                    )
                ],
            )
        )
    return conversations


def load(name: str, path: Path, **kwargs: Any) -> list[Conversation]:
    if name == "locomo":
        return load_locomo(path, **kwargs)
    if name == "longmemeval":
        return load_longmemeval(path)
    raise ValueError(f"unknown benchmark {name!r}; expected locomo or longmemeval")
