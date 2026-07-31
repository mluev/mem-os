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

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from . import prompts, providers

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

MEMORY_TYPES = providers.MEMORY_TYPES
SCOPES = providers.SCOPES

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
    scope_key: str | None = None,
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
        project=scope_key,
        session_date=session_date,
        agent_id=agent_id,
    )


TOOL = providers.anthropic_tool()   # kept for tests and docs


@dataclass
class Op:
    """One memory operation returned by the judge."""

    op: str
    reason: str
    id: str | None = None
    text: str | None = None
    type: str | None = None
    scope: str | None = None
    importance: float | None = None
    confidence: float | None = None
    valid_until: str | None = None
    task_status: str | None = None
    # The model's own answer to the travel test, kept for the eval and for reading
    # judge_runs by eye. `scope` above is already corrected from it.
    holds_in_other_repos: bool | None = None

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
        if op == "ADD" and raw.get("type") not in MEMORY_TYPES:
            return None
        task_status = raw.get("task_status")
        if task_status not in ("unknown", "todo", "doing", "done"):
            task_status = None
        if raw.get("type") not in (None, "task"):
            task_status = None
        # An out-of-vocabulary scope is worse than a wrong one: it satisfies no
        # branch of the read path's should-clause, so the fact is written to
        # SQLite and Qdrant and can never be retrieved. Fall back to the scope
        # that is always readable, the same way task_status falls back above.
        scope = raw.get("scope")
        if scope not in SCOPES:
            scope = "user"
        # The travel test, applied by code rather than trusted to the model.
        # Measured under v4: 41 of 62 facts came back scope=project and roughly 17
        # of those were personal preferences bound to a repository only by their
        # wording, leaving 34% of the store reachable without naming a project.
        # v6 makes the model answer "would this sentence still be true in another
        # project?" separately, and the promotion happens here.
        #
        # One-directional on purpose: project -> user only. A user-scoped fact is
        # never demoted, so this cannot regress the direction that was measured.
        # Versions before v6 do not ask the question and return null, which leaves
        # them byte-identical on the same eval.
        if scope == "project" and raw.get("holds_in_other_repos") is True:
            scope = "user"
        return cls(
            op=op,
            reason=raw.get("reason") or "",
            id=raw.get("id"),
            text=(raw.get("text") or "").strip() or None,
            type=raw.get("type"),
            scope=scope,
            importance=_clamp(raw.get("importance"), 0.6),
            confidence=_clamp(raw.get("confidence"), 0.9),
            valid_until=raw.get("valid_until"),
            task_status=task_status,
            holds_in_other_repos=(
                raw["holds_in_other_repos"]
                if isinstance(raw.get("holds_in_other_repos"), bool)
                else None
            ),
        )


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


def price_per_mtok(
    model: str = DEFAULT_MODEL, when: date | None = None
) -> tuple[float, float]:
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


def month_spend_usd(conn: sqlite3.Connection) -> float:
    """Total judge spend in the current calendar month."""
    prefix = datetime.now(UTC).strftime("%Y-%m")
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) s FROM judge_runs WHERE created_at LIKE ?",
        (f"{prefix}%",),
    ).fetchone()
    return float(row["s"])


def estimate_backfill(
    conn: sqlite3.Connection, *, model: str = DEFAULT_MODEL
) -> dict[str, Any]:
    """Shared backlog/cost estimate for the CLI and admin dashboard."""
    pending = conn.execute(
        """SELECT session_id, COUNT(*) n FROM messages
            WHERE processed = 0 GROUP BY session_id"""
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
        "estimated_cost_usd": round(
            windows * cost_of(int(per_in), int(per_out), model=model), 6
        ),
    }


def should_extract(
    *, messages_since_last: int, session_closed: bool, text: str = ""
) -> bool:
    """docs/04-judge.md gate.

    Grouping messages is about quality before cost: a ten-message window
    resolves the pronouns a single line cannot.
    """
    return (
        session_closed
        or messages_since_last >= MESSAGES_PER_EXTRACTION
        or bool(REMEMBER_RE.search(text))
    )


def render_window(messages: list[sqlite3.Row | dict[str, Any]]) -> str:
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
        f"- id={c['id']} type={c.get('type')} "
        f"task_status={c.get('task_status')} importance={c.get('importance')}: "
        f"{c['text']}"
        for c in candidates
    )


def extract(
    conn: sqlite3.Connection,
    *,
    window: list[Any],
    candidates: list[dict[str, Any]],
    monthly_limit_usd: float,
    api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    model: str = DEFAULT_MODEL,
    effort: str = "low",
    scope_key: str | None = None,
    session_date: str | None = None,
    agent_id: str | None = None,
    version: str | None = None,
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
    spent = month_spend_usd(conn)
    if spent >= monthly_limit_usd:
        # A single runaway loop can eat a month of budget in an hour, so this is
        # enforced in code rather than watched on a dashboard.
        logger.error(
            "judge paused: $%.2f spent this month exceeds the $%.2f limit",
            spent, monthly_limit_usd,
        )
        return JudgeResult([], None, 0, 0, 0.0, 0, error="monthly_cost_limit_reached")

    active_version = version or PROMPT_VERSION
    prompt = build_prompt(
        window=window,
        candidates=candidates,
        scope_key=scope_key,
        session_date=session_date,
        agent_id=agent_id,
        version=active_version,
    )
    payload = {
        "prompt_version": active_version,
        "model": model,
        "window_size": len(window),
        "candidate_ids": [c["id"] for c in candidates],
        "message_ids": [int(m["id"]) for m in window],
        # Recorded so a run can be explained later without re-deriving the
        # context: which project and which conversation date the prompt saw.
        "scope_key": scope_key,
        "session_date": session_date,
        "agent_id": agent_id,
    }

    t0 = time.perf_counter()
    error: str | None = None
    ops: list[Op] = []
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
    except Exception as exc:  # noqa: BLE001 - logged, then surfaced to the caller
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("judge call failed: %s", error)

    latency_ms = int((time.perf_counter() - t0) * 1000)
    cost = cost_of(in_tok, out_tok, model=model)

    cur = conn.execute(
        """INSERT INTO judge_runs
           (kind, model, prompt_version, input_json, output_json, error,
            input_tokens, output_tokens, cost_usd, latency_ms, created_at)
           VALUES ('extract', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            model, active_version, json.dumps(payload, ensure_ascii=False),
            json.dumps(raw_output, ensure_ascii=False) if raw_output else None,
            error, in_tok, out_tok, cost, latency_ms,
            datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        ),
    )
    return JudgeResult(
        ops=ops,
        judge_run_id=int(cur.lastrowid),
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        latency_ms=latency_ms,
        error=error,
    )
