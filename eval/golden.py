"""Score extractor variants against the golden set.

`experiment.py` measures what a variant *did* on the real corpus. This measures
whether it was *right*, against hand-written windows with a known answer.

    uv run python -m eval.golden \
        --variant gemini-3.5-flash-lite:v2 \
        --variant gemini-3.5-flash-lite:v3

Scores, in the order they matter:

leak     credential values reaching the store. Any non-zero score fails outright;
         nothing else compensates.
recall   expected facts found. The extractor's core job.
fp       facts invented where the answer was "nothing" — assistant work logs,
         transient moods, a term the user asked about once. v1's whole failure
         mode, so it is scored separately from recall rather than averaged in.
scope    of the facts found, how many landed in the right scope. A user
         preference filed as project-scoped is invisible outside that repo.
imp      how many cleared the importance floor the case declares. Catches the
         everything-is-0.6 collapse that both v1 and v2 showed.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import judge, prompts, providers  # noqa: E402
from memkit.config import get_settings  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "conversations.yaml"


@dataclass
class Case:
    id: str
    probes: str
    project: str | None
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
            project=raw.get("project"),
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
    scope_ok = 0
    scope_checked = 0
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
                    sc.failures.append(
                        f"{case.id}: rejected {pattern!r} -> {t[:60]!r}"
                    )

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
        if "scope" in want:
            sc.scope_checked += 1
            if best.scope == want["scope"]:
                sc.scope_ok += 1
            else:
                sc.failures.append(
                    f"{case.id}: scope {best.scope!r}, wanted {want['scope']!r} "
                    f"-> {(best.text or '')[:50]!r}"
                )
        if "min_importance" in want:
            sc.imp_checked += 1
            if (best.importance or 0) >= float(want["min_importance"]):
                sc.imp_ok += 1
            else:
                sc.failures.append(
                    f"{case.id}: importance {best.importance}, "
                    f"wanted >= {want['min_importance']}"
                )
        if "op" in want:
            sc.op_checked += 1
            if best.op == want["op"] and (
                "id" not in want or best.id == want["id"]
            ):
                sc.op_ok += 1
            else:
                sc.failures.append(
                    f"{case.id}: got {best.op} id={best.id}, "
                    f"wanted {want['op']} id={want.get('id')}"
                )

    if case.max_ops is not None and len(ops) > case.max_ops:
        sc.over_emission += len(ops) - case.max_ops
        sc.failures.append(f"{case.id}: {len(ops)} ops, cap was {case.max_ops}")


def run(cases: list[Case], *, model: str, version: str, s, today: str,
        verbose: bool) -> Score:
    sc = Score(model=model, version=version)
    for i, case in enumerate(cases, 1):
        prompt = prompts.render(
            version,
            today=today,
            window=judge.render_window(case.messages),
            candidates=judge.render_candidates(case.candidates),
            project=case.project,
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
                model=model, prompt=prompt,
                gemini_api_key=s.gemini_api_key,
                anthropic_api_key=s.anthropic_api_key,
            )
        except Exception as exc:  # noqa: BLE001
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
                # `travel` is the model's own answer to "would this hold in another
                # repo"; `scope` is already corrected from it, so printing both is
                # how a scope decision becomes auditable rather than a black box.
                travel = {True: "travels", False: "repo-bound", None: "-"}[
                    op.holds_in_other_repos
                ]
                print(f"      {op.op} {op.type}/{op.scope} imp={op.importance} "
                      f"[{travel}] {op.text}")
            if not ops:
                print("      (empty)")
    print(" " * 78, end="\r")
    return sc


def report(scores: list[Score], cases: list[Case]) -> None:
    print("\n" + "=" * 104)
    print(f"{'variant':<32} {'recall':>12} {'fp':>4} {'leak':>5} {'scope':>8} "
          f"{'imp':>7} {'op':>6} {'over':>5} {'medlen':>7} {'imps':>5} {'$':>8}")
    print("-" * 104)
    for sc in scores:
        scope = f"{sc.scope_ok}/{sc.scope_checked}" if sc.scope_checked else "-"
        imp = f"{sc.imp_ok}/{sc.imp_checked}" if sc.imp_checked else "-"
        op = f"{sc.op_ok}/{sc.op_checked}" if sc.op_checked else "-"
        medlen = statistics.median(sc.lengths) if sc.lengths else 0
        print(f"{sc.label:<32} {sc.found:>3}/{sc.expected:<3} {sc.recall:>5.0%} "
              f"{sc.false_positives:>4} {sc.leaks:>5} {scope:>8} {imp:>7} {op:>6} "
              f"{sc.over_emission:>5} {medlen:>7.0f} "
              f"{len(set(sc.importances)):>5} {sc.cost:>8.4f}")
    print("-" * 104)
    print("recall found/expected  |  fp = facts invented where the answer was nothing")
    print("leak = credential values stored (any value fails the run)")
    print("scope/imp/op = of facts found, how many had the right scope / cleared the")
    print("importance floor / used the right operation      over = ops above the cap")

    for sc in scores:
        if sc.errors:
            print(f"\n  {sc.label} errors: {len(sc.errors)}")
            for e in sc.errors[:3]:
                print(f"    {e[:100]}")
        if sc.failures:
            print(f"\n  {sc.label} — {len(sc.failures)} failures:")
            for f in sc.failures[:14]:
                print(f"    {f[:112]}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="golden")
    ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--file", default=str(GOLDEN))
    ap.add_argument("--only", default=None, help="run one case by id")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    raw = yaml.safe_load(Path(args.file).read_text(encoding="utf-8")) or []
    cases = [Case.parse(r, i) for i, r in enumerate(raw)]
    if args.only:
        cases = [c for c in cases if c.id == args.only]
    if not cases:
        print("no cases", file=sys.stderr)
        return 1

    variants = [v.split(":", 1) for v in args.variant] or [
        ["gemini-3.5-flash-lite", "v2"],
        ["gemini-3.5-flash-lite", "v3"],
    ]
    s = get_settings()
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    total_expected = sum(len(c.expect) for c in cases)
    empty_cases = sum(1 for c in cases if not c.expect)
    print(f"cases: {len(cases)}  expected facts: {total_expected}  "
          f"must-be-empty: {empty_cases}")
    print(f"variants: {[':'.join(v) for v in variants]}\n")

    scores = [
        run(cases, model=m, version=v, s=s, today=today, verbose=args.verbose)
        for m, v in variants
    ]
    report(scores, cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
