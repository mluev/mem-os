"""Ask the judge model for alternative phrasings of a search query.

Opt-in per request (`rewrite_query`), because it adds a model call to the read
path. Every failure -- no judge configured, the monthly ceiling, a provider
error, an empty answer -- yields no rewrites, and search proceeds with the
original query alone. The rewrites are never stored: retrieval telemetry keeps
only an HMAC of the query, and a rewrite is the query in other words.
"""

from __future__ import annotations

from typing import Any

import psycopg

from . import judge, prompts
from .http import judge_configured

MAX_REWRITES = 3
MAX_REWRITE_CHARS = 512


def rewrites(
    conn: psycopg.Connection, query: str, *, settings: Any, user_id: str | None
) -> tuple[list[str], str | None]:
    """Up to three distinct rewrites of `query`, and why there are none if so."""
    if not judge_configured(settings):
        return [], "judge_not_configured"
    result = judge.structured_call(
        conn,
        kind="rewrite",
        prompt_version=prompts.REWRITE_VERSION,
        prompt=prompts.render_rewrite(query),
        schema=prompts.rewrite_schema(),
        name="emit_rewrites",
        model=settings.judge_model,
        monthly_limit_usd=settings.monthly_cost_limit_usd,
        audit={"query_chars": len(query)},
        api_key=settings.anthropic_api_key,
        gemini_api_key=settings.gemini_api_key,
        project=settings.vertex_project,
        location=settings.vertex_location,
        max_output_tokens=512,
        user_id=user_id,
        record_output=False,
    )
    if result.error or result.raw is None:
        return [], result.error or "empty_response"
    seen = {query.strip().casefold()}
    out: list[str] = []
    for item in result.raw.get("queries") or []:
        text = str(item or "").strip()
        if not text or len(text) > MAX_REWRITE_CHARS or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(text)
        if len(out) >= MAX_REWRITES:
            break
    return out, None
