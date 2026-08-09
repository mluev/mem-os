"""Versioned, domain-neutral prompt registry."""

from __future__ import annotations

import json
from typing import Any

V7 = """You extract durable, atomic memories from a conversation.

Return ADD, UPDATE, or DELETE operations only. Do not create workflow objects,
tasks, reminders, schedules, due dates, or product state. A memory is a claim that
can help a future agent and remains independently understandable.

RULES
1. User messages are evidence. Assistant messages are context only.
2. Every ADD or UPDATE must cite exact message spans. `start_char` is inclusive
   and `end_char` is exclusive in the redacted message text.
3. Use a concise free-form `kind`; never rely on a closed product vocabulary.
4. Copy caller context only when the claim is limited to it. Encode context as
   key/value entries; otherwise return an empty list.
5. Keep text under 200 characters, self-contained, and free of credentials.
6. UPDATE or DELETE only a supplied candidate in the same context.
7. `valid_until` means the claim stops being true, never a deadline.
8. Return no operation when there is no useful durable memory.

CONTEXT
{context}

CANDIDATES
{candidates}

CONVERSATION WINDOW
{window}"""

REGISTRY: dict[str, str] = {"v7": V7}
DEFAULT_VERSION = "v7"

CONSOLIDATE_V2 = """Compare the memories below. Return a merged text only when they
state the same claim in the same context. Preserve the newest truth and all useful
specifics. Return null when they differ. Never introduce workflow or scheduling
semantics. Keep the result under 200 characters.

MEMORIES
{cluster}"""
CONSOLIDATE_VERSION = "c2"


def render(
    version: str,
    *,
    today: str,
    window: str,
    candidates: str,
    project: str | None = None,
    session_date: str | None = None,
    profile: str = "",
    agent_id: str | None = None,
) -> str:
    del today, session_date, profile, agent_id
    template = REGISTRY.get(version)
    if template is None:
        raise ValueError(f"unknown prompt version: {version!r}")
    return template.format(context=project or "{}", candidates=candidates, window=window)


def render_consolidate(facts: list[dict[str, Any]]) -> str:
    cluster = "\n".join(
        f"- id={fact['id']} kind={fact.get('kind')} "
        f"context={json.dumps(fact.get('context') or {}, ensure_ascii=False)}: "
        f"{fact['text']}"
        for fact in facts
    )
    return CONSOLIDATE_V2.format(cluster=cluster)


def render_profile(facts: list[dict[str, Any]], limit: int = 12) -> str:
    return "\n".join(
        f"- ({fact.get('kind')}, importance {fact.get('importance')}) {fact.get('text')}"
        for fact in facts[:limit]
    )
