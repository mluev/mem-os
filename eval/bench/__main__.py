"""python -m eval.bench {download,run,report,compare} -- see eval/bench/README.md."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import datasets, pipeline, stats
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
    if args.rewrite and args.mode != "memories":
        # The server assembles raw passages without rewrites; the flag would be
        # recorded in the config while changing nothing.
        _log("--rewrite only applies to --mode memories; ignoring it")
        args.rewrite = False
    options = (
        {"include_adversarial": args.adversarial}
        if args.dataset == "locomo"
        else {"include_assistant": not args.no_assistant}
    )
    data_sha256 = hashlib.sha256(Path(args.data).read_bytes()).hexdigest()
    conversations = datasets.load(args.dataset, Path(args.data), **options)
    # The whole dataset's category mix, before sampling: what weighted_accuracy
    # reweights a stratified sample back to.
    category_counts = stats.category_counts(conversations)
    source = None
    if args.source_run:
        source = pipeline.Run.open(args.source_run, Path(args.runs))
        theirs = source.state.get("config") or {}
        if (theirs.get("dataset"), theirs.get("data_sha256")) != (args.dataset, data_sha256):
            _log(f"--source-run {args.source_run} measured a different dataset file; refusing")
            return 2
        ingested = set(source.state["conversations"])
        missing = sum(1 for c in conversations if c.conversation_id not in ingested)
        if missing:
            _log(f"skipping {missing} conversations the source run never ingested")
        conversations = [c for c in conversations if c.conversation_id in ingested]
    if args.categories:
        wanted = set(args.categories.split(","))
        for conversation in conversations:
            conversation.questions = [q for q in conversation.questions if q.category in wanted]
        conversations = [c for c in conversations if c.questions]
    if args.sample:
        stats.sample(conversations, stats.parse_sample(args.sample), args.seed)
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
    if source is not None:
        pipeline.adopt(run, source)
    config = pipeline.Config(
        dataset=args.dataset,
        mode=args.mode,
        budget_tokens=args.budget,
        limit=args.results,
        rewrite=args.rewrite,
        policy=args.policy,
        answer_model=args.answer_model,
        judge_model=args.judge_model,
        workers=args.workers,
        dream=args.dream,
        budget_usd=args.budget_usd,
    )
    run.state["config"] = {
        **config.as_dict(),
        # Which bytes were measured: the dataset URLs track a branch.
        "data_sha256": data_sha256,
        "category_counts": category_counts,
        "sample": args.sample,
        "seed": args.seed,
        "source_run": args.source_run or None,
    }
    run.save()
    _log(
        f"run {run.run_id}: {len(conversations)} conversations, "
        f"{sum(len(c.questions) for c in conversations)} questions"
    )
    with httpx.Client(base_url=args.url, timeout=300) as http:
        memkit = Memkit(http, admin_key=args.admin_key, run_id=run.run_id)
        # What the server ran, recorded next to what it scored.
        run.state["config"]["server"] = memkit.server_config()
        before = memkit.spend()
        pipeline.ingest(run, memkit, conversations, _log, dream=args.dream)
        ingested = memkit.spend()
        questions = [q for c in conversations for q in c.questions]
        pipeline.evaluate(run, memkit, config, questions, _keys(), _log)
        spend = run.state.setdefault("spend", {})
        # Server-side spend on this deployment while the run was going: a
        # shared instance will include other traffic, a dedicated one will not.
        spend["server_ingest"] = round(
            spend.get("server_ingest", 0.0) + max(0.0, ingested - before), 4
        )
        spend["server_search"] = round(
            spend.get("server_search", 0.0) + max(0.0, memkit.spend() - ingested), 4
        )
        run.save()
    print(json.dumps(pipeline.report(run), indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    print(json.dumps(pipeline.report(pipeline.Run.open(args.run_id, Path(args.runs))), indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    root = Path(args.runs)
    result = pipeline.compare(
        pipeline.Run.open(args.baseline, root), pipeline.Run.open(args.candidate, root)
    )
    print(json.dumps(result, indent=2))
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
    run.add_argument(
        "--no-assistant",
        action="store_true",
        help="leave out LongMemEval single-session-assistant (answerable only from prompt v12)",
    )
    run.add_argument(
        "--sample",
        default="",
        help="questions per category, e.g. '*=50,single-session-assistant=15'",
    )
    run.add_argument("--seed", type=int, default=1, help="which questions --sample picks")
    run.add_argument(
        "--source-run",
        default="",
        help="search again over a previous run's ingested users instead of ingesting",
    )
    run.add_argument(
        "--dream", action="store_true", help="dream each conversation until caught up first"
    )
    run.add_argument(
        "--budget-usd", type=float, default=0.0, help="ceiling on answer+judge spend (0: none)"
    )
    run.add_argument("--mode", choices=["memories", "hybrid", "raw"], default="memories")
    run.add_argument("--budget", type=int, default=4000, help="context tokens per question")
    run.add_argument("--results", type=int, default=30, help="search result limit")
    run.add_argument("--rewrite", action="store_true", help="search with query rewrites")
    run.add_argument(
        "--policy", default="", help="retrieval policy, e.g. core-retrieval-v2 (default: server's)"
    )
    run.add_argument("--answer-model", default="gemini-3.5-flash")
    run.add_argument("--judge-model", default="gemini-3.5-flash")
    run.add_argument("--workers", type=int, default=4)
    run.set_defaults(func=cmd_run)

    show = commands.add_parser("report", help="summarise a run")
    show.add_argument("--run-id", required=True)
    show.add_argument("--runs", default=str(pipeline.DEFAULT_RUNS))
    show.set_defaults(func=cmd_report)

    versus = commands.add_parser("compare", help="paired difference between two runs")
    versus.add_argument("baseline")
    versus.add_argument("candidate")
    versus.add_argument("--runs", default=str(pipeline.DEFAULT_RUNS))
    versus.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    if args.command == "run" and not args.admin_key:
        parser.error("--admin-key (or MEMKIT_ADMIN_KEY) is required to create benchmark users")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
