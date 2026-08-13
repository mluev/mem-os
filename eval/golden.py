"""Score extractor variants against the golden set.

`experiment.py` measures what a variant *did* on the real corpus. This measures
whether it was *right*, against hand-written windows with a known answer.

    uv run python -m eval.golden \
        --variant gemini-3.5-flash-lite:v7

Scores, in the order they matter:

leak     credential values reaching the store. Any non-zero score fails outright;
         nothing else compensates.
recall   expected facts found. The extractor's core job.
fp       facts invented where the answer was "nothing" — assistant work logs,
         transient moods, a term the user asked about once. v1's whole failure
         mode, so it is scored separately from recall rather than averaged in.
context  of the facts found, how many copied only the applicable caller context.
imp      how many cleared the importance floor the case declares. Catches the
         everything-is-0.6 collapse that both v1 and v2 showed.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import jobs, judge, prompts, providers
from memkit.config import get_settings
from memkit.db import connect, ensure_owner, init_db, transaction, utcnow

GOLDEN = Path(__file__).parent / "golden" / "conversations.yaml"


@dataclass
class Case:
    id: str
    probes: str
    context: dict[str, str]
    messages: list[dict[str, str]]
    candidates: list[dict[str, Any]]
    expect: list[dict[str, Any]]
    reject: list[str]
    max_ops: int | None

    @classmethod
    def parse(cls, raw: dict[str, Any], index: int) -> Case:
        return cls(
            id=str(raw.get("id") or f"case{index}"),
            probes=str(raw.get("probes") or ""),
            context={str(k): str(v) for k, v in (raw.get("context") or {}).items()},
            messages=[
                {"id": i + 1, "role": role, "content": text}
                for i, (role, text) in enumerate(raw.get("messages") or [])
            ],
            candidates=list(raw.get("candidates") or []),
            expect=list(raw.get("expect") or []),
            reject=[str(p) for p in (raw.get("reject") or [])],
            max_ops=raw.get("max_ops"),
        )


@dataclass
class Score:
    model: str
    version: str
    expected = 0
    found = 0
    context_ok = 0
    context_checked = 0
    kind_ok = 0
    kind_checked = 0
    evidence_ok = 0
    evidence_checked = 0
    imp_ok = 0
    imp_checked = 0
    op_ok = 0
    op_checked = 0
    false_positives = 0
    leaks = 0
    over_emission = 0
    total_ops = 0
    in_tokens = 0
    out_tokens = 0
    latency: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    importances: list[float] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.model}:{self.version}"

    @property
    def recall(self) -> float:
        return self.found / self.expected if self.expected else 0.0

    @property
    def cost(self) -> float:
        return judge.cost_of(self.in_tokens, self.out_tokens, model=self.model)


def _match(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text or "", re.IGNORECASE))


def score_case(case: Case, ops: list[judge.Op], sc: Score) -> None:
    texts = [o.text or "" for o in ops]
    sc.total_ops += len(ops)
    sc.lengths.extend(len(t) for t in texts)
    sc.importances.extend(o.importance for o in ops if o.importance is not None)

    # Credential leaks first: a single one invalidates the run.
    for pattern in case.reject:
        for t in texts:
            if _match(pattern, t):
                if case.id == "credentials-must-not-leak":
                    sc.leaks += 1
                    sc.failures.append(f"{case.id}: LEAK {pattern!r} -> {t[:60]!r}")
                else:
                    sc.false_positives += 1
                    sc.failures.append(f"{case.id}: rejected {pattern!r} -> {t[:60]!r}")

    # Windows whose right answer is "nothing": every emitted fact is invented.
    if not case.expect and ops:
        sc.false_positives += len(ops)
        for t in texts:
            sc.failures.append(f"{case.id}: should have been empty -> {t[:70]!r}")

    for want in case.expect:
        sc.expected += 1
        hits = [o for o in ops if _match(str(want["text"]), o.text or "")]
        if not hits:
            sc.failures.append(f"{case.id}: MISSED {want['text']!r}")
            continue
        sc.found += 1
        best = hits[0]
        if "context" in want:
            sc.context_checked += 1
            if (best.context or {}) == want["context"]:
                sc.context_ok += 1
            else:
                sc.failures.append(
                    f"{case.id}: context {best.context!r}, wanted {want['context']!r} "
                    f"-> {(best.text or '')[:50]!r}"
                )
        if "kind" in want:
            sc.kind_checked += 1
            if best.kind == want["kind"]:
                sc.kind_ok += 1
            else:
                sc.failures.append(f"{case.id}: kind {best.kind!r}, wanted {want['kind']!r}")
        sc.evidence_checked += 1
        messages = {int(message["id"]): message for message in case.messages}
        citations_valid = bool(best.evidence)
        for citation in best.evidence or []:
            message = messages.get(int(citation["message_id"]))
            start = int(citation["start_char"])
            end = int(citation["end_char"])
            quote = str(citation.get("quote") or "")
            if message is not None and quote:
                first = message["content"].find(quote)
                if first >= 0 and message["content"].find(quote, first + 1) < 0:
                    start, end = first, first + len(quote)
            if (
                message is None
                or message["role"] != "user"
                or start < 0
                or end <= start
                or end > len(message["content"])
                or not message["content"][start:end].strip()
            ):
                citations_valid = False
        if citations_valid:
            sc.evidence_ok += 1
        else:
            sc.failures.append(f"{case.id}: missing or invalid exact user citation")
        if "min_importance" in want:
            sc.imp_checked += 1
            if (best.importance or 0) >= float(want["min_importance"]):
                sc.imp_ok += 1
            else:
                sc.failures.append(
                    f"{case.id}: importance {best.importance}, wanted >= {want['min_importance']}"
                )
        if "op" in want:
            sc.op_checked += 1
            if best.op == want["op"] and ("id" not in want or best.id == want["id"]):
                sc.op_ok += 1
            else:
                sc.failures.append(
                    f"{case.id}: got {best.op} id={best.id}, "
                    f"wanted {want['op']} id={want.get('id')}"
                )

    if case.max_ops is not None and len(ops) > case.max_ops:
        sc.over_emission += len(ops) - case.max_ops
        sc.failures.append(f"{case.id}: {len(ops)} ops, cap was {case.max_ops}")


def run(cases: list[Case], *, model: str, version: str, s, today: str, verbose: bool) -> Score:
    sc = Score(model=model, version=version)
    for i, case in enumerate(cases, 1):
        prompt = prompts.render(
            version,
            today=today,
            window=judge.render_window(case.messages),
            candidates=judge.render_candidates(case.candidates),
            context=json.dumps(case.context, ensure_ascii=False, sort_keys=True),
            session_date=today,
            # Deliberately empty: the golden set probes extraction from the
            # window alone. Profile effects are measured on the real corpus,
            # where the profile is real.
            profile="",
            agent_id="claude-code",
        )
        t0 = time.perf_counter()
        try:
            out = providers.call(
                model=model,
                prompt=prompt,
                gemini_api_key=s.gemini_api_key,
                anthropic_api_key=s.anthropic_api_key,
            )
        except Exception as exc:
            sc.errors.append(f"{case.id}: {type(exc).__name__}: {exc}")
            continue
        sc.latency.append(int((time.perf_counter() - t0) * 1000))
        sc.in_tokens += out.input_tokens
        sc.out_tokens += out.output_tokens
        if out.error:
            sc.errors.append(f"{case.id}: {out.error}")
            continue
        ops = [op for op in (judge.Op.parse(r) for r in out.operations) if op]
        score_case(case, ops, sc)
        print(f"    [{sc.label}] {i}/{len(cases)} {case.id}", end="\r", flush=True)
        if verbose:
            print()
            print(f"  --- {case.id} ({case.probes})")
            for op in ops:
                print(
                    f"      {op.op} {op.kind} context={op.context or {}} "
                    f"imp={op.importance} citations={len(op.evidence or [])} {op.text}"
                )
            if not ops:
                print("      (empty)")
    print(" " * 78, end="\r")
    return sc


def report(scores: list[Score], cases: list[Case]) -> None:
    print("\n" + "=" * 104)
    print(
        f"{'variant':<32} {'recall':>12} {'fp':>4} {'leak':>5} {'context':>8} "
        f"{'kind':>7} {'evidence':>8} {'imp':>7} {'op':>6} {'over':>5} {'$':>8}"
    )
    print("-" * 104)
    for sc in scores:
        context = f"{sc.context_ok}/{sc.context_checked}" if sc.context_checked else "-"
        kind = f"{sc.kind_ok}/{sc.kind_checked}" if sc.kind_checked else "-"
        evidence = f"{sc.evidence_ok}/{sc.evidence_checked}"
        imp = f"{sc.imp_ok}/{sc.imp_checked}" if sc.imp_checked else "-"
        op = f"{sc.op_ok}/{sc.op_checked}" if sc.op_checked else "-"
        print(
            f"{sc.label:<32} {sc.found:>3}/{sc.expected:<3} {sc.recall:>5.0%} "
            f"{sc.false_positives:>4} {sc.leaks:>5} {context:>8} {kind:>7} "
            f"{evidence:>8} {imp:>7} {op:>6} {sc.over_emission:>5} {sc.cost:>8.4f}"
        )
    print("-" * 104)
    print("recall found/expected  |  fp = facts invented where the answer was nothing")
    print("leak = credential values stored (any value fails the run)")
    print("context/kind/evidence/imp/op validate the v7 domain-neutral contract")

    for sc in scores:
        if sc.errors:
            print(f"\n  {sc.label} errors: {len(sc.errors)}")
            for e in sc.errors[:3]:
                print(f"    {e[:100]}")
        if sc.failures:
            print(f"\n  {sc.label} — {len(sc.failures)} failures:")
            for f in sc.failures[:14]:
                print(f"    {f[:112]}")


def _score_summary(score: Score) -> dict[str, Any]:
    return {
        "model": score.model,
        "version": score.version,
        "expected": score.expected,
        "found": score.found,
        "recall": score.recall,
        "false_positives": score.false_positives,
        "credential_leaks": score.leaks,
        "invalid_evidence": score.evidence_checked - score.evidence_ok,
        "context": [score.context_ok, score.context_checked],
        "kind": [score.kind_ok, score.kind_checked],
        "importance": [score.imp_ok, score.imp_checked],
        "operations": [score.op_ok, score.op_checked],
        "over_emission": score.over_emission,
        "input_tokens": score.in_tokens,
        "output_tokens": score.out_tokens,
        "cost_usd": score.cost,
        "errors": score.errors,
        "safety_passed": not score.errors
        and score.leaks == 0
        and score.evidence_ok == score.evidence_checked,
    }


def _winner(scores: list[Score]) -> str | None:
    safe = [score for score in scores if _score_summary(score)["safety_passed"]]
    if not safe:
        return None

    def correctness(score: Score) -> tuple[float, ...]:
        return (
            score.recall,
            -score.false_positives,
            score.context_ok / (score.context_checked or 1),
            score.kind_ok / (score.kind_checked or 1),
            score.imp_ok / (score.imp_checked or 1),
            score.op_ok / (score.op_checked or 1),
            -score.over_emission,
            -score.cost,
        )

    return max(safe, key=correctness).model


def _cost_ceiling(
    cases: list[Case], variants: list[list[str]], *, today: str
) -> tuple[float, dict[str, float]]:
    by_variant: dict[str, float] = {}
    for model, version in variants:
        ceiling = 0.0
        for case in cases:
            prompt = prompts.render(
                version,
                today=today,
                window=judge.render_window(case.messages),
                candidates=judge.render_candidates(case.candidates),
                context=json.dumps(case.context, ensure_ascii=False, sort_keys=True),
                session_date=today,
                profile="",
                agent_id="claude-code",
            )
            # One token per UTF-8 byte plus the provider's hard 4096-token output
            # cap is deliberately conservative and therefore safe to reserve.
            ceiling += judge.cost_of(len(prompt.encode("utf-8")), 4096, model=model)
        by_variant[f"{model}:{version}"] = ceiling
    return sum(by_variant.values()), by_variant


def _write_artifact(
    *, scores: list[Score], cases: list[Case], output_dir: Path, ceilings: dict[str, float]
) -> Path:
    summaries = [_score_summary(score) for score in scores]
    artifact: dict[str, Any] = {
        "kind": "paid-golden-v7",
        "created_at": utcnow(),
        "cases": len(cases),
        "case_ids": [case.id for case in cases],
        "scores": summaries,
        "selected_model": _winner(scores),
        "selection_order": ["safety", "correctness", "cost"],
        "both_failed": not any(summary["safety_passed"] for summary in summaries),
        "cost_ceiling_usd": sum(ceilings.values()),
        "variant_cost_ceilings_usd": ceilings,
        "actual_cost_usd": sum(score.cost for score in scores),
    }
    artifact["sha256"] = hashlib.sha256(
        json.dumps(artifact, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)
    path = output_dir / f"golden-v7-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(prog="golden")
    ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--file", default=str(GOLDEN))
    ap.add_argument("--only", default=None, help="run one case by id")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--schema-only", action="store_true")
    ap.add_argument("--budget-usd", type=float, default=10.0)
    ap.add_argument("--output-dir")
    args = ap.parse_args()

    raw = yaml.safe_load(Path(args.file).read_text(encoding="utf-8")) or []
    cases = [Case.parse(r, i) for i, r in enumerate(raw)]
    if args.only:
        cases = [c for c in cases if c.id == args.only]
    if not cases:
        print("no cases", file=sys.stderr)
        return 1
    forbidden = {"scope", "type", "holds_in_other_repos"}
    for raw_case in raw:
        for expected in raw_case.get("expect") or []:
            if forbidden & set(expected):
                print(f"{raw_case.get('id')}: retired expectation keys", file=sys.stderr)
                return 1
    if args.schema_only:
        for case in cases:
            prompts.render(
                prompts.DEFAULT_VERSION,
                today="2026-01-01",
                window=judge.render_window(case.messages),
                candidates=judge.render_candidates(case.candidates),
                context=json.dumps(case.context, sort_keys=True),
            )
        print(f"validated {len(cases)} v7 golden cases")
        return 0

    variants = [v.split(":", 1) for v in args.variant] or [
        ["gemini-3.5-flash-lite", prompts.DEFAULT_VERSION],
    ]
    s = get_settings()
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    ceiling, ceilings = _cost_ceiling(cases, variants, today=today)
    allowed = min(args.budget_usd, s.improvement_budget_usd)
    if ceiling > allowed + 1e-12:
        print(f"refusing paid run: ${ceiling:.4f} ceiling exceeds ${allowed:.2f}", file=sys.stderr)
        return 2
    init_db(s.db_path)
    conn = connect(s.db_path)
    ensure_owner(conn, s.owner_id, s.owner_name)
    conn.commit()
    program_spend = float(
        conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs WHERE kind LIKE 'improvement-%'"
        ).fetchone()[0]
    )
    if program_spend + ceiling > allowed + 1e-12:
        conn.close()
        print("refusing paid run: improvement-program budget would be exceeded", file=sys.stderr)
        return 2
    reservation_id = jobs.reserve_budget(
        conn,
        period=today[:7],
        amount_usd=ceiling,
        limit_usd=s.monthly_cost_limit_usd,
    )

    total_expected = sum(len(c.expect) for c in cases)
    empty_cases = sum(1 for c in cases if not c.expect)
    print(f"cases: {len(cases)}  expected facts: {total_expected}  must-be-empty: {empty_cases}")
    print(f"variants: {[':'.join(v) for v in variants]}\n")

    try:
        scores = [
            run(cases, model=m, version=v, s=s, today=today, verbose=args.verbose)
            for m, v in variants
        ]
        accounted = 0.0
        with transaction(conn):
            for score in scores:
                summary = _score_summary(score)
                cost = score.cost if not score.errors else ceilings[score.label]
                accounted += cost
                conn.execute(
                    """INSERT INTO judge_runs
                       (owner_id,kind,model,prompt_version,input_json,output_json,error,
                        input_tokens,output_tokens,cost_usd,latency_ms,created_at)
                       VALUES (?,'improvement-golden',?,?,?,?,?,?,?,?,?,?)""",
                    (
                        s.owner_id,
                        score.model,
                        score.version,
                        json.dumps({"case_ids": [case.id for case in cases]}, sort_keys=True),
                        json.dumps(summary, ensure_ascii=False, sort_keys=True),
                        "; ".join(score.errors)[:2000] or None,
                        score.in_tokens,
                        score.out_tokens,
                        cost,
                        sum(score.latency),
                        utcnow(),
                    ),
                )
        jobs.reconcile_budget(conn, reservation_id, actual_usd=accounted)
    except Exception:
        with contextlib.suppress(RuntimeError):
            jobs.release_budget(conn, reservation_id)
        conn.close()
        raise
    output_dir = (
        Path(args.output_dir).expanduser()
        if args.output_dir
        else s.export_dir / "release-artifacts"
    )
    artifact = _write_artifact(scores=scores, cases=cases, output_dir=output_dir, ceilings=ceilings)
    conn.close()
    report(scores, cases)
    print(f"protected artifact: {artifact}")
    return int(any(score.errors or score.leaks for score in scores))


if __name__ == "__main__":
    raise SystemExit(main())
