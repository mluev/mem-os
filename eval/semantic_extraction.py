"""Read-only live comparison: current golden extractor outputs with/without Jev.

Uses only the repository's synthetic golden conversations, never a live database.
Exact source validation precedes Jev. Reports recall lost to the semantic gate,
not just the number of rejected operations. This is an additional diagnostic set,
not the heldout semantic set and not a full production extraction replay.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from memkit import judge, prompts, providers
from memkit.config import get_settings
from memkit.security import redact, redact_value
from memkit.semantic import JevClient, SemanticError, support_probability
from memkit.semantic_questions import QUESTIONS

from .golden import GOLDEN, Case, Score, _score_summary, score_case
from .reports import archive, code_identity
from .semantic import digest


def verified_sources(case: Case, op: judge.Op) -> list[str] | None:
    """Slice exact user evidence. Missing, ambiguous or assistant sources fail closed."""
    if not op.evidence:
        return None
    messages = {int(m["id"]): m for m in case.messages}
    spans = []
    for citation in op.evidence:
        message = messages.get(int(citation["message_id"]))
        if not message or message["role"] != "user":
            return None
        text = str(message["content"])
        quote = str(citation.get("quote") or "")
        if quote:
            start = text.find(quote)
            if start < 0 or text.find(quote, start + 1) >= 0:
                return None
            end = start + len(quote)
        else:
            start, end = int(citation["start_char"]), int(citation["end_char"])
        if start < 0 or end <= start or end > len(text) or not text[start:end].strip():
            return None
        spans.append(text[start:end])
    return spans


def extract_case(case: Case, settings: Any) -> dict[str, Any]:
    today = datetime.now(UTC).date().isoformat()
    prompt = prompts.render(
        prompts.DEFAULT_VERSION,
        today=today,
        window=judge.render_window(case.messages),
        candidates=judge.render_candidates(case.candidates),
        context=json.dumps(case.context, ensure_ascii=False, sort_keys=True),
        entities=judge.render_entities(case.entities),
        session_date=case.session_date or today,
        profile="",
        agent_id="claude-code",
    )
    try:
        out = providers.call(
            model=settings.judge_model,
            prompt=redact(prompt).text,
            gemini_api_key=settings.gemini_api_key,
            anthropic_api_key=settings.anthropic_api_key,
        )
    except Exception as exc:
        return {"id": case.id, "error": type(exc).__name__}
    if out.error:
        return {"id": case.id, "error": "generative provider error"}
    return {
        "id": case.id,
        "operations": redact_value(out.operations)[0],
        "input_tokens": out.input_tokens,
        "output_tokens": out.output_tokens,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=list(QUESTIONS), default="v3")
    parser.add_argument("--support-floor", type=float, default=0.9)
    parser.add_argument("--state-version", choices=["minimal", "anchored"], default="anchored")
    parser.add_argument(
        "--refresh", action="store_true", help="regenerate cached extractor outputs"
    )
    parser.add_argument("--output", type=Path, default=Path("data/jev/extractor-v3.json"))
    args = parser.parse_args()
    if not 0 <= args.support_floor <= 1:
        parser.error("support-floor must be 0..1")
    settings = get_settings()
    provenance = code_identity()
    raw = yaml.safe_load(GOLDEN.read_text())
    corpus = [Case.parse(case, i) for i, case in enumerate(raw)]
    signature = digest(
        {
            "corpus": raw,
            "model": settings.judge_model,
            "prompt": prompts.REGISTRY[prompts.DEFAULT_VERSION],
            "today": datetime.now(UTC).date().isoformat(),
        }
    )
    cache_path = Path("data/jev/golden-extractor-outputs.json")
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    cache_reused = cache.get("signature") == signature and not args.refresh
    if not cache_reused:
        if not (settings.gemini_api_key or settings.anthropic_api_key):
            parser.error("a configured generative provider credential is required")
        outputs = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(extract_case, c, settings) for c in corpus]
            for future in as_completed(futures):
                outputs.append(future.result())
                print(f"Extracted {len(outputs)}/{len(corpus)}", flush=True)
        cache = {"signature": signature, "outputs": outputs}
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n")
    by_id = {c.id: c for c in corpus}
    baseline, filtered = [
        Score(model=settings.judge_model, version=v)
        for v in [prompts.DEFAULT_VERSION, f"{prompts.DEFAULT_VERSION}+{args.version}"]
    ]
    records, errors = [], []
    with JevClient(settings.jev_api_key, model=settings.jev_model) as client:
        for output in sorted(cache["outputs"], key=lambda r: r["id"]):
            if "error" in output:
                errors.append({"id": output["id"], "error": output["error"]})
                continue
            case = by_id[output["id"]]
            for scoring in (baseline, filtered):
                scoring.in_tokens += output["input_tokens"]
                scoring.out_tokens += output["output_tokens"]
            parsed = [o for o in (judge.Op.parse(r) for r in output["operations"]) if o]
            valid, accepted, checks = [], [], []
            for op in parsed:
                if op.op == "DELETE":
                    valid.append(op)
                    accepted.append(op)
                    continue
                spans = verified_sources(case, op)
                if spans is None:
                    checks.append({"claim": op.text, "disposition": "invalid_source"})
                    continue
                valid.append(op)
                state = {
                    "claim": op.text,
                    "user_spans": spans,
                    "context": [{"role": m["role"], "text": m["content"]} for m in case.messages],
                }
                if args.state_version == "anchored":
                    state["context"] = {
                        "conversation": state["context"],
                        "entities": case.entities,
                        "recording_date": case.session_date or datetime.now(UTC).date().isoformat(),
                    }
                try:
                    result = client.judge("support", state, version=args.version)
                except SemanticError as exc:
                    errors.append({"id": case.id, "error": str(exc)})
                    continue
                retain = support_probability(result.answers["support"]) >= args.support_floor
                checks.append(
                    {
                        "claim": op.text,
                        "disposition": "accept" if retain else "hold",
                        "judgment": asdict(result),
                    }
                )
                if retain:
                    accepted.append(op)
            score_case(case, valid, baseline)
            score_case(case, accepted, filtered)
            records.append(
                {
                    "id": case.id,
                    "checks": checks,
                    "baseline_ops": [asdict(op) for op in valid],
                    "accepted_ops": [asdict(op) for op in accepted],
                }
            )
    artifact = {
        "signature": signature,
        "provenance": provenance,
        "state_version": args.state_version,
        "question_version": args.version,
        "question_sha256": digest(QUESTIONS[args.version]),
        "support_floor": args.support_floor,
        "extractor_cache_reused": cache_reused,
        "usage_note": "Score summaries include original extraction usage only; Jev usage is separate.",
        "baseline": _score_summary(baseline),
        "filtered": _score_summary(filtered),
        "baseline_failures": baseline.failures,
        "filtered_failures": filtered.failures,
        "errors": errors,
        "records": records,
    }
    semantic_runs = [
        check["judgment"] for r in records for check in r["checks"] if "judgment" in check
    ]
    artifact["jev_usage"] = {
        "input_tokens": sum(r["input_tokens"] for r in semantic_runs),
        "output_tokens": sum(r["output_tokens"] for r in semantic_runs),
        "requests": len(semantic_runs),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
    saved = archive(
        artifact,
        root=Path("data/experiments"),
        name=f"extractor-{args.version}-{args.state_version}",
        hypothesis="Check whether more complete reference context restores supported facts.",
        decision="inconclusive",
        data_class="synthetic",
        label_source="golden regex scorer; author-labeled",
        limitations=[
            "Diagnostic retention comparison on cached outputs, not proof of factual correctness.",
            "Support remains advisory regardless of this experiment.",
        ],
        source_name=args.output.name,
    )
    print(json.dumps({k: artifact[k] for k in ["baseline", "filtered", "errors"]}, indent=2))
    print(f"Artifact: {args.output}")
    print(f"Archived: {saved}")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
