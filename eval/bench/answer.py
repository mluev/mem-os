"""Turn a search response into answer context, answer, and judge the answer.

The context format follows what the service returns and nothing more: each
memory with when it was said and when it happened, what it replaced, what it
is linked to, and the source chunk it came from; then any raw passages. The
answering model is told the question date, because "how many days ago" has no
answer without one.

Judge prompts follow LongMemEval's published per-type instructions (temporal
answers tolerate off-by-one day counts; knowledge-update answers may mention
the old value if they give the new one; abstention is correct only when the
system says it does not know).
"""

from __future__ import annotations

from typing import Any

from memkit import providers

from .datasets import Question


def render_context(payload: dict[str, Any]) -> str:
    blocks = []
    for number, memory in enumerate(payload.get("memories") or [], start=1):
        lines = [f"[{number}] {memory['text']}"]
        when = []
        if memory.get("document_date"):
            when.append(f"said {memory['document_date'][:10]}")
        if memory.get("event_dates"):
            when.append(f"happened {', '.join(memory['event_dates'])}")
        if when:
            lines.append(f"    ({'; '.join(when)})")
        for old in memory.get("history") or []:
            until = f" until {old['valid_until'][:10]}" if old.get("valid_until") else ""
            lines.append(f"    previously{until}: {old['text']}")
        for linked in memory.get("related") or []:
            lines.append(f"    {linked['relation'].replace('_', ' ')}: {linked['text']}")
        for source in memory.get("sources") or []:
            said = (source.get("created_at") or "")[:10]
            lines.append(f"    source ({said}): {source.get('context') or source['excerpt']}")
        blocks.append("\n".join(lines))
    for passage in payload.get("raw") or []:
        said = (passage.get("created_at") or "")[:10]
        blocks.append(f"[passage {said}] {passage['text']}")
    return "\n\n".join(blocks) if blocks else "(nothing found)"


def answer_prompt(question: Question, context: str) -> str:
    asked = question.question_date.strftime("%Y-%m-%d") if question.question_date else "unknown"
    return f"""You answer questions about a person's past conversations using only the
memories retrieved below.

Each memory may show when it was said and when the thing it describes happened.
Relative words in a memory ("yesterday", "last week") were already resolved
against the day it was said. "previously" lines are older values that were
later replaced; the memory itself is the current value. Source lines quote the
original conversation and carry the details.

Question date: {asked}
Question: {question.question}

Retrieved memories:
{context}

Think step by step: find the relevant memories, use their dates for any time
arithmetic (counting from the question date when the question is about "now"),
prefer current values over replaced ones unless the question asks about the
past. If the memories do not contain the answer, say you do not know. Keep the
final answer short."""


ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"reasoning": {"type": "string"}, "answer": {"type": "string"}},
    "required": ["reasoning", "answer"],
}

JUDGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"correct": {"type": "boolean"}, "explanation": {"type": "string"}},
    "required": ["correct", "explanation"],
}

_BASE = (
    "Decide whether the response contains the correct answer. It is correct if it is "
    "equivalent to the correct answer or contains all the intermediate steps to reach it. "
    "It is incorrect if it only contains part of the required information."
)
_TEMPORAL = (
    " Do not penalise off-by-one errors in a number of days, weeks or months: 19 days for "
    "an answer of 18 days is correct."
)
_UPDATE = (
    " A response that mentions earlier information together with the updated answer is "
    "correct as long as the updated answer is the one required."
)
_PREFERENCE = (
    "Decide whether the response satisfies the rubric for a personalised answer. It need "
    "not reflect every point; it is correct if it recalls and uses the person's own "
    "information correctly."
)
_ABSTAIN = (
    "The information was never in the conversations, so the correct behaviour is to say "
    "it is not known. The response is correct only if it abstains or says it does not "
    "know; it is incorrect if it gives an answer."
)


def judge_prompt(question: Question, response: str) -> str:
    kind = question.category.lower()
    if question.abstention:
        rule, label = _ABSTAIN, "Correct behaviour"
    elif "preference" in kind:
        rule, label = _PREFERENCE, "Rubric"
    elif "temporal" in kind:
        rule, label = _BASE + _TEMPORAL, "Correct answer"
    elif "update" in kind:
        rule, label = _BASE + _UPDATE, "Correct answer"
    else:
        rule, label = _BASE, "Correct answer"
    expected = "say that it is not known" if question.abstention else question.answer
    return f"""{rule}

Question: {question.question}
{label}: {expected}
Response: {response}"""


def ask(model: str, prompt: str, schema: dict[str, Any], name: str, keys: dict[str, str]) -> dict:
    result = providers.call_json(
        model=model,
        prompt=prompt,
        schema=schema,
        name=name,
        anthropic_api_key=keys.get("anthropic", ""),
        gemini_api_key=keys.get("gemini", ""),
        project=keys.get("project", ""),
        location=keys.get("location", ""),
        max_tokens=2048,
    )
    if result.error or not isinstance(result.raw, dict):
        raise RuntimeError(result.error or "empty model response")
    return result.raw
