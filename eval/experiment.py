"""A/B harness for extractor variants.

Runs the *same* windows through several (model, prompt version) combinations and
reports them side by side. Nothing is written to `memories` or `judge_runs`: the
point is to compare before committing, and a variant that pollutes the store
cannot be compared twice.

    uv run python -m eval.experiment --windows 12 \
        --variant gemini-3.5-flash-lite:v2 \
        --variant gemini-3.5-flash-lite:v3

Windows are picked deterministically and every variant sees the identical set,
so differences are the variant's and not the sample's.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import extract, judge, prompts, providers, vectors  # noqa: E402
from memkit.config import get_settings  # noqa: E402
from memkit.db import connect  # noqa: E402
from memkit.embed import get_embedder  # noqa: E402


@dataclass
class Sample:
    """One window, plus everything a prompt might want to know about it."""

    session_id: str
    messages: list[Any]
    candidates: list[dict[str, Any]]
    project: str | None
    session_date: str | None
    agent_id: str | None

    @property
    def user_turns(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "user")


@dataclass
class VariantResult:
    model: str
    version: str
    ops: list[dict[str, Any]] = field(default_factory=list)
    empty_windows: int = 0
    windows: int = 0
    in_tokens: int = 0
    out_tokens: int = 0
    latency_ms: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.model}:{self.version}"

    @property
    def cost(self) -> float:
        return judge.cost_of(self.in_tokens, self.out_tokens, model=self.model)


def pick_samples(
    conn, client, embedder, *, owner_id: str, count: int, window_size: int
) -> list[Sample]:
    """Deterministic sample of windows that actually contain user turns.

    Assistant-only windows are excluded: they cannot produce a fact about the
    user, so measuring a variant on them measures nothing. Sessions are taken in
    id order and one window per session, for spread across projects rather than
    a deep dive into whichever session happens to be longest.
    """
    sessions = conn.execute(
        """SELECT s.id, s.agent_id, s.meta,
                  MIN(m.id) first_id, MIN(m.created_at) started
             FROM sessions s JOIN messages m ON m.session_id = s.id
            WHERE m.role = 'user' AND length(m.content) >= 40
            GROUP BY s.id
            HAVING COUNT(*) >= 2
            ORDER BY s.id"""
    ).fetchall()

    samples: list[Sample] = []
    for row in sessions:
        if len(samples) >= count:
            break
        first_user = conn.execute(
            """SELECT MIN(id) i FROM messages
                WHERE session_id = ? AND role = 'user' AND length(content) >= 40""",
            (row["id"],),
        ).fetchone()["i"]
        if first_user is None:
            continue
        # A few assistant turns of lead-in, then the window, mirroring what the
        # real pipeline assembles after a fast-forward.
        start = max(1, first_user - extract.CONTEXT_LEAD)
        msgs = conn.execute(
            """SELECT id, role, content, created_at FROM messages
                WHERE session_id = ? AND id >= ? ORDER BY id LIMIT ?""",
            (row["id"], start, window_size),
        ).fetchall()
        if not any(m["role"] == "user" for m in msgs):
            continue

        project = None
        if row["meta"]:
            import json

            try:
                project = (json.loads(row["meta"]) or {}).get("project")
            except (ValueError, TypeError):
                project = None

        samples.append(
            Sample(
                session_id=row["id"],
                messages=list(msgs),
                candidates=extract.find_candidates(
                    client, embedder, window=list(msgs), owner_id=owner_id
                ),
                project=project,
                session_date=(row["started"] or "")[:10] or None,
                agent_id=row["agent_id"],
            )
        )
    return samples


def load_profile(conn, owner_id: str, limit: int = 12) -> list[dict[str, Any]]:
    """Top user-scope facts by importance -- the stable 'who is this' block."""
    rows = conn.execute(
        """SELECT text, type, importance FROM memories
            WHERE owner_id = ? AND status = 'active' AND scope = 'user'
            ORDER BY importance DESC, updated_at DESC LIMIT ?""",
        (owner_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def run_variant(
    samples: list[Sample],
    *,
    model: str,
    version: str,
    profile_facts: list[dict[str, Any]],
    gemini_api_key: str,
    anthropic_api_key: str,
    today: str,
    verbose: bool = False,
) -> VariantResult:
    res = VariantResult(model=model, version=version)
    profile = prompts.render_profile(profile_facts)

    for i, s in enumerate(samples, 1):
        prompt = prompts.render(
            version,
            today=today,
            window=judge.render_window(s.messages),
            candidates=judge.render_candidates(s.candidates),
            project=s.project,
            session_date=s.session_date,
            profile=profile,
            agent_id=s.agent_id,
        )
        t0 = time.perf_counter()
        try:
            out = providers.call(
                model=model,
                prompt=prompt,
                gemini_api_key=gemini_api_key,
                anthropic_api_key=anthropic_api_key,
            )
        except Exception as exc:  # noqa: BLE001
            res.errors.append(f"{type(exc).__name__}: {exc}")
            res.windows += 1
            continue
        res.latency_ms.append(int((time.perf_counter() - t0) * 1000))
        res.windows += 1
        res.in_tokens += out.input_tokens
        res.out_tokens += out.output_tokens
        if out.error:
            res.errors.append(out.error)
            continue

        # Validate exactly as production does: Op.parse is the real gate.
        parsed = [op for op in (judge.Op.parse(r) for r in out.operations) if op]
        if not parsed:
            res.empty_windows += 1
        for op in parsed:
            res.ops.append(
                {
                    "op": op.op, "text": op.text or "", "type": op.type,
                    "scope": op.scope, "importance": op.importance,
                    "session": s.session_id, "project": s.project,
                }
            )
        print(f"    [{res.label}] {i}/{len(samples)} ops={len(parsed)}",
              end="\r", flush=True)
        if verbose and parsed:
            print()
            for op in parsed:
                print(f"       {op.op} {op.type}/{op.scope} imp={op.importance} "
                      f"[{len(op.text or '')}c] {op.text}")
    print(" " * 70, end="\r")
    return res


def report(results: list[VariantResult]) -> None:
    print("\n" + "=" * 100)
    # Absolute user-scope count, not just the share. A variant that doubles
    # total recall dilutes the percentage while finding exactly as many facts
    # about the person -- reading the ratio alone points at the wrong winner.
    print(f"{'variant':<34} {'ops':>4} {'ops/win':>8} {'empty':>7} "
          f"{'user':>5} {'proj':>5} {'task':>5} "
          f"{'medlen':>7} {'>200c':>6} {'imps':>5} {'lat':>7} {'$/win':>8}")
    print("-" * 100)
    for r in results:
        lens = [len(o["text"]) for o in r.ops] or [0]
        scopes = Counter(o["scope"] for o in r.ops)
        imps = {o["importance"] for o in r.ops}
        lat = statistics.median(r.latency_ms) if r.latency_ms else 0
        print(f"{r.label:<34} {len(r.ops):>4} {len(r.ops)/max(1,r.windows):>8.2f} "
              f"{r.empty_windows:>3}/{r.windows:<3} "
              f"{scopes.get('user', 0):>5} {scopes.get('project', 0):>5} "
              f"{scopes.get('task', 0):>5} "
              f"{statistics.median(lens):>7.0f} "
              f"{sum(1 for x in lens if x > 200):>6} "
              f"{len(imps):>5} {lat:>6.0f}ms "
              f"{r.cost/max(1,r.windows):>8.5f}")
    print("-" * 100)
    print("ops/win = facts per window (recall)  |  empty = windows yielding nothing")
    print("medlen  = median fact length, chars  |  >200c = facts over the prompt's cap")
    print("user/proj/task = facts per scope, absolute  |  imps = distinct importance values")

    for r in results:
        if r.errors:
            uniq = Counter(e[:90] for e in r.errors)
            print(f"\n  {r.label} errors ({len(r.errors)}):")
            for msg, n in uniq.most_common(3):
                print(f"    x{n} {msg}")

    print("\n" + "=" * 100)
    for r in results:
        print(f"\n### {r.label} — {len(r.ops)} facts")
        for o in sorted(r.ops, key=lambda x: -(x["importance"] or 0)):
            scope = o["scope"] + (f"/{o['project']}" if o["scope"] != "user" else "")
            print(f"  imp={o['importance']:.2f} {str(o['type']):<10} {scope:<22} "
                  f"[{len(o['text']):>3}c] {o['text'][:110]}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="experiment")
    ap.add_argument("--windows", type=int, default=10)
    ap.add_argument("--window-size", type=int, default=extract.WINDOW_SIZE)
    ap.add_argument(
        "--variant", action="append", default=[],
        help="model:version, repeatable (e.g. gemini-3.5-flash-lite:v3)",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    variants = [v.split(":", 1) for v in args.variant] or [
        ["gemini-3.5-flash-lite", "v2"],
        ["gemini-3.5-flash-lite", "v3"],
    ]

    s = get_settings()
    conn = connect(s.db_path)
    client = vectors.get_client(s.qdrant_url)
    embedder = get_embedder()

    samples = pick_samples(
        conn, client, embedder, owner_id=s.owner_id,
        count=args.windows, window_size=args.window_size,
    )
    profile_facts = load_profile(conn, s.owner_id)
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    print(f"windows: {len(samples)}  (user turns per window: "
          f"{[x.user_turns for x in samples]})")
    print(f"projects: {sorted({x.project for x in samples if x.project})}")
    print(f"profile facts available: {len(profile_facts)}")
    est = sum(
        judge.cost_of(3000, 200, model=m) * len(samples) for m, _ in variants
    )
    print(f"variants: {[':'.join(v) for v in variants]}  ~${est:.3f} estimated\n")

    results = []
    for model, version in variants:
        results.append(
            run_variant(
                samples, model=model, version=version,
                profile_facts=profile_facts,
                gemini_api_key=s.gemini_api_key,
                anthropic_api_key=s.anthropic_api_key,
                today=today, verbose=args.verbose,
            )
        )
    report(results)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
