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
routing  of the facts found in a case that shows an ENTITIES block, how many
         landed in the right scope and named the right subject. A spurious scope
         counts as wrong, so an expectation that omits `scope`/`subject` asserts
         that the model omitted them too.
fab      entity numbers that were not in the block the case showed. Production
         drops such an operation outright, so this is wasted extraction rather
         than bad data -- but it is the tell that a model is guessing at routing.
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
from memkit.db import connect, init_db, iso, transaction, utcnow

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
    # Recording date the window claims for itself. v8's date anchor resolves
    # relative time against it; cases that probe that need it to differ from
    # today, which is why it is per-case rather than the runner's date.
    session_date: str | None
    # The numbered ENTITIES block this window is shown, in the shape
    # `entities.for_prompt` produces plus the `ref` `judge.extract` assigns.
    # A case that declares one is a routing case: its expectations are scored
    # for scope and subject as well as for text. A case that declares none sees
    # "(none)", which is what a single-user instance sends.
    entities: list[dict[str, Any]]

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
            session_date=str(raw["session_date"]) if raw.get("session_date") else None,
            entities=[
                {
                    "ref": int(entity.get("ref") or i + 1),
                    "label": str(entity.get("label") or entity.get("kind") or "entity"),
                    "name": str(entity.get("name") or ""),
                    "aliases": [str(a) for a in (entity.get("aliases") or [])],
                }
                for i, entity in enumerate(raw.get("entities") or [])
            ],
        )

    @property
    def refs(self) -> set[int]:
        return {int(entity["ref"]) for entity in self.entities}


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
    routing_ok = 0
    routing_checked = 0
    fabricated = 0
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


def _routing_of(op: judge.Op) -> dict[str, Any]:
    return {"scope": op.scope, "subject": op.subject, "subject_name": op.subject_name}


def _routing_wanted(want: dict[str, Any]) -> dict[str, Any]:
    """The routing an expectation asserts. An absent key asserts absence.

    There is no "don't care" here on purpose. Routing a personal preference to
    the team is exactly the failure this metric exists to catch, and a metric
    that only looked at the cases where a scope was wanted could not see it.
    """
    return {
        "scope": want.get("scope"),
        "subject": want.get("subject"),
        "subject_name": want.get("subject_name"),
    }


def _routing_matches(want: dict[str, Any], got: dict[str, Any]) -> bool:
    for name in ("scope", "subject"):
        wanted = want[name]
        actual = got[name]
        if (wanted is None) != (actual is None) or (
            wanted is not None and int(wanted) != int(actual)
        ):
            return False
    # An unresolved person is asserted verbatim, since a human reads this name
    # to say who was meant; case is the one difference that carries no meaning.
    wanted_name = str(want["subject_name"] or "").strip().casefold()
    actual_name = str(got["subject_name"] or "").strip().casefold()
    return wanted_name == actual_name


RETIRED_KEYS = frozenset({"type", "holds_in_other_repos"})


def retired_expectations(raw: list[dict[str, Any]]) -> list[str]:
    """Case ids whose expectations use the retired single-owner schema.

    `scope` is not on the list any more, but it changed meaning rather than
    disappearing: it used to name the project context and now holds an integer
    reference into the ENTITIES block. A string there would score nothing and
    quietly inflate recall, so the type is checked instead of the key.
    """
    offenders: list[str] = []
    for case in raw:
        for expected in case.get("expect") or []:
            bad_types = any(
                not isinstance(expected[key], int)
                for key in ("scope", "subject")
                if key in expected
            )
            if RETIRED_KEYS & set(expected) or bad_types:
                offenders.append(str(case.get("id")))
    return sorted(set(offenders))


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

    # A number outside the block cannot have come from the window. Production
    # drops the whole operation, so it is scored here even when the operation
    # would otherwise have matched an expectation.
    for op in ops:
        for name in ("scope", "subject"):
            ref = getattr(op, name)
            if ref is not None and int(ref) not in case.refs:
                sc.fabricated += 1
                sc.failures.append(f"{case.id}: FABRICATED {name}={ref}, block has {case.refs}")

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
        if case.entities:
            sc.routing_checked += 1
            wanted_routing = _routing_wanted(want)
            got_routing = _routing_of(best)
            if _routing_matches(wanted_routing, got_routing):
                sc.routing_ok += 1
            else:
                sc.failures.append(
                    f"{case.id}: routing {got_routing!r}, wanted {wanted_routing!r} "
                    f"-> {(best.text or '')[:40]!r}"
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
            entities=judge.render_entities(case.entities),
            session_date=case.session_date or today,
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
                    f"scope={op.scope} subject={op.subject or op.subject_name} "
                    f"imp={op.importance} citations={len(op.evidence or [])} {op.text}"
                )
            if not ops:
                print("      (empty)")
    print(" " * 78, end="\r")
    return sc


def report(scores: list[Score], cases: list[Case]) -> None:
    print("\n" + "=" * 118)
    print(
        f"{'variant':<32} {'recall':>12} {'fp':>4} {'leak':>5} {'routing':>8} {'fab':>4} "
        f"{'context':>8} {'kind':>7} {'evidence':>8} {'imp':>7} {'op':>6} {'over':>5} {'$':>8}"
    )
    print("-" * 118)
    for sc in scores:
        routing = f"{sc.routing_ok}/{sc.routing_checked}" if sc.routing_checked else "-"
        context = f"{sc.context_ok}/{sc.context_checked}" if sc.context_checked else "-"
        kind = f"{sc.kind_ok}/{sc.kind_checked}" if sc.kind_checked else "-"
        evidence = f"{sc.evidence_ok}/{sc.evidence_checked}"
        imp = f"{sc.imp_ok}/{sc.imp_checked}" if sc.imp_checked else "-"
        op = f"{sc.op_ok}/{sc.op_checked}" if sc.op_checked else "-"
        print(
            f"{sc.label:<32} {sc.found:>3}/{sc.expected:<3} {sc.recall:>5.0%} "
            f"{sc.false_positives:>4} {sc.leaks:>5} {routing:>8} {sc.fabricated:>4} "
            f"{context:>8} {kind:>7} {evidence:>8} {imp:>7} {op:>6} "
            f"{sc.over_emission:>5} {sc.cost:>8.4f}"
        )
    print("-" * 118)
    print("recall found/expected  |  fp = facts invented where the answer was nothing")
    print("leak = credential values stored (any value fails the run)")
    print("routing = scope/subject correct, counting a spurious scope as wrong")
    print("fab = entity numbers absent from the block the case showed")
    print("context/kind/evidence/imp/op validate the v7 domain-neutral contract")

    for sc in scores:
        if sc.errors:
            print(f"\n  {sc.label} errors: {len(sc.errors)}")
            for e in sc.errors[:3]:
                print(f"    {e[:100]}")
        if sc.failures:
            print(f"\n  {sc.label} — {len(sc.failures)} failures:")
            for f in sc.failures[:24]:
                print(f"    {f[:118]}")


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
        "routing": [score.routing_ok, score.routing_checked],
        "fabricated_refs": score.fabricated,
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
        # Safety first and absolute: `safety_passed` already excluded leaks and
        # invalid evidence, and an invented fact outranks every accuracy metric
        # because no amount of recall repairs a store that contains fiction.
        # Then recall, then routing -- a fact in the wrong person's scope is
        # readable by the wrong person, which context drift is not -- then the
        # narrower contract metrics, then price.
        return (
            -score.false_positives,
            score.recall,
            score.routing_ok / (score.routing_checked or 1),
            -score.fabricated,
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
                entities=judge.render_entities(case.entities),
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
        "kind": "paid-golden",
        # The artifact is checksummed, so its timestamp has to be the rendered
        # string that gets hashed, not the datetime `utcnow` now returns.
        "created_at": iso(utcnow()),
        "cases": len(cases),
        "case_ids": [case.id for case in cases],
        "scores": summaries,
        "selected_model": _winner(scores),
        "selection_order": ["safety", "recall", "routing", "context", "cost"],
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
    path = output_dir / f"golden-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _runner_id(conn) -> str | None:
    """The administrator this paid run is billed to, if the instance has one.

    `judge_runs.user_id` is nullable, so a golden run on a bare database still
    records its spend rather than failing on a foreign key.
    """
    row = conn.execute(
        "SELECT id FROM users WHERE role='admin' AND disabled_at IS NULL ORDER BY created_at"
    ).fetchone()
    return str(row["id"]) if row else None


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
    if retired := retired_expectations(raw):
        print(f"retired expectation keys in: {', '.join(retired)}", file=sys.stderr)
        return 1
    if args.schema_only:
        for case in cases:
            prompts.render(
                prompts.DEFAULT_VERSION,
                today="2026-01-01",
                window=judge.render_window(case.messages),
                candidates=judge.render_candidates(case.candidates),
                context=json.dumps(case.context, sort_keys=True),
                entities=judge.render_entities(case.entities),
                session_date=case.session_date,
            )
        print(f"validated {len(cases)} golden cases against {prompts.DEFAULT_VERSION}")
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
    init_db(s.database_url)
    conn = connect(s.database_url)
    program_spend = float(
        conn.execute(
            """SELECT COALESCE(SUM(cost_usd),0) AS spent FROM judge_runs
                WHERE kind LIKE 'improvement-%'"""
        ).fetchone()["spent"]
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
    routing_cases = sum(1 for c in cases if c.entities)
    print(
        f"cases: {len(cases)}  expected facts: {total_expected}  "
        f"must-be-empty: {empty_cases}  routing: {routing_cases}"
    )
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
                       (user_id,kind,model,prompt_version,input,output,error,
                        input_tokens,output_tokens,cost_usd,latency_ms,created_at)
                       VALUES (%s,'improvement-golden',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        _runner_id(conn),
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
