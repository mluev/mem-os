"""The extractor: turns a window of conversation into memory operations.

The default judge is **Gemini 3.5 Flash-Lite**, not the
`claude-haiku-4-5` of docs/04-judge.md. The doc's Haiku pricing was accurate
($1/$5 per Mtok, and Batch really is half price), but Flash-Lite is cheaper
still, Google recommends it for exactly this shape of work, and it bills to
Google Cloud where this deployment's credits live. Claude models still work --
see `providers.py` -- so the two can be compared on the same eval.

Key-only auth uses the Gemini Developer API. Project auth uses Vertex AI.

Cost, per call at v2 window sizes:

    gemini-3.5-flash-lite   $0.0009
    claude-haiku-4-5        $0.0023
    claude-sonnet-5         $0.0046

Flash-Lite bills output at 8x input ($2.50 against $0.30) and counts reasoning
as output, which is why the prompt caps fact length and thinking is MINIMAL.

Corrections to the doc's contract:

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

from . import providers

logger = logging.getLogger(__name__)

PROMPT_VERSION = "v3"

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


SYSTEM_PROMPT = """You extract long-term memories from a conversation.

THE TEST FOR EVERY MEMORY
Would this still be worth knowing in three months? If it is only true of this
one session's work, it is not a memory. A changelog is not a memory.

  BAD  "Merged PR #203, fixed 3 stale test suites, 162/162 suites green"
  GOOD "Auth for the API lives in auth/ and uses session cookies, not JWT"

  BAD  "User implemented converting LMS subpages into modal/drawer patterns,
        built side-drawer editors at 880px, deleted old route-level files"
  GOOD "Prefers drawer/modal editors over separate route pages in the LMS UI"

RULES

1. ONE FACT PER OPERATION, AT MOST TWO SENTENCES, UNDER 200 CHARACTERS.
   If you are writing a list, a summary, or anything with semicolons joining
   unrelated points, you are writing a changelog. Split it or drop it.
2. Self-contained. Someone reading it in a year, with no other context, must
   understand it. Never write "he", "it", "this project".
3. Resolve relative time to absolute dates. Today is {today}.
   "last month" -> "(June 2026)".
4. Store what is true about the user and their world. Do NOT store what the
   assistant did. The assistant's turns are context only -- they are there so
   you can resolve "it" and "that project", never as source material. Prefixing
   "User implemented..." to a summary of the assistant's work does not make it
   a fact about the user.
5. All three scopes matter, and each earns its keep differently:
     scope=user     durable across every project -- preferences, identity,
                    skills, working style, tools they insist on
     scope=project  durable for the life of one codebase -- where things live,
                    architectural decisions and the reason behind them
     scope=task     only for genuinely short-lived work; these expire in days
   A window of technical work usually contains BOTH: what the user prefers in
   general, and what was decided about this codebase. Look for both. If you
   emit only project facts from a long conversation, you have probably missed
   the user's preferences hiding in how they asked for things.
6. If new information contradicts or refines a CANDIDATE, emit UPDATE with
   that candidate's id. Do not emit ADD.
7. Returning an empty operations list is correct and common. Most windows
   contain nothing worth remembering.
8. Write the memory in the same language the user used.
9. Never store credentials, tokens, keys, connection strings, file contents,
   or command output. If a message contains them, extract only the surrounding
   intent, never the value.

TASK WORKFLOW STATUS
Set task_status only for type=task and only when the conversation is explicit:
  todo     clearly planned, assigned, requested, or not yet started
  doing    explicitly in progress now
  done     explicitly completed, fixed, shipped, or resolved
  unknown  the task exists but its workflow state is unclear
For non-task memories task_status must be null. Do not guess progress from tone.

IMPORTANCE -- use the full range; do not cluster everything in the middle
  0.9-1.0  identity and hard constraints: who they are, what they will not do,
           things that should shape almost every answer
  0.7-0.8  strong stable preferences and real skills: tools they insist on,
           languages they work in daily, firm architectural positions
  0.4-0.6  useful but narrow: where one module lives, one decision's reason
  0.1-0.3  weak signal, mentioned once, probably situational
  below    do not emit at all
A single conversation should not produce five facts all at 0.5. Differentiate.

CANDIDATES (existing memories, may be empty)
{candidates}

CONVERSATION WINDOW
Assistant turns are truncated on purpose: they are context, not content.
{window}"""


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
        return cls(
            op=op,
            reason=raw.get("reason") or "",
            id=raw.get("id"),
            text=(raw.get("text") or "").strip() or None,
            type=raw.get("type"),
            scope=raw.get("scope") or "user",
            importance=_clamp(raw.get("importance"), 0.6),
            confidence=_clamp(raw.get("confidence"), 0.9),
            valid_until=raw.get("valid_until"),
            task_status=task_status,
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
) -> JudgeResult:
    """Call the judge and log the run.

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

    prompt = SYSTEM_PROMPT.format(
        today=datetime.now(UTC).strftime("%Y-%m-%d"),
        candidates=render_candidates(candidates),
        window=render_window(window),
    )
    payload = {
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "window_size": len(window),
        "candidate_ids": [c["id"] for c in candidates],
        "message_ids": [int(m["id"]) for m in window],
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
            model, PROMPT_VERSION, json.dumps(payload, ensure_ascii=False),
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
