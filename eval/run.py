"""Retrieval eval. One command, run before and after every change.

Assertions are content-based -- regexes matched against returned text -- not
memory ids. docs/05-retrieval.md pins ids (``expect: ["m-7f2a"]``), but
``POST /v1/admin/reextract`` mints new ids by design, so an id-pinned eval file
invalidates itself on the first re-extraction. Since the eval is the only thing
distinguishing a real improvement from a hunch, it has to survive the operation
the docs are built around.

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


def run_eval(queries_path: Path, limit: int = 10, target: str = "raw") -> int:
    """Run the eval against raw turns or extracted facts.

    `raw` is the stage-1 baseline: semantic search over the user's own messages.
    `memories` measures the extracted facts, which is what stages 2-3 are
    actually trying to improve. Running the same query set against both is the
    comparison the project rests on -- the target changes, the questions do not.
    """
    from memkit import retrieval, store, vectors
    from memkit.config import get_settings
    from memkit.embed import get_embedder

    if not queries_path.exists():
        print(f"no eval file at {queries_path}", file=sys.stderr)
        return 1

    all_cases = [
        Case.parse(raw, i)
        for i, raw in enumerate(yaml.safe_load(queries_path.read_text()) or [])
    ]
    if not all_cases:
        print("eval file is empty", file=sys.stderr)
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

    s = get_settings()
    client = vectors.get_client(s.qdrant_url)
    embedder = get_embedder()

    hits_at_k, reject_violations, token_counts = 0, 0, []
    reciprocal_ranks: list[float] = []
    top1 = 0
    failures: list[str] = []

    if target == "memories":
        n_facts = vectors.count(client, vectors.MEMORIES)
        if n_facts == 0:
            print(
                "no extracted facts in the store — run `memkit backfill` first "
                "(needs ANTHROPIC_API_KEY)",
                file=sys.stderr,
            )
            return 1
        print(f"target            memories ({n_facts} facts)")
    else:
        print(f"target            raw ({vectors.count(client, vectors.RAW)} turns)")

    for case in cases:
        if target == "memories":
            scored, used = retrieval.search(
                client, embedder, query=case.query, owner_id=s.owner_id,
                project=case.project, limit=limit, budget_tokens=0,
            )
            texts = [x.text for x in scored]
            token_counts.append(used)
        else:
            results = store.search_raw(
                client, embedder, query=case.query, owner_id=s.owner_id,
                limit=limit, project=case.project,
            )
            texts = [r["text"] for r in results]
            token_counts.append(sum(len(t) // 3 for t in texts))

        ok = True
        if case.expect_any:
            rank = _first_rank(case.expect_any, texts)
            if rank is None:
                ok = False
                reciprocal_ranks.append(0.0)
                failures.append(
                    f"  {case.id}: none of expect_any matched -> {case.expect_any}"
                )
            else:
                reciprocal_ranks.append(1.0 / rank)
                if rank == 1:
                    top1 += 1
        for pattern in case.expect_all:
            if not _matches(pattern, texts):
                ok = False
                failures.append(f"  {case.id}: expect_all missing -> {pattern!r}")
        for pattern in case.reject:
            if _matches(pattern, texts):
                reject_violations += 1
                failures.append(f"  {case.id}: rejected pattern present -> {pattern!r}")
        if ok:
            hits_at_k += 1

    n = len(cases)
    scored = len(reciprocal_ranks) or 1
    print(f"cases             {n}")
    if skipped:
        # Named, never silent: a suppressed case is a coverage claim not being
        # made, and that has to be visible in the output that gets compared.
        print(f"skipped           {len(skipped)} not answerable by {target} "
              f"({', '.join(c.id for c in skipped[:6])}"
              f"{', ...' if len(skipped) > 6 else ''})")
    print(f"recall@{limit:<11} {hits_at_k / n:.2f}  ({hits_at_k}/{n})")
    print(f"MRR               {sum(reciprocal_ranks) / scored:.3f}")
    print(f"top-1 hits        {top1}/{scored}")
    print(f"reject violations {reject_violations}")
    print(f"mean tokens       {statistics.mean(token_counts):.0f}")
    print(f"max tokens        {max(token_counts)}")
    if failures:
        print("\nfailures:")
        for line in failures:
            print(line)
    return 0


if __name__ == "__main__":
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/queries.yaml")
    raise SystemExit(run_eval(path, target=sys.argv[2] if len(sys.argv) > 2 else "raw"))
