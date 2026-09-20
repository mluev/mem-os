"""The extractor: turns a window of conversation into memory operations.

The default judge is **Gemini 3.5 Flash-Lite**: cheaper than Haiku, and
measured *better* on this task, where the failure mode is eagerness rather than
weakness. Claude models still work -- see `providers.py` -- so versions can be
compared on one eval. See decisions/0008.

Key-only auth uses the Gemini Developer API. Project auth uses Vertex AI.

Cost, per call at v2 window sizes:

    gemini-3.5-flash-lite   $0.0009
    claude-haiku-4-5        $0.0023
    claude-sonnet-5         $0.0046

Flash-Lite bills output at 8x input ($2.50 against $0.30) and counts reasoning
as output, which is why the prompt caps fact length and thinking is MINIMAL.

The v4 prompt is ~450 tokens longer than v2, which at $0.30/Mtok input is about
$0.00014 more per call -- immaterial next to what the extra recall is worth.

Corrections to the doc's contract:

* The prompt text lives in `prompts.py` and nowhere else. `build_prompt` is the
  single path to it, and `PROMPT_VERSION` names the version that path renders.
  These were once separate -- a literal copy of v2 here, `DEFAULT_VERSION`
  ("v4") on the label -- which made `extraction_version` lie and made every
  measurement in the extractor notebook describe a prompt production never ran.
#  See decisions/0016.
* Structured output is enforced per provider -- `strict: true` on Anthropic,
  `response_json_schema` on Vertex. The doc claims tool use alone means the
  model "physically cannot return malformed JSON"; that holds only in strict
  mode. Either way `Op.parse` is the real gate, since no schema can express
  "text is required when op is ADD".
* Rule 9 (never store credentials) is folded in from
  docs/07-hermes-adapter.md. The judge is a cloud API, so this belongs in the
  prompt itself and not only in the adapter that feeds it.
* v2 truncates assistant turns in the window. Measured on v1, leaving them full
  made windows ~4000 input tokens and, worse, meant the window was ~90% work
  log -- so the model summarised the work log and called it a fact about the
  user.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from . import jobs, prompts, providers, security

logger = logging.getLogger(__name__)

# The active version, and the *only* place the prompt text comes from. judge.py
# used to carry its own literal copy of the prompt while stamping every fact with
# prompts.DEFAULT_VERSION, so the version column claimed "v4" for text that was
# actually v2 and every measurement in the extractor notebook described a prompt
# never ran. `build_prompt` below is now the single path; the invariant is
# guarded by test_production_prompt_is_the_active_registry_version.
PROMPT_VERSION = prompts.DEFAULT_VERSION

# Assistant turns are *context* for resolving "it" and "that project", not source
# material. Measured on v1: leaving them full made windows ~4000 input tokens
# (3.4x the doc's estimate) and, worse, meant the window was ~90% work log — so
# the model summarised the work log and called the summary a fact about the user.
# Truncating fixes the cost and the quality problem in one change.
ASSISTANT_CONTEXT_CHARS = 220

# $ per million tokens (in, out). Gemini figures are the Vertex AI global-endpoint
# rates; note Flash-Lite bills output at 8x input, and reasoning counts as
# output -- which is why the prompt caps fact length and thinking is MINIMAL.
MODELS: dict[str, dict[str, Any]] = {
    "gemini-3.5-flash-lite": {"price": (0.30, 2.50)},
    # Prices below are placeholders pending verification -- they are here so an
    # experiment does not silently get billed at the fallback (most-expensive)
    # rate, which made a golden-set run report 18x the real cost.
    "gemini-3.1-flash-lite": {"price": (0.30, 2.50), "price_unverified": True},
    "gemini-3-flash-preview": {"price": (0.30, 2.50), "price_unverified": True},
    "gemini-3.5-flash": {"price": (0.60, 3.50), "price_unverified": True},
    "claude-haiku-4-5": {"price": (1.00, 5.00)},
    "claude-sonnet-5": {
        # Introductory rate through 2026-08-31, standard after.
        "price": (2.00, 10.00),
        "price_after": (3.00, 15.00),
    },
    "claude-opus-5": {"price": (5.00, 25.00)},
}
_INTRO_ENDS = date(2026, 8, 31)

# Gemini 3.5 Flash-Lite: cheapest of the four, GA, and supports structured
# output through both the Gemini Developer API and Vertex AI.
DEFAULT_MODEL = "gemini-3.5-flash-lite"

# Gate: an explicit request to remember bypasses the message counter entirely.
# Stems rather than whole words -- "запомни" alone misses "запомнить"/"запомни-ка".
REMEMBER_RE = re.compile(
    r"(запомн|не\s+забудь|запиши\s+себе|remember\s+(that|this)|don'?t\s+forget|"
    r"keep\s+in\s+mind|note\s+that\s+i)",
    re.IGNORECASE,
)

MESSAGES_PER_EXTRACTION = 10


def build_prompt(
    *,
    window: list[Any],
    candidates: list[dict[str, Any]],
    entities: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    session_date: str | None = None,
    agent_id: str | None = None,
    version: str = PROMPT_VERSION,
    today: str | None = None,
) -> str:
    """Render the active extractor prompt. The only prompt path in production.

    Everything a prompt could want is passed in and each version takes what it
    uses -- `prompts.render` ignores the rest -- so adding context to a new
    version does not change this signature.

    The context arguments are not decoration. Without `session_date` rule 3
    resolves "last month" against today's date, which is wrong for every
    backfilled window in a ten-month corpus. Without the project, rule 2 produces
    facts that say "this project" and nothing else.
    """
    return prompts.render(
        version,
        today=today or datetime.now(UTC).strftime("%Y-%m-%d"),
        window=render_window(window),
        candidates=render_candidates(candidates),
        entities=render_entities(entities or []),
        context=json.dumps(context or {}, ensure_ascii=False, sort_keys=True),
        session_date=session_date,
        agent_id=agent_id,
    )


TOOL = providers.anthropic_tool()  # kept for tests and docs


@dataclass
class Op:
    """One memory operation returned by the judge."""

    op: str
    reason: str
    id: str | None = None
    text: str | None = None
    kind: str | None = None
    context: dict[str, str] | None = None
    tags: list[str] | None = None
    importance: float | None = None
    confidence: float | None = None
    valid_until: str | None = None
    evidence: list[dict[str, Any]] | None = None
    # Routing, as integers into the ENTITIES block. Resolved to real ids by
    # judge.extract, exactly like candidate targets.
    scope: int | None = None
    subject: int | None = None
    # A person the model saw named but could not find in the block. Kept
    # verbatim so a human can say who was meant.
    subject_name: str | None = None
    # Filled in by apply_ops once routing resolves; not part of the schema.
    scope_id: str | None = None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Op | None:
        """Build an Op, discarding anything structurally unusable.

        Even in strict mode the schema cannot express "text is required when op
        is ADD", so the cross-field rules are enforced here.
        """
        op = (raw.get("op") or "").upper()
        if op not in ("ADD", "UPDATE", "DELETE"):
            return None
        if op in ("UPDATE", "DELETE") and not raw.get("id"):
            return None
        if op in ("ADD", "UPDATE") and not (raw.get("text") or "").strip():
            return None
        text = (raw.get("text") or "").strip()
        if op in ("ADD", "UPDATE") and len(text) > 200:
            return None
        kind = (raw.get("kind") or "fact").strip()
        if not kind or len(kind) > 64:
            return None
        entries = raw.get("context_entries") or []
        context: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            key = str(entry.get("key") or "").strip()
            value = str(entry.get("value") or "").strip()
            if not key or not value or len(key) > 64 or len(value) > 256:
                return None
            context[key] = value
        tags = [str(tag).strip() for tag in (raw.get("tags") or [])]
        if any(not tag or len(tag) > 64 for tag in tags) or len(tags) > 20:
            return None
        evidence = raw.get("evidence") or []
        if op in ("ADD", "UPDATE") and not evidence:
            return None
        parsed_evidence: list[dict[str, Any]] = []
        for citation in evidence:
            try:
                message_id = int(citation["message_id"])
                start = int(citation["start_char"])
                end = int(citation["end_char"])
            except (KeyError, TypeError, ValueError):
                return None
            quote = str(citation.get("quote") or "")
            if message_id <= 0 or ((start < 0 or end <= start) and not quote):
                return None
            parsed_evidence.append(
                {
                    "message_id": message_id,
                    "start_char": start,
                    "end_char": end,
                    **({"quote": quote} if quote else {}),
                }
            )
        scope = _positive_int(raw.get("scope"))
        subject = _positive_int(raw.get("subject"))
        subject_name = str(raw.get("subject_name") or "").strip() or None
        if subject_name and len(subject_name) > 128:
            return None
        # A resolved subject and an unresolved name are mutually exclusive: one
        # says "this person", the other says "somebody I could not place".
        if subject is not None and subject_name:
            subject_name = None
        return cls(
            op=op,
            reason=raw.get("reason") or "",
            id=raw.get("id"),
            text=text or None,
            kind=kind,
            context=context,
            tags=tags,
            importance=_clamp(raw.get("importance"), 0.6),
            confidence=_clamp(raw.get("confidence"), 0.9),
            valid_until=raw.get("valid_until"),
            evidence=parsed_evidence,
            scope=scope,
            subject=subject,
            subject_name=subject_name,
        )


def _positive_int(value: Any) -> int | None:
    """An entity reference, or None. Anything else is not a reference."""
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def _clamp(value: Any, default: float) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


@dataclass
class JudgeResult:
    ops: list[Op]
    judge_run_id: int | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    error: str | None = None
    # UPDATE/DELETE ops whose candidate reference did not resolve — the model
    # cited an id it was never shown. Dropped here (a fabricated target must
    # not reach apply_ops) and surfaced so the extraction outcome can count
    # them as rejections instead of losing them silently.
    unknown_candidates: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    # Integer -> entity id for the block the model was shown, so a logged run
    # stays explainable and apply_ops can resolve what it returned.
    entity_map: dict[str, str] = dataclasses.field(default_factory=dict)
    # Operations naming an entity number that was never shown: fabricated
    # rather than mistyped, and dropped for the same reason as candidates.
    unknown_entities: list[dict[str, Any]] = dataclasses.field(default_factory=list)


def price_per_mtok(model: str = DEFAULT_MODEL, when: date | None = None) -> tuple[float, float]:
    spec = MODELS.get(model)
    if spec is None:
        # Unknown model: price it as the most expensive one we know, so an
        # unrecognised id can never quietly under-report against the ceiling.
        return max(m["price"] for m in MODELS.values())
    when = when or datetime.now(UTC).date()
    if "price_after" in spec and when > _INTRO_ENDS:
        return spec["price_after"]
    return spec["price"]


def cost_of(
    input_tokens: int,
    output_tokens: int,
    when: date | None = None,
    model: str = DEFAULT_MODEL,
) -> float:
    p_in, p_out = price_per_mtok(model, when)
    return input_tokens * p_in / 1_000_000 + output_tokens * p_out / 1_000_000


def provider_of(model: str) -> str:
    return providers.provider_of(model)


def month_spend_usd(conn: psycopg.Connection) -> float:
    """Total judge spend in the current calendar month."""
    period = datetime.now(UTC).strftime("%Y-%m")
    row = conn.execute(
        """SELECT COALESCE(SUM(cost_usd), 0) AS s FROM judge_runs
            WHERE to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM') = %s""",
        (period,),
    ).fetchone()
    return float(row["s"]) if row else 0.0


def estimate_backfill(conn: psycopg.Connection, *, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Shared backlog/cost estimate for the CLI and admin dashboard."""
    pending = conn.execute(
        """SELECT session_id, COUNT(*) AS n FROM messages
            WHERE NOT processed GROUP BY session_id"""
    ).fetchall()
    messages = sum(int(row["n"]) for row in pending)
    windows = sum(-(-int(row["n"]) // MESSAGES_PER_EXTRACTION) for row in pending)
    measured = conn.execute(
        """SELECT AVG(input_tokens) i, AVG(output_tokens) o, COUNT(*) n
             FROM judge_runs WHERE error IS NULL AND input_tokens > 0"""
    ).fetchone()
    if measured["n"]:
        per_in = float(measured["i"])
        per_out = float(measured["o"])
        basis = f"measured over {measured['n']} real calls"
    else:
        per_in, per_out = 1200.0, 150.0
        basis = "docs estimate"
    return {
        "sessions": len(pending),
        "messages": messages,
        "windows": windows,
        "input_tokens_per_call": round(per_in),
        "output_tokens_per_call": round(per_out),
        "basis": basis,
        "estimated_cost_usd": round(windows * cost_of(int(per_in), int(per_out), model=model), 6),
    }


def should_extract(*, messages_since_last: int, session_closed: bool, text: str = "") -> bool:
    """docs/04-judge.md gate.

    Grouping messages is about quality before cost: a ten-message window
    resolves the pronouns a single line cannot.
    """
    return (
        session_closed
        or messages_since_last >= MESSAGES_PER_EXTRACTION
        or bool(REMEMBER_RE.search(text))
    )


def render_window(messages: list[Any]) -> str:
    """Render the window, truncating assistant turns.

    The user's own words go in whole -- they are the source material. Assistant
    turns are clipped to ``ASSISTANT_CONTEXT_CHARS`` because in a coding-agent
    corpus they are 2000-character work logs, and a window dominated by them
    produces a summary of the work log instead of a fact about the user.
    """
    lines = []
    for m in messages:
        role = m["role"]
        content = m["content"] or ""
        mid = m["id"] if not isinstance(m, dict) else m.get("id")
        if role == "assistant" and len(content) > ASSISTANT_CONTEXT_CHARS:
            content = content[:ASSISTANT_CONTEXT_CHARS].rstrip() + " […truncated]"
        lines.append(f"[{mid}] {role}: {content}")
    return "\n".join(lines)


def render_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "(none)"
    return "\n".join(
        f"- id={c['id']} kind={c.get('kind')} context={c.get('context', {})} "
        f"importance={c.get('importance')}: {c['text']}"
        for c in candidates
    )


def render_entities(entities: list[dict[str, Any]]) -> str:
    """The ENTITIES block: numbered, labelled, with the aliases people say.

    Aliases are the point. Conversation says "Саша" or "the shop", and without
    them a fact about a teammate has nothing to attach to.
    """
    if not entities:
        return "(none)"
    lines = []
    for item in entities:
        aliases = ", ".join(item.get("aliases") or [])
        suffix = f" — aliases: {aliases}" if aliases else ""
        lines.append(f"{item['ref']}. {item['label']}: {item['name']}{suffix}")
    return "\n".join(lines)


def extract(
    conn: psycopg.Connection,
    *,
    window: list[Any],
    candidates: list[dict[str, Any]],
    entities: list[dict[str, Any]] | None = None,
    monthly_limit_usd: float,
    api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    model: str = DEFAULT_MODEL,
    effort: str = "low",
    context: dict[str, Any] | None = None,
    session_date: str | None = None,
    agent_id: str | None = None,
    version: str | None = None,
    user_id: str | None = None,
    job_id: str | None = None,
) -> JudgeResult:
    """Call the judge and log the run.

    ``version`` overrides the active prompt version, which is what
    ``POST /v1/admin/reextract`` needs: docs/04-judge.md's whole argument for
    recording `extraction_version` is that two versions can be compared on one
    eval, and that is only possible if an old version can be replayed on demand.

    Every call is recorded in `judge_runs` whether it succeeds or fails --
    docs/06-roadmap.md is right that reading those rows by eye for the first
    week is the most useful thing in the project, and a failed call is often the
    most informative row in the table.
    """
    active_version = version or PROMPT_VERSION
    context, _ = security.redact_value(context or {})
    # The model sees small integers, never real memory ids: a UUID shown to an
    # LLM comes back subtly mutated often enough that hallucinated targets were
    # a real failure class. Integers are copied faithfully, and anything outside
    # the map is provably fabricated rather than plausibly mistyped.
    id_map = {str(i + 1): c["id"] for i, c in enumerate(candidates)}
    display_candidates = [{**c, "id": str(i + 1)} for i, c in enumerate(candidates)]
    # Entities are numbered the same way and for the same reason. The numbering
    # is stable within a call and recorded with the run, so a stored operation
    # can be explained later.
    entity_list = entities or []
    entity_map = {str(i + 1): item["id"] for i, item in enumerate(entity_list)}
    display_entities = [{**item, "ref": i + 1} for i, item in enumerate(entity_list)]
    prompt = build_prompt(
        window=window,
        candidates=display_candidates,
        entities=display_entities,
        context=context,
        session_date=session_date,
        agent_id=agent_id,
        version=active_version,
    )
    payload = {
        "prompt_version": active_version,
        "model": model,
        "window_size": len(window),
        "candidate_ids": [c["id"] for c in candidates],
        # The integer aliases the model saw, so a logged run stays explainable.
        "candidate_map": id_map,
        "entity_map": entity_map,
        "message_ids": [int(m["id"]) for m in window],
        # Recorded so a run can be explained later without re-deriving the
        # Context and date make the model input independently auditable.
        "context": context or {},
        "session_date": session_date,
        "agent_id": agent_id,
    }

    from .retrieval import _token_count

    # A UTF-8 byte count is a conservative cross-provider upper bound even
    # when the provider tokenizer differs from our exact local tokenizer.
    estimated_input = max(_token_count(prompt), len(prompt.encode("utf-8")))
    maximum_cost = cost_of(estimated_input, 4096, model=model)
    period = datetime.now(UTC).strftime("%Y-%m")
    try:
        reservation_id = jobs.reserve_budget(
            conn,
            period=period,
            amount_usd=maximum_cost,
            limit_usd=monthly_limit_usd,
            job_id=job_id,
        )
    except jobs.BudgetExceeded:
        return JudgeResult([], None, 0, 0, 0.0, 0, error="monthly_cost_limit_reached")

    if job_id:
        try:
            jobs.consume_call(conn, job_id)
        except jobs.CallLimitExceeded:
            jobs.release_budget(conn, reservation_id)
            return JudgeResult([], None, 0, 0, 0.0, 0, error="job_call_limit_reached")

    prompt = security.redact(prompt).text
    t0 = time.perf_counter()
    error: str | None = None
    ops: list[Op] = []
    unknown_candidates: list[dict[str, Any]] = []
    unknown_entities: list[dict[str, Any]] = []
    in_tok = out_tok = 0
    raw_output: Any = None

    try:
        res = providers.call(
            model=model,
            prompt=prompt,
            anthropic_api_key=api_key,
            gemini_api_key=gemini_api_key,
            project=project,
            location=location,
            effort=effort,
        )
        in_tok, out_tok = res.input_tokens, res.output_tokens
        raw_output, error = res.raw, res.error
        # Op.parse is the real gate on both providers: no response schema can
        # express "text is required when op is ADD".
        ops = [op for op in (Op.parse(r) for r in res.operations) if op is not None]
        resolved: list[Op] = []
        for op in ops:
            if op.op in ("UPDATE", "DELETE"):
                target = id_map.get(str(op.id))
                if target is None:
                    unknown_candidates.append({"op": op.op, "id": op.id})
                    continue
                op.id = target
            # A reference outside the block is fabricated, not mistyped, so the
            # operation is dropped rather than routed somewhere plausible.
            if op.scope is not None and str(op.scope) not in entity_map:
                unknown_entities.append({"op": op.op, "ref": op.scope, "field": "scope"})
                continue
            if op.subject is not None and str(op.subject) not in entity_map:
                unknown_entities.append({"op": op.op, "ref": op.subject, "field": "subject"})
                continue
            resolved.append(op)
        ops = resolved
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("judge call failed: %s", error)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    cost = cost_of(in_tok, out_tok, model=model)
    if error and in_tok == 0 and out_tok == 0:
        # No token counts came back, so the real cost is unknown. It used to be
        # recorded as `maximum_cost` -- the reservation ceiling, which assumes a
        # full 4096-token completion on top of a UTF-8-byte input estimate. Since
        # reserve_budget sums judge_runs.cost_usd, a run of failures (a bad key,
        # a Qdrant outage loop) exhausted the monthly ceiling on spend that was
        # never billed, with no way to reconcile it.
        if providers.is_unbilled(error):
            cost = 0.0
            error = f"unbilled: {error}"
        else:
            # Possibly billed for the prompt, certainly not for a completion
            # that never arrived.
            cost = cost_of(estimated_input, 0, model=model)
            error = f"cost_unknown: {error}"

    # The run row and its cost reconciliation land together: a logged call
    # whose reservation stayed active would double-count against the ceiling.
    with conn.transaction():
        run = conn.execute(
            """INSERT INTO judge_runs
               (user_id,job_id,kind,model,prompt_version,input,output,error,
                input_tokens,output_tokens,cost_usd,latency_ms,created_at)
               VALUES (%s,%s,'extract',%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
               RETURNING id""",
            (
                user_id,
                job_id,
                model,
                active_version,
                Jsonb(payload),
                Jsonb(raw_output) if raw_output else None,
                error,
                in_tok,
                out_tok,
                cost,
                latency_ms,
            ),
        ).fetchone()
        if run is None:  # pragma: no cover - RETURNING cannot be empty here
            raise RuntimeError("judge_runs insert returned no row")
        conn.execute(
            """UPDATE budget_reservations
                  SET actual_usd=%s,status='reconciled',updated_at=now() WHERE id=%s""",
            (cost, reservation_id),
        )
    return JudgeResult(
        ops=ops,
        judge_run_id=int(run["id"]),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        latency_ms=latency_ms,
        error=error,
        unknown_candidates=unknown_candidates,
        entity_map=entity_map,
        unknown_entities=unknown_entities,
    )
