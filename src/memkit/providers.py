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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

ProviderCallable = Callable[..., "ProviderResult"]
_CUSTOM_PROVIDERS: dict[str, tuple[str, ProviderCallable]] = {}
PROVIDER_TIMEOUT_SECONDS = 120.0


def register_provider(family: str, *, model_prefix: str, call: ProviderCallable) -> None:
    """Register a replaceable judge implementation for a model prefix."""
    if not family or not model_prefix:
        raise ValueError("provider family and model prefix are required")
    _CUSTOM_PROVIDERS[family] = (model_prefix, call)


_OP_FIELDS = [
    "op",
    "id",
    "text",
    "kind",
    "context_entries",
    "tags",
    "importance",
    "confidence",
    "valid_until",
    "evidence",
    "reason",
    # Routing. Integers referring to the ENTITIES block, never names or ids:
    # the same reason candidate targets are integers, since a uuid shown to a
    # model comes back subtly mutated often enough to matter.
    "scope",
    "subject",
    "subject_name",
]


def _operation_properties(*, anthropic: bool) -> dict[str, Any]:
    nullable_string: dict[str, Any] = {"type": ["string", "null"]}
    evidence_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "message_id": {"type": "integer"},
            "start_char": {"type": "integer"},
            "end_char": {"type": "integer"},
            "quote": nullable_string,
        },
        "required": ["message_id", "start_char", "end_char", "quote"],
    }
    context_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
        "required": ["key", "value"],
    }
    return {
        "op": {"type": "string", "enum": ["ADD", "UPDATE", "DELETE"]},
        "id": nullable_string,
        "text": nullable_string,
        "kind": nullable_string,
        "context_entries": {"type": "array", "items": context_item},
        "tags": {"type": "array", "items": {"type": "string"}},
        "importance": {"type": ["number", "null"]},
        "confidence": {"type": ["number", "null"]},
        "valid_until": nullable_string,
        "evidence": {"type": "array", "items": evidence_item},
        "reason": {"type": "string"},
        "scope": {"type": ["integer", "null"]},
        "subject": {"type": ["integer", "null"]},
        "subject_name": nullable_string,
    }


@dataclass
class ProviderResult:
    """Raw result of one model call, before validation."""

    operations: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None


def provider_of(model: str) -> str:
    for family, (prefix, _) in _CUSTOM_PROVIDERS.items():
        if model.startswith(prefix):
            return family
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

    Tool use alone does not mean the model "physically cannot return malformed
    JSON" -- that holds only with ``strict: true``, which in turn requires
    ``additionalProperties: false`` and every property in ``required``, hence the
    nullable optional fields.
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
                        "properties": _operation_properties(anthropic=True),
                        "required": _OP_FIELDS,
                    },
                }
            },
            "required": ["operations"],
        },
    }


def gemini_schema() -> dict[str, Any]:
    """Response schema for Vertex AI.

    Optional fields are nullable, and their allowed values are constrained with
    ``enum`` alongside the nullable type rather than being described in prose
    only. Prose-only was the earlier choice, on the reasoning that ``Op.parse``
    is the real gate anyway -- but it left the model free to return any string
    for ``scope``, and an unrecognised scope produces a fact that no read-path
    filter can ever match. Constrain it here *and* in ``Op.parse``; the schema is
    what makes the model retry, the parse is what protects the store.

    The values stay in the descriptions too, since that is what the model reads.
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
                    "properties": _operation_properties(anthropic=False),
                    "required": _OP_FIELDS,
                },
            }
        },
        "required": ["operations"],
    }


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------


def call_anthropic(*, model: str, prompt: str, api_key: str, effort: str = "low") -> ProviderResult:
    from anthropic import Anthropic

    # Sonnet 5 and Opus take output_config.effort and reject budget_tokens,
    # temperature, top_p and top_k with a 400. Haiku 4.5 is the reverse: it
    # rejects effort outright.
    extra: dict[str, Any] = {}
    if not model.startswith("claude-haiku"):
        extra["output_config"] = {"effort": effort}

    tool = anthropic_tool()
    response = Anthropic(
        api_key=api_key,
        timeout=PROVIDER_TIMEOUT_SECONDS,
        max_retries=1,
    ).messages.create(
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
            break
    if result.raw is None and result.error is None:
        result.error = "structured_output_missing"
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
    from google.genai import types

    client = _gemini_client(api_key=api_key, project=project, location=location)
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


def merge_schema() -> dict[str, Any]:
    """Response schema for the consolidator.

    A separate, much smaller schema than the extractor's: consolidation answers one
    question about one cluster. `text` is nullable because "these are actually
    different things" is a first-class answer -- see rule 4 of the merge prompt.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "text": {
                "type": ["string", "null"],
                "description": (
                    "The merged fact, under 200 characters. Null if the memories "
                    "are about different things and must not be merged."
                ),
            },
            "importance": {
                "type": ["number", "null"],
                "description": "Importance of the merged fact, 0.0-1.0.",
            },
            "reason": {"type": "string"},
        },
        "required": ["text", "importance", "reason"],
    }


def merge_tool() -> dict[str, Any]:
    """Anthropic equivalent of `merge_schema`, strict mode."""
    schema = merge_schema()
    return {
        "name": "emit_merge",
        "description": "Emit one merged memory, or null if they must not merge.",
        "strict": True,
        "input_schema": schema,
    }


def call_merge(
    *,
    model: str,
    prompt: str,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
) -> ProviderResult:
    """One consolidation call. `raw` carries the merge object, `operations` is unused."""
    which = provider_of(model)
    if which == "gemini":
        if not (gemini_api_key or project):
            return ProviderResult(error="no GEMINI_API_KEY and no VERTEX_PROJECT")
        from google.genai import types

        client = _gemini_client(api_key=gemini_api_key, project=project, location=location)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
                response_mime_type="application/json",
                response_json_schema=merge_schema(),
                max_output_tokens=1024,
            ),
        )
        usage = getattr(response, "usage_metadata", None)
        result = ProviderResult(
            input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
            output_tokens=(
                (getattr(usage, "candidates_token_count", 0) or 0)
                + (getattr(usage, "thoughts_token_count", 0) or 0)
            ),
        )
        text = getattr(response, "text", None)
        if not text:
            result.error = "empty_response"
            return result
        try:
            result.raw = json.loads(text)
        except ValueError as exc:
            result.error = f"json_decode_error: {exc}"
        return result

    if not anthropic_api_key:
        return ProviderResult(error="no ANTHROPIC_API_KEY configured")
    from anthropic import Anthropic

    tool = merge_tool()
    extra: dict[str, Any] = {}
    if not model.startswith("claude-haiku"):
        extra["output_config"] = {"effort": "low"}
    response = Anthropic(
        api_key=anthropic_api_key,
        timeout=PROVIDER_TIMEOUT_SECONDS,
        max_retries=1,
    ).messages.create(
        model=model,
        max_tokens=1024,
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
    return result


# Errors that prove nothing was billed: the request never reached a model, or
# it was refused before inference. A failed call must not be charged against the
# monthly ceiling as if it had run -- see judge.extract.
UNBILLED_ERROR_PREFIXES = (
    "no GEMINI_API_KEY",
    "no ANTHROPIC_API_KEY",
)
UNBILLED_EXCEPTIONS = frozenset(
    {
        # Never reached the provider.
        "ConnectError",
        "ConnectTimeout",
        "ConnectionError",
        "ConnectionRefusedError",
        "APIConnectionError",
        "SSLError",
        # Refused before inference (4xx).
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "NotFoundError",
        "RateLimitError",
        "ClientError",
    }
)


def _gemini_client(*, api_key: str, project: str, location: str):
    """One Gemini client builder for every call path.

    The merge path used to build its own client with no timeout, so a hung
    consolidation call blocked the single worker thread indefinitely -- for up
    to twenty clusters in a row. Sharing the constructor makes forgetting the
    timeout impossible.
    """
    from google import genai
    from google.genai import types

    http_options = types.HttpOptions(timeout=int(PROVIDER_TIMEOUT_SECONDS * 1000))
    if project:
        return genai.Client(
            vertexai=True,
            project=project,
            location=location or "global",
            api_key=api_key or None,
            http_options=http_options,
        )
    return genai.Client(api_key=api_key, http_options=http_options)


def is_unbilled(error: str) -> bool:
    """True when this error means the provider certainly did not bill us.

    Deliberately conservative: a timeout mid-inference or an unrecognised
    exception is treated as possibly billed, because under-reporting spend is
    worse than over-reporting it.
    """
    if not error:
        return False
    if error.startswith(UNBILLED_ERROR_PREFIXES):
        return True
    return error.partition(":")[0].strip() in UNBILLED_EXCEPTIONS


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
    custom = _CUSTOM_PROVIDERS.get(which)
    if custom:
        return custom[1](
            model=model,
            prompt=prompt,
            anthropic_api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            project=project,
            location=location,
            effort=effort,
        )
    if which == "gemini":
        if not (gemini_api_key or project):
            return ProviderResult(
                error="no GEMINI_API_KEY set (Gemini Developer API) and no "
                "VERTEX_PROJECT for standard Vertex"
            )
        return call_vertex(
            model=model,
            prompt=prompt,
            api_key=gemini_api_key,
            project=project,
            location=location,
        )
    if not anthropic_api_key:
        return ProviderResult(error="no ANTHROPIC_API_KEY configured")
    return call_anthropic(model=model, prompt=prompt, api_key=anthropic_api_key, effort=effort)
