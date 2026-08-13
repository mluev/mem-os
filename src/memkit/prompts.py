"""Versioned, domain-neutral prompt registry."""

from __future__ import annotations

import json
from typing import Any

V7 = """You extract durable, atomic memories from a conversation. Precision and
source fidelity matter more than recall: when uncertain, return no operation.

Return ADD, UPDATE, or DELETE operations only. Do not create workflow objects,
tasks, reminders, schedules, due dates, or product state. A memory is a claim that
can help a future agent and remains independently understandable.

RULES
1. Only a user's own words can support a memory. Assistant messages are context
   for resolving references only. Never extract assistant work logs, counts,
   summaries, plans, claims, or suggestions—even when the user says "go on",
   "okay", or otherwise acknowledges them.
2. Every ADD or UPDATE must cite one or more exact spans from USER messages only.
   For each citation, copy the smallest sufficient user substring word-for-word
   into `quote`. Also provide `start_char`/`end_char` if you can count them, but
   the system derives authoritative offsets from a unique exact quote. Never
   paraphrase a quote, cite an assistant message, or guess source text.
3. Emit nothing for temporary moods or states (today, tired, later, currently),
   one-off questions or definitions, acknowledgements, ordinary task requests,
   implementation steps, completed work, tickets, schedules, or facts stated only
   by the assistant. Repetition in an assistant message does not make it evidence.
4. Use `kind="preference"` for a user's taste, correction, constraint, or durable
   working style; `kind="fact"` for identity/contact/profile attributes; otherwise
   use one concise domain-neutral noun. Do not invent taxonomy variants such as
   `ux_preference`, `identity`, or `profile_info`.
5. Context defaults to empty. Personal preferences, identity, contact details,
   general working style, and rules stated as "always", "everywhere", "in all our
   products", or "in future" remain global even inside a workspace conversation.
   Copy caller context only for a claim about this named codebase/system or a
   decision that would be false elsewhere.
6. Importance guidance: identity/contact, hard constraints, and explicit durable
   "always/never" rules are 0.7–0.9; ordinary durable preferences and project
   architecture are 0.5–0.7; never raise transient content into memory.
7. Keep text under 200 characters, self-contained, and free of credential values.
   A request to remember a secret is not permission to store the value.
8. UPDATE or DELETE only a supplied candidate in the same context. Use UPDATE
   when user evidence corrects or replaces that candidate; do not duplicate it.
9. `valid_until` means the claim stops being true, never a deadline.

FINAL CHECK FOR EACH OPERATION
- durable and useful in a future conversation;
- supported only by exact cited user text;
- kind, context, importance, and candidate target follow the rules above;
- no credential, assistant-only detail, transient state, or one-off question.
If any check fails, omit the operation.

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
    context: str | None = None,
    session_date: str | None = None,
    profile: str = "",
    agent_id: str | None = None,
) -> str:
    del today, session_date, profile, agent_id
    template = REGISTRY.get(version)
    if template is None:
        raise ValueError(f"unknown prompt version: {version!r}")
    return template.format(context=context or "{}", candidates=candidates, window=window)


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
