"""Command line entry points: serve, import, bench, reindex, eval."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import store, vectors
from .config import get_settings
from .db import connect, ensure_owner, ensure_session, init_db, transaction
from .embed import get_embedder
from .importers.claude_code import ImportStats, iter_turns

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
)
# One line per Qdrant upsert and per HuggingFace HEAD drowns out the progress
# output that actually matters.
for _noisy in ("httpx", "httpcore", "sentence_transformers", "transformers"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger("memkit.cli")


def judge_models() -> list[str]:
    from . import judge

    return list(judge.MODELS)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    s = get_settings()
    uvicorn.run("memkit.api:app", host=s.host, port=s.port, reload=args.reload)
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """Phase-0 gate: one phrase must embed in under 100 ms on MPS."""
    result = get_embedder().benchmark()
    print(json.dumps(result, indent=2))
    median = result["median_ms"]
    if result["dim"] != 1024:
        print(f"FAIL: expected dim 1024, got {result['dim']}", file=sys.stderr)
        return 1
    if median < 100:
        print(f"PASS: {median} ms median on {result['device']}")
        return 0
    if median < 300:
        print(f"WARN: {median} ms median -- above the 100 ms target but usable")
        return 0
    print(f"FAIL: {median} ms median exceeds the 300 ms ceiling", file=sys.stderr)
    return 1


def cmd_import_claude_code(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not root.exists():
        print(f"no such directory: {root}", file=sys.stderr)
        return 1

    stats = ImportStats()
    turns = iter_turns(root, stats)
    print(stats.render())

    users = [t for t in turns if t.role == "user"]
    print(
        f"\nclassified: {len(turns)} turns "
        f"({len(users)} user, {len(turns) - len(users)} assistant) "
        f"across {len({t.session_id for t in turns})} sessions, "
        f"{len({t.project for t in users})} projects"
    )
    if args.dry_run:
        print("\ndry run: nothing written")
        return 0

    s = get_settings()
    init_db(s.db_path)
    conn = connect(s.db_path)
    client = vectors.get_client(s.qdrant_url)
    vectors.ensure_collections(client)
    embedder = get_embedder()

    if args.limit:
        turns = turns[: args.limit]

    inserted, deduped, new_ids = 0, 0, []
    with transaction(conn):
        ensure_owner(conn, s.owner_id, s.owner_name)
        for turn in turns:
            # Session metadata carries the project so search results can be
            # filtered by it. cwd gives this for free; no guessing required.
            ensure_session(
                conn, turn.session_id, s.owner_id, "claude-code", turn.created_at
            )
            conn.execute(
                "UPDATE sessions SET meta = ? WHERE id = ? AND meta IS NULL",
                (json.dumps({"project": turn.project, "git_branch": turn.git_branch}),
                 turn.session_id),
            )
            mid, dedup = store.add_message(
                conn,
                session_id=turn.session_id,
                owner_id=s.owner_id,
                agent_id="claude-code",
                role=turn.role,
                content=turn.text,
                created_at=turn.created_at,
                external_source="claude-code",
                external_id=turn.external_id,
            )
            if dedup:
                deduped += 1
            else:
                inserted += 1
                if turn.indexable:
                    new_ids.append(mid)

    print(f"\nsqlite: {inserted} inserted, {deduped} already present")

    indexed = 0
    for i in range(0, len(new_ids), 256):
        indexed += store.index_raw(conn, client, embedder, new_ids[i : i + 256])
        print(f"  indexed {indexed}/{len(new_ids)}", end="\r", flush=True)
    print(f"\nqdrant: {indexed} raw turns indexed")
    conn.close()
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    """Run the extractor over already-imported history.

    Always dry-run first. The estimate is derived from measured token usage once
    any real calls exist, so the first estimate is coarser than later ones.
    """
    from . import extract, judge

    s = get_settings()
    conn = connect(s.db_path)
    pending = conn.execute(
        """SELECT session_id, COUNT(*) n FROM messages
            WHERE processed = 0 GROUP BY session_id ORDER BY MIN(id)"""
    ).fetchall()
    model = args.model or s.judge_model
    estimate = judge.estimate_backfill(conn, model=model)
    total_msgs = estimate["messages"]
    windows = estimate["windows"]
    per_in = estimate["input_tokens_per_call"]
    per_out = estimate["output_tokens_per_call"]
    basis = estimate["basis"]
    est = estimate["estimated_cost_usd"]
    p_in, p_out = judge.price_per_mtok(model)
    print(f"model            {model}  (${p_in}/${p_out} per Mtok, {judge.provider_of(model)})")
    print(f"sessions         {len(pending)}")
    print(f"messages pending {total_msgs}")
    print(f"windows (calls)  {windows}")
    print(f"tokens/call      ~{per_in:.0f} in / ~{per_out:.0f} out   [{basis}]")
    print(f"estimated cost   ${est:.2f}")
    print(f"month spend      ${judge.month_spend_usd(conn):.4f} "
          f"of ${s.monthly_cost_limit_usd} limit")

    if args.dry_run:
        print("\ndry run: no calls made")
        return 0
    which = judge.provider_of(model)
    if which == "gemini" and not (s.gemini_api_key or s.vertex_project):
        print("\nGEMINI_API_KEY is not set. Add one line to .env:\n"
              "  GEMINI_API_KEY=your-ai-studio-key\n"
              "(uses the Gemini Developer API; GOOGLE_API_KEY and "
              "GOOGLE_VERTEX_API_KEY are also read.)",
              file=sys.stderr)
        return 1
    if which == "anthropic" and not s.anthropic_api_key:
        print("\nANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 1

    client = vectors.get_client(s.qdrant_url)
    embedder = get_embedder()
    done = extract.ExtractionOutcome()
    calls = 0
    limit = args.max_calls or windows

    for row in pending:
        while calls < limit:
            remaining_before = extract.messages_since_last(conn, row["session_id"])
            with transaction(conn):
                outcome = extract.run_extraction(
                    conn, client, embedder,
                    session_id=row["session_id"], owner_id=s.owner_id,
                    agent_id="claude-code", api_key=s.anthropic_api_key,
                    gemini_api_key=s.gemini_api_key,
                    project=s.vertex_project, location=s.vertex_location,
                    monthly_limit_usd=s.monthly_cost_limit_usd, force=True,
                    model=model,
                )
            done.fast_forwarded += outcome.fast_forwarded
            done.abandoned += outcome.abandoned
            if outcome.judge_run_id is None and not outcome.error:
                # Nothing happened at all: session drained. A fast-forward or an
                # abandoned window is progress, so keep going in those cases.
                if outcome.fast_forwarded == 0 and outcome.abandoned == 0:
                    break
                continue
            calls += 1
            if (
                outcome.error
                and extract.messages_since_last(conn, row["session_id"])
                >= remaining_before
            ):
                # The call failed and left the backlog exactly where it was, so
                # the next iteration would buy the same window again. Move on and
                # let MAX_WINDOW_ATTEMPTS retire it.
                print(f"\nno progress on {row['session_id']}: {outcome.error}",
                      file=sys.stderr)
                break
            done.added += outcome.added
            done.updated += outcome.updated
            done.deleted += outcome.deleted
            done.skipped += outcome.skipped
            done.cost_usd += outcome.cost_usd
            done.input_tokens += outcome.input_tokens
            done.output_tokens += outcome.output_tokens
            print(
                f"  calls={calls}/{limit} +{done.added} ~{done.updated} "
                f"-{done.deleted} ?{done.skipped} ff={done.fast_forwarded} "
                f"${done.cost_usd:.4f}",
                end="\r", flush=True,
            )
            if outcome.error:
                print(f"\nstopped: {outcome.error}", file=sys.stderr)
                calls = limit
                break
        if calls >= limit:
            break

    print()
    print(json.dumps(done.as_dict(), indent=2))
    if calls:
        print(f"per call: {done.input_tokens // calls} in / "
              f"{done.output_tokens // calls} out / "
              f"${done.cost_usd / calls:.5f}")
    conn.close()
    return 0


def cmd_judge_runs(args: argparse.Namespace) -> int:
    """Read judge_runs by eye.

    docs/06-roadmap.md calls this the most useful and most boring part of the
    project. It is right: this is where a bad prompt becomes visible.
    """
    s = get_settings()
    conn = connect(s.db_path)
    rows = conn.execute(
        """SELECT id, created_at, error, input_tokens, output_tokens, cost_usd,
                  latency_ms, output_json, model, prompt_version
             FROM judge_runs ORDER BY id DESC LIMIT ?""",
        (args.limit,),
    ).fetchall()
    for r in reversed(rows):
        head = (f"#{r['id']} {r['created_at']} {r['prompt_version']} {r['model']} "
                f"{r['latency_ms']}ms {r['input_tokens']}->{r['output_tokens']}tok "
                f"${r['cost_usd']:.5f}")
        print(head)
        if r["error"]:
            print(f"    ERROR {r['error']}")
            continue
        try:
            ops = (json.loads(r["output_json"]) or {}).get("operations", [])
        except (ValueError, TypeError):
            ops = []
        if not ops:
            print("    (no operations — correct and common)")
        for o in ops:
            print(f"    {o.get('op'):<7} {str(o.get('type') or '-'):<11} "
                  f"imp={o.get('importance')} {str(o.get('text'))[:88]!r}")
            print(f"            why: {str(o.get('reason'))[:96]}")
    conn.close()
    return 0


def cmd_consolidate(args: argparse.Namespace) -> int:
    """Nightly consolidation, run by hand or by launchd.

    Dry-run prints the clusters it would send to the model and costs nothing, which
    is the only sane way to pick a threshold.
    """
    from . import consolidate as consolidator
    from . import judge, vectors

    s = get_settings()
    conn = connect(s.db_path)
    client = vectors.get_client(s.qdrant_url)
    embedder = get_embedder()
    threshold = args.threshold or s.consolidate_cosine

    print(f"owner        {s.owner_id}")
    print(f"threshold    {threshold}")
    print(f"stale days   {s.consolidate_stale_days} (importance -{s.consolidate_demotion})")
    print(f"model        {args.model or s.judge_model}")
    print(f"month spend  ${judge.month_spend_usd(conn):.4f} of ${s.monthly_cost_limit_usd}")

    with transaction(conn):
        outcome = consolidator.run(
            conn, client, embedder,
            owner_id=s.owner_id,
            threshold=threshold,
            stale_days=s.consolidate_stale_days,
            demotion=s.consolidate_demotion,
            model=args.model or s.judge_model,
            monthly_limit_usd=s.monthly_cost_limit_usd,
            anthropic_api_key=s.anthropic_api_key,
            gemini_api_key=s.gemini_api_key,
            project=s.vertex_project,
            location=s.vertex_location,
            dry_run=args.dry_run,
        )

    print()
    print(f"expired      {outcome.expired}")
    print(f"demoted      {outcome.demoted}")
    print(f"clusters     {outcome.clusters}")
    if args.dry_run:
        for merge in outcome.merges:
            print(f"\n  would merge {len(merge.ids)} x {merge.type}:")
            for text in merge.texts:
                print(f"    - {text[:110]}")
        print("\ndry run: no calls made, nothing written")
    else:
        print(f"merged       {outcome.merged}")
        print(f"declined     {outcome.declined}  (model judged them distinct)")
        print(f"superseded   {outcome.superseded}")
        print(f"cost         ${outcome.cost_usd:.5f}")
        for merge in outcome.merges:
            if merge.text:
                print(f"\n  {len(merge.ids)} -> {merge.survivor_id[:8] if merge.survivor_id else '?'}")
                for text in merge.texts:
                    print(f"    was: {text[:100]}")
                print(f"    now: {merge.text[:100]}")
            elif not merge.error:
                print(f"\n  declined: {merge.reason[:100]}")
    for err in outcome.errors:
        print(f"  error: {err}", file=sys.stderr)
    conn.close()
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    s = get_settings()
    conn = connect(s.db_path)
    client = vectors.get_client(s.qdrant_url)
    counts = store.reindex(conn, client, get_embedder())
    print(json.dumps(counts, indent=2))
    conn.close()
    return 0


def cmd_install_hermes(args: argparse.Namespace) -> int:
    """Install the Hermes MemoryProvider into $HERMES_HOME/plugins/memkit.

    The source lives in this repository so it is versioned and tested with the
    service. Hermes scans `$HERMES_HOME/plugins/<name>/` for user-installed
    providers -- not `plugins/memory/<name>/`, which is where its own bundled ones
    live and would mean editing the hermes-agent package.
    """
    import shutil

    source = Path(__file__).resolve().parents[2] / "integrations" / "hermes" / "memkit"
    if not source.is_dir():
        print(f"provider source not found at {source}", file=sys.stderr)
        return 1

    home = Path(args.hermes_home or os.environ.get("HERMES_HOME") or "~/.hermes")
    home = home.expanduser()
    if not home.is_dir():
        print(f"no HERMES_HOME at {home}", file=sys.stderr)
        return 1
    target = home / "plugins" / "memkit"

    if target.exists() and not args.force:
        print(f"{target} already exists; pass --force to overwrite", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    # Copy rather than symlink: a symlink into a git checkout means a branch switch
    # silently changes what Hermes loads.
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))

    s = get_settings()
    print(f"installed {source.name} -> {target}")
    print("\nNow add to $HERMES_HOME/config.yaml:\n")
    print("memory:")
    print("  provider: memkit")
    print("plugins:")
    print("  memkit:")
    print(f"    base_url: http://{s.host}:{s.port}")
    print(f"    owner_id: {s.owner_id}")
    print("    budget_tokens: 800")
    print("    send_tool_results: false")
    print(f"    db_path: {s.db_path.resolve()}")
    print("\nAnd export the key Hermes will send:")
    print("  export MEMKIT_API_KEY=...        # same value as MEMKIT_API_KEY here")
    print("\nThen: hermes memory setup   (or restart Hermes)")
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    # eval/ is a repo-level harness, not part of the installed package, so it
    # is reached through the working directory rather than the wheel.
    queries = Path(args.queries)
    root = queries.resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from eval.run import run_eval

    return run_eval(queries, limit=args.limit, target=args.target)


def main() -> int:
    p = argparse.ArgumentParser(prog="memkit")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("serve", help="run the HTTP service")
    sp.add_argument("--reload", action="store_true")
    sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("bench", help="measure embedding latency")
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser("import-claude-code", help="import ~/.claude transcripts")
    sp.add_argument("--root", default="~/.claude/projects")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--limit", type=int, default=0)
    sp.set_defaults(func=cmd_import_claude_code)

    sp = sub.add_parser("backfill", help="run the extractor over imported history")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--max-calls", type=int, default=0,
                    help="stop after N judge calls (0 = no cap)")
    sp.add_argument("--model", default=None,
                    help=f"judge model (default from settings; known: {', '.join(judge_models())})")
    sp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("judge-runs", help="read recent judge runs by eye")
    sp.add_argument("--limit", type=int, default=10)
    sp.set_defaults(func=cmd_judge_runs)

    sp = sub.add_parser("consolidate", help="nightly consolidation (stage 4)")
    sp.add_argument("--dry-run", action="store_true",
                    help="print clusters without calling the model")
    sp.add_argument("--threshold", type=float, default=None,
                    help="cluster cosine (default from settings)")
    sp.add_argument("--model", default=None)
    sp.set_defaults(func=cmd_consolidate)

    sp = sub.add_parser("reindex", help="rebuild Qdrant from SQLite")
    sp.set_defaults(func=cmd_reindex)

    sp = sub.add_parser("install-hermes", help="install the Hermes memory provider")
    sp.add_argument("--hermes-home", default=None,
                    help="default: $HERMES_HOME or ~/.hermes")
    sp.add_argument("--force", action="store_true", help="overwrite an existing install")
    sp.set_defaults(func=cmd_install_hermes)

    sp = sub.add_parser("eval", help="run the retrieval eval")
    sp.add_argument("--queries", default="eval/queries.yaml")
    sp.add_argument("--limit", type=int, default=10)
    sp.add_argument("--target", choices=("raw", "memories"), default="raw",
                    help="raw turns (stage-1 baseline) or extracted facts")
    sp.set_defaults(func=cmd_eval)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
