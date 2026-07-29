"""Model providers for the judge.

The judge's contract is provider-neutral: a window plus candidates go in, a list
of operations matching one schema comes out. Only the call itself differs, so
that is all this module holds.

Two providers, chosen by model id:

``gemini-*`` via the Gemini Developer API or Vertex AI
    The default. Structured output is a **response schema**
    (``response_json_schema`` + ``response_mime_type``), not tool use.
    ``thinking_level="MINIMAL"`` because Google recommends it for exactly this
    shape of work -- classification and JSON extraction -- and because on
    Flash-Lite reasoning bills as *output*, which costs 8x what input does.
    A key-only configuration uses the Gemini Developer API. A configured
    project uses Vertex AI.

``claude-*`` via the Anthropic API
    Structured output is a tool call with ``strict: true``. Kept working so the
    two can be compared on the same eval rather than swapped on faith.

The schemas are not interchangeable. Anthropic's strict mode requires every
property in ``required`` and accepts ``null`` inside an ``enum``; the Gemini
schema keeps optional fields as nullable plain types instead, because an
enum-with-null is the kind of thing providers disagree about. Nothing is lost:
``Op.parse`` validates every field regardless of provider, and it -- not the
schema -- is the real gate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_TYPES = [
    "preference", "fact", "skill", "relation", "project", "decision", "task",
]
SCOPES = ["user", "project", "task"]

_OP_FIELDS = [
    "op", "id", "text", "type", "scope",
    "importance", "confidence", "valid_until", "task_status", "reason",
]


@dataclass
class ProviderResult:
    """Raw result of one model call, before validation."""

    operations: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


def provider_of(model: str) -> str:
    if model.startswith("gemini"):
        return "gemini"
    if model.startswith("claude"):
        return "anthropic"
    raise ValueError(f"unknown model family: {model!r}")


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

def anthropic_tool() -> dict[str, Any]:
    """Tool definition with strict mode.

    docs/04-judge.md claims tool use alone means the model "physically cannot
    return malformed JSON". That holds only with ``strict: true``, which in turn
    requires ``additionalProperties: false`` and every property in ``required``
    -- hence the nullable optional fields.
    """
    return {
        "name": "emit_operations",
        "description": "Emit memory operations for the conversation window.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "op": {"enum": ["ADD", "UPDATE", "DELETE"]},
                            "id": {"type": ["string", "null"]},
                            "text": {"type": ["string", "null"]},
                            "type": {"enum": [*MEMORY_TYPES, None]},
                            "scope": {"enum": [*SCOPES, None]},
                            "importance": {"type": ["number", "null"]},
                            "confidence": {"type": ["number", "null"]},
                            "valid_until": {"type": ["string", "null"]},
                            "task_status": {
                                "enum": ["unknown", "todo", "doing", "done", None]
                            },
                            "reason": {"type": "string"},
                        },
                        "required": _OP_FIELDS,
                    },
                }
            },
            "required": ["operations"],
        },
    }


def gemini_schema() -> dict[str, Any]:
    """Response schema for Vertex AI.

    Optional enums are nullable plain strings rather than enum-with-null, which
    providers handle inconsistently. ``Op.parse`` rejects any value outside the
    allowed set, so the constraint is still enforced -- just one layer later.
    The allowed values stay in the field descriptions so the model still sees
    them.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE"]},
                        "id": {
                            "type": ["string", "null"],
                            "description": "Existing memory id; required for UPDATE and DELETE.",
                        },
                        "text": {
                            "type": ["string", "null"],
                            "description": "The fact, under 200 characters. Required for ADD and UPDATE.",
                        },
                        "type": {
                            "type": ["string", "null"],
                            "description": "One of: " + ", ".join(MEMORY_TYPES),
                        },
                        "scope": {
                            "type": ["string", "null"],
                            "description": "One of: " + ", ".join(SCOPES),
                        },
                        "importance": {"type": ["number", "null"]},
                        "confidence": {"type": ["number", "null"]},
                        "valid_until": {"type": ["string", "null"]},
                        "task_status": {
                            "type": ["string", "null"],
                            "description": "For task memories only: unknown, todo, doing, or done.",
                        },
                        "reason": {"type": "string"},
                    },
                    "required": _OP_FIELDS,
                },
            }
        },
        "required": ["operations"],
    }


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------

def call_anthropic(
    *, model: str, prompt: str, api_key: str, effort: str = "low"
) -> ProviderResult:
    from anthropic import Anthropic

    # Sonnet 5 and Opus take output_config.effort and reject budget_tokens,
    # temperature, top_p and top_k with a 400. Haiku 4.5 is the reverse: it
    # rejects effort outright.
    extra: dict[str, Any] = {}
    if not model.startswith("claude-haiku"):
        extra["output_config"] = {"effort": effort}

    tool = anthropic_tool()
    response = Anthropic(api_key=api_key).messages.create(
        model=model,
        max_tokens=4096,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": prompt}],
        **extra,
    )
    result = ProviderResult(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    if response.stop_reason == "refusal":
        result.error = "refusal"
        return result
    for block in response.content:
        if block.type == "tool_use" and block.name == tool["name"]:
            result.raw = block.input
            result.operations = list(block.input.get("operations") or [])
    return result


def call_vertex(
    *,
    model: str,
    prompt: str,
    api_key: str = "",
    project: str = "",
    location: str = "",
) -> ProviderResult:
    """Call Gemini through the Developer API or Vertex AI.

    The Google Gen AI SDK selects different services through ``vertexai``:

    Gemini Developer API
        An API key alone. This is the default and works with AI Studio keys.
    Standard Vertex
        ``project`` + ``location``, authenticated by ADC or a Vertex-enabled
        key. Only for full GCP integration.

    A plain AI Studio key must not be sent with ``vertexai=True``: that routes
    it to ``aiplatform.googleapis.com`` and restricted keys fail with
    ``API_KEY_SERVICE_BLOCKED`` even though the same key is valid for Gemini.
    """
    from google import genai
    from google.genai import types

    if project:
        client = genai.Client(
            vertexai=True,
            project=project,
            location=location or "global",
            api_key=api_key or None,
        )
    else:
        client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            # MINIMAL is Google's own recommendation for classification and JSON
            # extraction. It also matters for cost: on Flash-Lite reasoning is
            # billed as output at $2.50/Mtok against $0.30 for input.
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
            response_mime_type="application/json",
            response_json_schema=gemini_schema(),
            max_output_tokens=4096,
        ),
    )

    usage = getattr(response, "usage_metadata", None)
    result = ProviderResult(
        input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
        # Reasoning is billed as output, so count it as output or the ceiling
        # under-reports real spend.
        output_tokens=(
            (getattr(usage, "candidates_token_count", 0) or 0)
            + (getattr(usage, "thoughts_token_count", 0) or 0)
        ),
    )

    text = getattr(response, "text", None)
    if not text:
        # A blocked or empty candidate yields no text. Surface the reason rather
        # than treating it as "nothing worth remembering".
        reason = getattr(response, "prompt_feedback", None)
        result.error = f"empty_response ({reason})" if reason else "empty_response"
        return result

    try:
        parsed = json.loads(text)
    except ValueError as exc:
        result.error = f"json_decode_error: {exc}"
        return result

    result.raw = parsed
    result.operations = list((parsed or {}).get("operations") or [])
    return result


def call(
    *,
    model: str,
    prompt: str,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    effort: str = "low",
) -> ProviderResult:
    """Dispatch to the right provider, converting missing config into an error."""
    which = provider_of(model)
    if which == "gemini":
        if not (gemini_api_key or project):
            return ProviderResult(
                error="no GEMINI_API_KEY set (Gemini Developer API) and no "
                      "VERTEX_PROJECT for standard Vertex"
            )
        return call_vertex(
            model=model, prompt=prompt, api_key=gemini_api_key,
            project=project, location=location,
        )
    if not anthropic_api_key:
        return ProviderResult(error="no ANTHROPIC_API_KEY configured")
    return call_anthropic(
        model=model, prompt=prompt, api_key=anthropic_api_key, effort=effort
    )
