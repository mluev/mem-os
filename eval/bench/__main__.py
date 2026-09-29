"""python -m eval.bench {download,run,report} -- see eval/bench/README.md."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import datasets, pipeline
from .client import Memkit


def _log(message: str) -> None:
    print(f"{datetime.now(UTC):%H:%M:%S} {message}", file=sys.stderr, flush=True)


def _keys() -> dict[str, str]:
    return {
        "gemini": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", ""),
        "anthropic": os.environ.get("ANTHROPIC_API_KEY", ""),
        "project": os.environ.get("VERTEX_PROJECT", ""),
        "location": os.environ.get("VERTEX_LOCATION", ""),
    }


def cmd_download(args: argparse.Namespace) -> int:
    url = datasets.LOCOMO_URL if args.dataset == "locomo" else datasets.LONGMEMEVAL_URL
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=600) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    _log(f"saved {url} to {target}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    conversations = datasets.load(
        args.dataset,
        Path(args.data),
        **({"include_adversarial": args.adversarial} if args.dataset == "locomo" else {}),
    )
    if args.categories:
        wanted = set(args.categories.split(","))
        for conversation in conversations:
            conversation.questions = [q for q in conversation.questions if q.category in wanted]
        conversations = [c for c in conversations if c.questions]
    if args.limit:
        # Limit questions, and only ingest the conversations they need.
        kept, count = [], 0
        for conversation in conversations:
            if count >= args.limit:
                break
            conversation.questions = conversation.questions[: args.limit - count]
            count += len(conversation.questions)
            kept.append(conversation)
        conversations = kept
    run = pipeline.Run.open(args.run_id or uuid.uuid4().hex[:8], Path(args.runs))
    config = pipeline.Config(
        dataset=args.dataset,
        mode=args.mode,
        budget_tokens=args.budget,
        limit=args.results,
        rewrite=args.rewrite,
        answer_model=args.answer_model,
        judge_model=args.judge_model,
        workers=args.workers,
    )
    run.state["config"] = config.as_dict()
    run.save()
    _log(
        f"run {run.run_id}: {len(conversations)} conversations, "
        f"{sum(len(c.questions) for c in conversations)} questions"
    )
    with httpx.Client(base_url=args.url, timeout=300) as http:
        memkit = Memkit(http, admin_key=args.admin_key, run_id=run.run_id)
        pipeline.ingest(run, memkit, conversations, _log)
        questions = [q for c in conversations for q in c.questions]
        pipeline.evaluate(run, memkit, config, questions, _keys(), _log)
    print(json.dumps(pipeline.report(run), indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    print(json.dumps(pipeline.report(pipeline.Run.open(args.run_id, Path(args.runs))), indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m eval.bench")
    commands = parser.add_subparsers(dest="command", required=True)

    download = commands.add_parser("download", help="fetch a benchmark dataset")
    download.add_argument("dataset", choices=["locomo", "longmemeval"])
    download.add_argument("--out", required=True)
    download.set_defaults(func=cmd_download)

    run = commands.add_parser("run", help="ingest, search, answer and judge")
    run.add_argument("--dataset", choices=["locomo", "longmemeval"], required=True)
    run.add_argument("--data", required=True, help="path to the dataset JSON")
    run.add_argument("--url", default=os.environ.get("MEMKIT_BASE_URL", "http://127.0.0.1:8077"))
    run.add_argument("--admin-key", default=os.environ.get("MEMKIT_ADMIN_KEY", ""))
    run.add_argument("--run-id")
    run.add_argument("--runs", default=str(pipeline.DEFAULT_RUNS))
    run.add_argument("--limit", type=int, default=0, help="questions to evaluate")
    run.add_argument("--categories", default="", help="comma-separated category names")
    run.add_argument("--adversarial", action="store_true", help="LoCoMo category 5 too")
    run.add_argument("--mode", choices=["memories", "hybrid", "raw"], default="memories")
    run.add_argument("--budget", type=int, default=4000, help="context tokens per question")
    run.add_argument("--results", type=int, default=20, help="search result limit")
    run.add_argument("--rewrite", action="store_true", help="search with query rewrites")
    run.add_argument("--answer-model", default="gemini-3.5-flash")
    run.add_argument("--judge-model", default="gemini-3.5-flash")
    run.add_argument("--workers", type=int, default=4)
    run.set_defaults(func=cmd_run)

    show = commands.add_parser("report", help="summarise a run")
    show.add_argument("--run-id", required=True)
    show.add_argument("--runs", default=str(pipeline.DEFAULT_RUNS))
    show.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    if args.command == "run" and not args.admin_key:
        parser.error("--admin-key (or MEMKIT_ADMIN_KEY) is required to create benchmark users")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
