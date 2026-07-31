"""Retrieval eval. One command, run before and after every change.

Assertions are content-based -- regexes matched against returned text -- not
memory ids. The original spec pinned ids (``expect: ["m-7f2a"]``), but
``POST /v1/admin/reextract`` mints new ids by design, so an id-pinned eval file
invalidates itself on the first re-extraction. Since the eval is the only thing
distinguishing a real improvement from a hunch, it has to survive the operation
the docs are built around.

Two modes, and the difference matters:

    --target raw | memories   one target, over the cases that target can answer
    --compare                 both targets, over the cases BOTH can answer

Only the second is a comparison. This file used to claim in its own docstring
that "the target changes, the questions do not", while filtering cases per
target four lines below -- so `--target raw` scored 47 cases and
`--target memories` scored 31, and the two printouts were read side by side as a
head-to-head. Every raw-vs-facts figure published before `--compare` existed was
across different question sets.

The number this prints is a baseline, not a grade. 30-odd queries is not
statistical rigour; it is enough to make a regression visible immediately.
"""

from __future__ import annotations

import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

TARGETS = ("raw", "memories")

# Metric keys, in report order. Shared by the single-target report and the
# side-by-side comparison so the two cannot drift apart.
METRICS = ("cases", "recall", "mrr", "top1", "rejects", "mean_tokens", "max_tokens")


@dataclass
class Case:
    id: str
    query: str
    expect_any: list[str]
    expect_all: list[str]
    reject: list[str]
    project: str | None
    answerable_by: tuple[str, ...]

    @classmethod
    def parse(cls, raw: dict[str, Any], index: int) -> Case:
        declared = raw.get("answerable_by")
        if declared is None:
            answerable = TARGETS
        else:
            answerable = tuple(str(t) for t in declared)
            unknown = set(answerable) - set(TARGETS)
            if unknown:
                raise ValueError(
                    f"{raw.get('id')}: unknown answerable_by {sorted(unknown)}"
                )
        return cls(
            id=str(raw.get("id") or f"q{index}"),
            query=raw["query"],
            expect_any=[str(p) for p in raw.get("expect_any", [])],
            expect_all=[str(p) for p in raw.get("expect_all", [])],
            reject=[str(p) for p in raw.get("reject", [])],
            project=raw.get("project"),
            answerable_by=answerable,
        )


def _matches(pattern: str, texts: list[str]) -> bool:
    rx = re.compile(pattern, re.IGNORECASE)
    return any(rx.search(t) for t in texts)


def _first_rank(patterns: list[str], texts: list[str]) -> int | None:
    """1-based rank of the earliest result matching any pattern.

    recall@k saturates: with 300 documents and k=10, almost any sane query
    scrapes a hit somewhere in the list, so recall alone cannot tell a good
    ranking from a lucky one. Reciprocal rank keeps moving after recall pegs at
    1.0, which is what makes it useful as a baseline for later stages.
    """
    rxs = [re.compile(p, re.IGNORECASE) for p in patterns]
    for i, text in enumerate(texts, start=1):
        if any(rx.search(text) for rx in rxs):
            return i
    return None


def load_cases(queries_path: Path) -> list[Case]:
    return [
        Case.parse(raw, i)
        for i, raw in enumerate(yaml.safe_load(queries_path.read_text()) or [])
    ]


def score(client, embedder, settings, cases: list[Case], *, target: str, limit: int):
    """Score one target over exactly the cases handed in.

    Case *selection* is the caller's job on purpose. Filtering inside the scorer
    is what made the two targets incomparable: `run_eval` narrows per target, so
    `--target raw` scored 47 cases against `--target memories`' 31 and the two
    printouts were read side by side as though they were the same questions.
    """
    from memkit import retrieval, store

    hits, rejects, tokens = 0, 0, []
    reciprocal: list[float] = []
    top1 = 0
    failures: list[str] = []

    for case in cases:
        if target == "memories":
            scored, used = retrieval.search(
                client, embedder, query=case.query, owner_id=settings.owner_id,
                project=case.project, limit=limit, budget_tokens=0,
            )
            texts = [x.text for x in scored]
            tokens.append(used)
        else:
            results = store.search_raw(
                client, embedder, query=case.query, owner_id=settings.owner_id,
                limit=limit, project=case.project,
            )
            texts = [r["text"] for r in results]
            tokens.append(sum(len(t) // 3 for t in texts))

        ok = True
        if case.expect_any:
            rank = _first_rank(case.expect_any, texts)
            if rank is None:
                ok = False
                reciprocal.append(0.0)
                failures.append(
                    f"  {case.id}: none of expect_any matched -> {case.expect_any}"
                )
            else:
                reciprocal.append(1.0 / rank)
                if rank == 1:
                    top1 += 1
        for pattern in case.expect_all:
            if not _matches(pattern, texts):
                ok = False
                failures.append(f"  {case.id}: expect_all missing -> {pattern!r}")
        for pattern in case.reject:
            if _matches(pattern, texts):
                rejects += 1
                failures.append(f"  {case.id}: rejected pattern present -> {pattern!r}")
        if ok:
            hits += 1

    n = len(cases) or 1
    ranked = len(reciprocal) or 1
    return {
        "cases": len(cases),
        "recall": hits / n,
        "hits": hits,
        "mrr": sum(reciprocal) / ranked,
        "top1": top1,
        "ranked": ranked,
        "rejects": rejects,
        "mean_tokens": statistics.mean(tokens) if tokens else 0.0,
        "max_tokens": max(tokens) if tokens else 0,
        "failures": failures,
    }


def _setup(queries_path: Path):
    """Shared preamble: parse the file, open Qdrant, load the embedder."""
    from memkit import vectors
    from memkit.config import get_settings
    from memkit.embed import get_embedder

    if not queries_path.exists():
        raise FileNotFoundError(f"no eval file at {queries_path}")
    cases = load_cases(queries_path)
    if not cases:
        raise ValueError("eval file is empty")
    settings = get_settings()
    return (
        cases, settings, vectors.get_client(settings.qdrant_url), get_embedder()
    )


def run_eval(queries_path: Path, limit: int = 10, target: str = "raw") -> int:
    """Run the eval against raw turns or extracted facts.

    `raw` is the stage-1 baseline: semantic search over the user's own messages.
    `memories` measures the extracted facts, which is what stages 2-3 are
    actually trying to improve.

    This reports ONE target over the cases that target can answer. It is not a
    head-to-head: the two targets answer different numbers of questions, so
    comparing two of these printouts compares different question sets. Use
    `run_compare` for that, and see the note it prints.
    """
    from memkit import vectors

    try:
        all_cases, settings, client, embedder = _setup(queries_path)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    # A question the extractor is *right* to have no answer for must not be
    # scored against the memory store. Measured before this split: 19 of 22
    # misses against `memories` were windows the judge had read and correctly
    # declined -- one-off tickets ("the header is too big", "run the seeder"),
    # which prompt rule 8 forbids storing. Scoring those produced MRR 0.253 and
    # read as an extractor failure when it was a specification conflict.
    cases = [c for c in all_cases if target in c.answerable_by]
    skipped = [c for c in all_cases if target not in c.answerable_by]
    if not cases:
        print(f"no cases answerable by {target!r}", file=sys.stderr)
        return 1

    if target == "memories":
        n_facts = vectors.count(client, vectors.MEMORIES)
        if n_facts == 0:
            print(
                "no extracted facts in the store — run `memkit backfill` first "
                "(needs GEMINI_API_KEY or ANTHROPIC_API_KEY)",
                file=sys.stderr,
            )
            return 1
        print(f"target            memories ({n_facts} facts)")
    else:
        print(f"target            raw ({vectors.count(client, vectors.RAW)} turns)")

    m = score(client, embedder, settings, cases, target=target, limit=limit)
    print(f"cases             {m['cases']}")
    if skipped:
        # Named, never silent: a suppressed case is a coverage claim not being
        # made, and that has to be visible in the output that gets compared.
        print(f"skipped           {len(skipped)} not answerable by {target} "
              f"({', '.join(c.id for c in skipped[:6])}"
              f"{', ...' if len(skipped) > 6 else ''})")
    print(f"recall@{limit:<11} {m['recall']:.2f}  ({m['hits']}/{m['cases']})")
    print(f"MRR               {m['mrr']:.3f}")
    print(f"top-1 hits        {m['top1']}/{m['ranked']}")
    print(f"reject violations {m['rejects']}")
    print(f"mean tokens       {m['mean_tokens']:.0f}")
    print(f"max tokens        {m['max_tokens']}")
    if skipped:
        print("\nnot a head-to-head: run `--compare` for that.")
    if m["failures"]:
        print("\nfailures:")
        for line in m["failures"]:
            print(line)
    return 0


def run_compare(queries_path: Path, limit: int = 10) -> int:
    """Score both targets over the cases both can answer.

    This is the number the stage-2 exit gate turns on, so it has to be the same
    questions on both sides. Extracted facts lose on absolute MRR and win by a
    wide margin per token; which of those matters is a judgement call, and the
    point of printing both is that the call is made in the open.
    """
    try:
        all_cases, settings, client, embedder = _setup(queries_path)
    except (FileNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1

    shared = [c for c in all_cases if set(TARGETS) <= set(c.answerable_by)]
    if not shared:
        print("no case is answerable by both targets", file=sys.stderr)
        return 1
    excluded = [c for c in all_cases if c not in shared]

    results = {
        t: score(client, embedder, settings, shared, target=t, limit=limit)
        for t in TARGETS
    }

    print(f"shared cases      {len(shared)} of {len(all_cases)}")
    if excluded:
        print(f"excluded          {len(excluded)} answerable by one target only "
              f"({', '.join(c.id for c in excluded[:6])}"
              f"{', ...' if len(excluded) > 6 else ''})")
    print()
    print(f"{'metric':<18}{'raw':>12}{'memories':>12}")
    print("-" * 42)
    rows = (
        (f"recall@{limit}", "recall", "{:.2f}"),
        ("MRR", "mrr", "{:.3f}"),
        ("top-1 hits", "top1", "{:d}"),
        ("reject violations", "rejects", "{:d}"),
        ("mean tokens", "mean_tokens", "{:.0f}"),
        ("max tokens", "max_tokens", "{:d}"),
    )
    for label, key, fmt in rows:
        cells = "".join(fmt.format(results[t][key]).rjust(12) for t in TARGETS)
        print(f"{label:<18}{cells}")
    density = {
        t: 1000 * results[t]["mrr"] / (results[t]["mean_tokens"] or 1) for t in TARGETS
    }
    cells = "".join(f"{density[t]:.3f}".rjust(12) for t in TARGETS)
    print(f"{'MRR per 1k tok':<18}{cells}")
    print()
    for t in TARGETS:
        misses = [f.split(":")[0].strip() for f in results[t]["failures"]]
        print(f"{t} misses: {', '.join(misses) or 'none'}")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--compare" in argv:
        argv.remove("--compare")
        path = Path(argv[0] if argv else "eval/queries.yaml")
        raise SystemExit(run_compare(path))
    path = Path(argv[0] if argv else "eval/queries.yaml")
    raise SystemExit(run_eval(path, target=argv[1] if len(argv) > 1 else "raw"))
