"""Sampling and paired comparison, so a difference between two runs means something.

A benchmark that cannot afford every question samples them, and two arms are
only comparable on the same questions. Sampling is stratified by category and
deterministic -- the same seed picks the same questions on every machine -- and
a comparison is paired: per question, did the change turn a miss into a hit or
the other way round. The bootstrap interval says how far that difference could
move by chance at this sample size; McNemar's exact test says whether the
discordant questions lean one way more than a coin would.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable, Mapping
from typing import Any

from .datasets import Conversation

ADVERSARIAL = "adversarial"
ASSISTANT_ONLY = "single-session-assistant"


def parse_sample(spec: str) -> dict[str, int]:
    """'*=50,single-session-assistant=15' -> {'*': 50, 'single-session-assistant': 15}."""
    sizes: dict[str, int] = {}
    for part in filter(None, (item.strip() for item in spec.split(","))):
        name, _, count = part.partition("=")
        if not name or not count.isdigit():
            raise ValueError(f"bad sample entry {part!r}; expected CATEGORY=COUNT or *=COUNT")
        sizes[name.strip()] = int(count)
    return sizes


def _order(seed: int, question_id: str) -> str:
    return hashlib.sha256(f"{seed}|{question_id}".encode()).hexdigest()


def sample(conversations: list[Conversation], sizes: Mapping[str, int], seed: int) -> None:
    """Keep up to `sizes[category]` questions per category (or `sizes['*']`), in place.

    The order within a category is a hash of the seed and the question id, so
    adding a category or a conversation never reshuffles the others.
    """
    by_category: dict[str, list[str]] = {}
    for conversation in conversations:
        for question in conversation.questions:
            by_category.setdefault(question.category, []).append(question.question_id)
    keep: set[str] = set()
    for category, ids in by_category.items():
        size = sizes.get(category, sizes.get("*"))
        chosen = sorted(ids, key=lambda qid: _order(seed, qid))
        keep.update(chosen if size is None else chosen[:size])
    for conversation in conversations:
        conversation.questions = [q for q in conversation.questions if q.question_id in keep]


def category_counts(conversations: Iterable[Conversation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for conversation in conversations:
        for question in conversation.questions:
            counts[question.category] = counts.get(question.category, 0) + 1
    return counts


def weighted_accuracy(
    by_category: Mapping[str, list[bool]], shares: Mapping[str, int], *, exclude: set[str]
) -> float | None:
    """Per-category accuracy reweighted to the full dataset's category mix.

    A stratified sample over-represents small categories; published scores are
    micro-averages over every question. Reweighting by the full dataset's
    counts makes a sampled run comparable to them.
    """
    total = weight = 0.0
    for category, values in by_category.items():
        if category in exclude or not values or not shares.get(category):
            continue
        weight += shares[category]
        total += shares[category] * sum(values) / len(values)
    return round(100 * total / weight, 2) if weight else None


def _mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def _bootstrap(diffs: list[int], *, resamples: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)  # noqa: S311 -- a seeded resample, reproducible on purpose
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(resamples))
    low = means[int(0.025 * (resamples - 1))]
    high = means[int(0.975 * (resamples - 1))]
    return round(100 * low, 2), round(100 * high, 2)


def compare(
    baseline: Mapping[str, Mapping[str, Any]],
    candidate: Mapping[str, Mapping[str, Any]],
    *,
    resamples: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    """Paired difference, candidate minus baseline, on the questions both judged."""
    shared = sorted(
        qid
        for qid in set(baseline) & set(candidate)
        if "correct" in baseline[qid] and "correct" in candidate[qid]
    )

    def summarise(ids: list[str]) -> dict[str, Any]:
        diffs = [int(candidate[q]["correct"]) - int(baseline[q]["correct"]) for q in ids]
        gained = sum(1 for d in diffs if d > 0)
        lost = sum(1 for d in diffs if d < 0)
        low, high = _bootstrap(diffs, resamples=resamples, seed=seed) if ids else (None, None)
        return {
            "n": len(ids),
            "baseline": round(100 * sum(baseline[q]["correct"] for q in ids) / len(ids), 2)
            if ids
            else None,
            "candidate": round(100 * sum(candidate[q]["correct"] for q in ids) / len(ids), 2)
            if ids
            else None,
            "delta": round(100 * sum(diffs) / len(ids), 2) if ids else None,
            "ci95": [low, high],
            "gained": gained,
            "lost": lost,
            "mcnemar_p": round(_mcnemar_exact(gained, lost), 4),
        }

    headline = [q for q in shared if baseline[q].get("category") != ADVERSARIAL]
    categories = sorted({str(baseline[q].get("category")) for q in shared})
    return {
        "overall": summarise(headline),
        "excluding_assistant": summarise(
            [q for q in headline if baseline[q].get("category") != ASSISTANT_ONLY]
        ),
        "by_category": {
            name: summarise([q for q in shared if baseline[q].get("category") == name])
            for name in categories
        },
    }
