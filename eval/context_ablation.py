"""Offline source-priority and budget ablations of an exact recorded runtime pool.

No model calls, threshold tuning or new labels. These are diagnostic comparisons
on already opened cases, with the recorded Jev answers reused unchanged.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from memkit.retrieval import _token_count

from .context_cases import corpus
from .context_experiments import metrics
from .reports import archive, code_identity, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_artifact", type=Path)
    args = parser.parse_args()
    source = json.loads(args.runtime_artifact.read_text())
    data = corpus()
    by_text = {i["text"]: i for i in data["items"]}
    if source["corpus_sha256"] != sha(data):
        raise ValueError("wrong source corpus")
    records, summary = [], {}
    for original in source["records"]:
        pool = []
        for call in original["variants"]["raw_select"]["calls"]:
            if "result" not in call:
                raise ValueError("cannot reconstruct a failed selection")
            for i, candidate in enumerate(call["request"]["state"]["candidates"]):
                pool.append(
                    (by_text[candidate["text"]], call["result"]["answers"][str(i)]["value"])
                )
        rankings = {
            "source_first": sorted(pool, key=lambda pair: pair[0]["kind"] != "evidence"),
            "contribution": sorted([p for p in pool if p[1] >= 0.7], key=lambda pair: -pair[1]),
            "contribution_source_first": sorted(
                [p for p in pool if p[1] >= 0.7],
                key=lambda pair: (pair[0]["kind"] != "evidence", -pair[1]),
            ),
        }
        record = {"query": original["query"], "variants": {}}
        for budget in (80, 160, 320):
            for name, ranking in rankings.items():
                ids, used = [], 0
                for item, _ in ranking:
                    cost = _token_count(item["text"]) + 6
                    if used + cost <= budget and len(ids) < 30:
                        ids.append(item["id"])
                        used += cost
                record["variants"][f"{name}_{budget}"] = {
                    "ids": ids,
                    "tokens": used,
                    "usage": {
                        "provider_ms_sum": 0,
                        "input_tokens": 0,
                        "new_input_tokens": 0,
                        "errors": 0,
                    },
                }
        records.append(record)
    for variant in records[0]["variants"]:
        summary[variant] = metrics(records, data, variant)
    folder = archive(
        {
            "corpus_sha256": sha(data),
            "split": "opened-runtime-budget-diagnostic",
            "source_artifact_sha256": sha(source),
            "provenance": code_identity(),
            "metrics": summary,
            "records": records,
            "thresholds": {"contribution": 0.7},
        },
        root=Path("data/experiments"),
        name="context-source-priority-and-budget",
        hypothesis="Compare simple source priority against semantic selection at three fixed budgets.",
        decision="observe",
        data_class="synthetic",
        label_source="author-labeled; not independently reviewed",
        limitations=[
            "Reuses the exact runtime candidates and judgments; no independent new evidence.",
            "Zero recorded cost means offline replay, not free original semantic inference.",
        ],
    )
    print(json.dumps(summary, indent=2))
    print(f"Archived: {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
