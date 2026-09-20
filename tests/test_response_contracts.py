"""Response contracts retain open JSON and the published Python SDK read API."""

from __future__ import annotations

import importlib

import pytest
from pydantic import TypeAdapter

from memkit.schemas import JudgeRunOut, MemorySearchOut, MetricsOut
from sdk.python.memkit_client.models import (
    JudgeRunOut as ClientJudgeRun,
)
from sdk.python.memkit_client.models import (
    MemorySearchOut as ClientSearch,
)
from sdk.python.memkit_client.models import (
    MetricsOut as ClientMetrics,
)
from sdk.python.memkit_client.models import OffsetPageOut
from tools.normalize_python_sdk import LEGACY_DICTIONARIES


def test_search_optional_sources_and_arbitrary_context_survive_typed_roundtrip() -> None:
    memory = {
        "id": "m1",
        "text": "Use pnpm",
        "kind": "preference",
        "source_role": "user",
        "context": {"client_specific": {"nested": [1, True, None, {"x": "y"}]}},
        "tags": [],
        "revision": 1,
        "review_status": "confirmed",
        "scope": "Personal",
        "scope_slug": "private",
        "subject": None,
        "subject_slug": None,
        "score": 0.9,
        "similarity": 0.8,
        "lexical": 0.7,
        "entity": 0.0,
        "importance": 0.6,
        "recency": 0.5,
        "updated_at": "2026-09-20T00:00:00Z",
        "future_extension": {"enabled": True},
    }
    payload = {
        "memories": [memory],
        "used_tokens": 5,
        "dropped_trust": [],
        "dropped_filter": [],
        "dropped_validity": [],
        "dropped_relevance": [],
        "policy_id": "neutral-v1",
        "embed_ms": 1,
        "timings": {"total_ms": 10},
        "raw": [],
        "retrieval_id": None,
    }
    rendered = MemorySearchOut.model_validate(payload).model_dump(mode="json")
    assert rendered == payload
    assert "sources" not in rendered["memories"][0]
    result = ClientSearch.from_dict(rendered)
    # Existing clients used dictionary wrappers here, before named attributes existed.
    assert result.memories[0]["text"] == "Use pnpm"
    assert result.memories[0]["context"] == memory["context"]
    assert "text" in result.memories[0]
    assert "sources" not in result.memories[0]
    assert result.to_dict() == rendered


def test_judge_json_and_nullable_member_metrics_remain_dictionary_readable() -> None:
    run = {
        "id": 1,
        "kind": "extraction",
        "model": "model",
        "prompt_version": "v1",
        "input": {"messages": ["hello", {"role": "user"}]},
        "output": {"items": []},
        "error": None,
        "input_tokens": 1,
        "output_tokens": 2,
        "cost_usd": 0.01,
        "latency_ms": 1.5,
        "created_at": None,
    }
    rendered = TypeAdapter(JudgeRunOut).validate_python(run)
    parsed = ClientJudgeRun.from_dict(rendered)
    assert parsed["input"] == run["input"]
    assert parsed["output"] == run["output"]
    assert parsed.to_dict() == run
    metrics = {
        "outbox_pending": None,
        "oldest_unprocessed_message": None,
        "provider_errors": 0,
        "month_spend_usd": 0.0,
        "month_reserved_usd": 0.0,
        "month_limit_usd": None,
        "pending_review": 0,
        "search_latency_ms": {"p50": None, "p95": None, "p99": None},
        "retrieval_runs": 0,
        "abstention_rate": None,
        "feedback_labels": 0,
        "feedback_runs": 0,
        "useful_rate": None,
        "correct_rate": None,
        "spend_by_user": [],
        "outbox_oldest_age_seconds": None,
        "outbox_retries": None,
        "index_parity": {"database_active": 1, "qdrant_active": None},
        "backup_freshness_seconds": None,
    }
    rendered_metrics = MetricsOut.model_validate(metrics).model_dump(mode="json")
    parsed_metrics = ClientMetrics.from_dict(rendered_metrics)
    assert parsed_metrics["index_parity"]["database_active"] == 1
    assert parsed_metrics["outbox_pending"] is None
    assert parsed_metrics.to_dict() == metrics


@pytest.mark.parametrize(("module", "name"), LEGACY_DICTIONARIES.items())
def test_published_dictionary_model_imports_still_accept_custom_json(
    module: str, name: str
) -> None:
    namespace = importlib.import_module(f"sdk.python.memkit_client.models.{module}")
    model = getattr(namespace, name)
    payload = {"text": "hello", "context": {"custom": [1, None, False]}}
    parsed = model.from_dict(payload)
    assert parsed["text"] == "hello"
    assert parsed.to_dict() == payload


def test_published_generic_offset_page_keeps_arbitrary_items() -> None:
    payload = {"items": [{"custom": [None, True]}], "limit": 1, "offset": 0, "total": 1}
    parsed = OffsetPageOut.from_dict(payload)
    assert parsed.items[0]["custom"] == [None, True]
    assert parsed.to_dict() == payload


def test_dashboard_fixtures_validate_against_actual_openapi() -> None:
    """TypeScript checks property names; JSON Schema also checks wire formats."""
    import json
    import shutil
    import subprocess
    from pathlib import Path

    from jsonschema import Draft202012Validator, FormatChecker

    from memkit.api import app

    root = Path(__file__).resolve().parents[1]
    script = """
import ts from 'typescript';
import { readFileSync } from 'node:fs';
const source = readFileSync('../../web/e2e/fixtures.ts', 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const fixtures = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
process.stdout.write(JSON.stringify(fixtures));
"""
    node = shutil.which("node")
    assert node is not None
    fixtures = json.loads(
        subprocess.run(  # noqa: S603
            [node, "--input-type=module", "-e", script],
            # Backend CI installs the SDK toolchain; fixtures have only type imports.
            cwd=root / "sdk" / "typescript",
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    document = app.openapi()
    routes = {
        "health": ("/v1/admin/health", "get"),
        "me": ("/v1/auth/me", "get"),
        "metrics": ("/v1/admin/metrics", "get"),
        "reviewStats": ("/v1/admin/stats/review", "get"),
        "searchResult": ("/v1/memories/search", "post"),
        "backups": ("/v1/admin/backups", "get"),
        "judge": ("/v1/admin/judge-runs/{run_id}", "get"),
    }
    for name, (path, method) in routes.items():
        schema = document["paths"][path][method]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        validator = Draft202012Validator(
            {**schema, "components": document["components"]}, format_checker=FormatChecker()
        )
        errors = [error.message for error in validator.iter_errors(fixtures[name])]
        assert not errors, (name, errors)
