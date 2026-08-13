"""A/B extractor harness for the current domain-neutral v7 contract."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from memkit import extract, judge, prompts, providers
from memkit.config import get_settings
from memkit.db import connect


@dataclass
class Sample:
    session_id: str
    messages: list[Any]
    candidates: list[dict[str, Any]]
    context: dict[str, Any]
    agent_id: str


@dataclass
class VariantResult:
    model: str
    version: str
    ops: list[dict[str, Any]] = field(default_factory=list)
    windows: int = 0
    empty_windows: int = 0
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


def pick_samples(conn, *, owner_id: str, count: int, window_size: int) -> list[Sample]:
    sessions = conn.execute(
        """SELECT s.id,s.agent_id,s.context_json,MIN(m.id) AS first_id
             FROM sessions s JOIN messages m ON m.session_id=s.id
            WHERE s.owner_id=? AND m.role='user'
            GROUP BY s.id ORDER BY s.id""",
        (owner_id,),
    ).fetchall()
    samples: list[Sample] = []
    for session in sessions:
        messages = conn.execute(
            """SELECT id,role,content,created_at FROM messages
                 WHERE session_id=? AND id>=? ORDER BY id LIMIT ?""",
            (session["id"], session["first_id"], window_size),
        ).fetchall()
        if not any(message["role"] == "user" for message in messages):
            continue
        context = json.loads(session["context_json"] or "{}")
        samples.append(
            Sample(
                session_id=session["id"],
                messages=list(messages),
                candidates=extract.find_candidates(conn, owner_id=owner_id, context=context),
                context=context,
                agent_id=session["agent_id"],
            )
        )
        if len(samples) >= count:
            break
    return samples


def run_variant(samples: list[Sample], *, model: str, version: str, settings) -> VariantResult:
    result = VariantResult(model=model, version=version)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    for index, sample in enumerate(samples, 1):
        prompt = prompts.render(
            version,
            today=today,
            window=judge.render_window(sample.messages),
            candidates=judge.render_candidates(sample.candidates),
            context=json.dumps(sample.context, ensure_ascii=False, sort_keys=True),
            agent_id=sample.agent_id,
        )
        started = time.perf_counter()
        response = providers.call(
            model=model,
            prompt=prompt,
            gemini_api_key=settings.gemini_api_key,
            anthropic_api_key=settings.anthropic_api_key,
        )
        result.windows += 1
        result.latency_ms.append(int((time.perf_counter() - started) * 1000))
        result.in_tokens += response.input_tokens
        result.out_tokens += response.output_tokens
        if response.error:
            result.errors.append(response.error)
            continue
        parsed = [op for op in (judge.Op.parse(raw) for raw in response.operations) if op]
        if not parsed:
            result.empty_windows += 1
        for operation in parsed:
            result.ops.append(
                {
                    "op": operation.op,
                    "kind": operation.kind,
                    "context": operation.context or {},
                    "text": operation.text or "",
                    "importance": operation.importance,
                    "citations": len(operation.evidence or []),
                    "session": sample.session_id,
                }
            )
        print(f"[{result.label}] {index}/{len(samples)} ops={len(parsed)}", end="\r")
    return result


def report(results: list[VariantResult]) -> None:
    print("variant                           ops  empty  context-free  citations  latency  cost")
    for result in results:
        context_free = sum(not operation["context"] for operation in result.ops)
        citations = sum(operation["citations"] for operation in result.ops)
        latency = statistics.median(result.latency_ms) if result.latency_ms else 0
        print(
            f"{result.label:<33} {len(result.ops):>3}  "
            f"{result.empty_windows:>2}/{result.windows:<2}  {context_free:>12}  "
            f"{citations:>9}  {latency:>6.0f}ms  ${result.cost:.4f}"
        )
        for error in result.errors[:3]:
            print(f"  error: {error}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="experiment")
    parser.add_argument("--windows", type=int, default=10)
    parser.add_argument("--window-size", type=int, default=extract.WINDOW_SIZE)
    parser.add_argument("--variant", action="append", default=[])
    args = parser.parse_args()
    settings = get_settings()
    samples = pick_samples(
        connect(settings.db_path),
        owner_id=settings.owner_id,
        count=args.windows,
        window_size=args.window_size,
    )
    variants = [value.split(":", 1) for value in args.variant] or [
        [settings.judge_model, prompts.DEFAULT_VERSION]
    ]
    results = [
        run_variant(samples, model=model, version=version, settings=settings)
        for model, version in variants
    ]
    report(results)
    return int(any(result.errors for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
