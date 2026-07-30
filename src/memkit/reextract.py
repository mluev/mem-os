"""Replay history under a different prompt version.

`docs/04-judge.md` argues for recording `extraction_version` on every fact so two
versions can be compared on one eval and a bad one rolled back. That argument only
holds if an old version can actually be replayed, which is what this does and what
`POST /v1/admin/reextract` promised from the start without ever existing.

The contract from `docs/03-api.md`, and how it is met:

* **Old facts are not overwritten.** A fresh set is produced under the requested
  version and the facts sourced from the same messages are marked `superseded`.
  Nothing is deleted, so `POST /v1/admin/memories/bulk` with `op="restore"` is a
  complete rollback.
* **`dry_run` first, always.** It counts windows and prices them from measured token
  usage, and makes no calls.
* **`use_batch` is rejected, not ignored.** The doc offers it at half price; this
  service does not implement Gemini's Batch API, and silently accepting the flag
  would report a discount that was never applied. A silently-ignored parameter is
  exactly the class of defect that made `scopes` useless for months.

Order of operations is deliberate. The candidate block excludes the facts being
replaced, so the judge cannot emit UPDATE against them and mutate the old set in
place — which would destroy the comparison the operation exists to enable. The old
set is superseded only after the new one is written, so a failure halfway leaves both
sets intact rather than losing the old one.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient

from . import extract, judge, mutate, prompts
from .embed import Embedder

logger = logging.getLogger(__name__)


@dataclass
class Plan:
    """What a re-extraction would do, before it does anything."""

    messages: int = 0
    sessions: int = 0
    windows: int = 0
    replaces: int = 0
    input_tokens_per_call: int = 0
    output_tokens_per_call: int = 0
    basis: str = ""
    estimated_cost_usd: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "messages_to_process": self.messages,
            "sessions": self.sessions,
            "estimated_calls": self.windows,
            "facts_to_supersede": self.replaces,
            "input_tokens_per_call": self.input_tokens_per_call,
            "output_tokens_per_call": self.output_tokens_per_call,
            "basis": self.basis,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
        }


@dataclass
class Outcome:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    superseded: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    superseded_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "skipped": self.skipped,
            "superseded": self.superseded,
            "calls": self.calls,
            "cost_usd": round(self.cost_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            # Returned so a rollback is one bulk restore away, not an archaeology
            # exercise against updated_at.
            "superseded_ids": self.superseded_ids,
            "errors": self.errors,
        }


def _windows(
    conn: sqlite3.Connection, *, owner_id: str, from_date: str | None
) -> list[list[sqlite3.Row]]:
    """Split the selected history into windows the way live extraction would.

    Same window size and the same "no user turn, no window" rule, so a replay is
    comparable to the original run rather than to a differently-sliced corpus.
    """
    params: list[Any] = [owner_id]
    clause = ""
    if from_date:
        clause = " AND m.created_at >= ?"
        params.append(from_date)
    rows = conn.execute(
        f"""SELECT m.id, m.session_id, m.role, m.content, m.created_at
              FROM messages m JOIN sessions s ON s.id = m.session_id
             WHERE s.owner_id = ?{clause}
             ORDER BY m.session_id, m.id""",
        params,
    ).fetchall()

    windows: list[list[sqlite3.Row]] = []
    current: list[sqlite3.Row] = []
    session: str | None = None
    for row in rows:
        if row["session_id"] != session or len(current) >= extract.WINDOW_SIZE:
            if current:
                windows.append(current)
            current, session = [], row["session_id"]
        current.append(row)
    if current:
        windows.append(current)
    # A window with no user turn cannot yield a fact about the user, and paying for
    # it is what the live path's fast-forward exists to avoid.
    return [w for w in windows if any(r["role"] == "user" for r in w)]


def _facts_from(
    conn: sqlite3.Connection, *, owner_id: str, message_ids: list[int]
) -> list[str]:
    if not message_ids:
        return []
    placeholders = ",".join("?" for _ in message_ids)
    rows = conn.execute(
        f"""SELECT DISTINCT m.id FROM memories m
              JOIN memory_sources ms ON ms.memory_id = m.id
             WHERE m.owner_id = ? AND m.status = 'active'
               AND ms.message_id IN ({placeholders})""",
        (owner_id, *message_ids),
    ).fetchall()
    return [row["id"] for row in rows]


def _fully_covered(
    conn: sqlite3.Connection, *, memory_id: str, processed: set[int]
) -> bool:
    """Whether every message this fact was drawn from has been re-read."""
    rows = conn.execute(
        "SELECT message_id FROM memory_sources WHERE memory_id = ?", (memory_id,)
    ).fetchall()
    return bool(rows) and all(int(r["message_id"]) in processed for r in rows)


def plan(
    conn: sqlite3.Connection,
    *,
    owner_id: str,
    from_date: str | None,
    model: str,
) -> Plan:
    windows = _windows(conn, owner_id=owner_id, from_date=from_date)
    message_ids = [int(r["id"]) for w in windows for r in w]
    measured = conn.execute(
        """SELECT AVG(input_tokens) i, AVG(output_tokens) o, COUNT(*) n
             FROM judge_runs
            WHERE kind = 'extract' AND error IS NULL AND input_tokens > 0"""
    ).fetchone()
    if measured["n"]:
        per_in, per_out = float(measured["i"]), float(measured["o"])
        basis = f"measured over {measured['n']} real calls"
    else:
        per_in, per_out = 1200.0, 150.0
        basis = "docs estimate"
    return Plan(
        messages=len(message_ids),
        sessions=len({r["session_id"] for w in windows for r in w}),
        windows=len(windows),
        replaces=len(_facts_from(conn, owner_id=owner_id, message_ids=message_ids)),
        input_tokens_per_call=round(per_in),
        output_tokens_per_call=round(per_out),
        basis=basis,
        estimated_cost_usd=len(windows)
        * judge.cost_of(int(per_in), int(per_out), model=model),
    )


def run(
    conn: sqlite3.Connection,
    client: QdrantClient,
    embedder: Embedder,
    *,
    owner_id: str,
    from_date: str | None,
    version: str,
    model: str,
    monthly_limit_usd: float,
    anthropic_api_key: str = "",
    gemini_api_key: str = "",
    project: str = "",
    location: str = "",
    max_calls: int = 0,
) -> Outcome:
    """Replay the selected history under `version`. Caller owns the transaction."""
    if version not in prompts.REGISTRY:
        raise ValueError(
            f"unknown prompt version {version!r}; "
            f"known: {', '.join(sorted(prompts.REGISTRY))}"
        )

    out = Outcome()
    windows = _windows(conn, owner_id=owner_id, from_date=from_date)
    all_ids = [int(r["id"]) for w in windows for r in w]
    # Excluded from the candidate block across the whole selection, so a partial run
    # still cannot UPDATE a fact it is meant to replace.
    replacing = _facts_from(conn, owner_id=owner_id, message_ids=all_ids)
    limit = max_calls or len(windows)
    # Superseded only for windows actually re-read. With max_calls set, retiring the
    # whole selection would drop facts whose messages were never re-processed --
    # deleting evidence in exchange for nothing.
    processed_ids: list[int] = []

    for window in windows:
        if out.calls >= limit:
            break
        scope_key = extract._session_project(conn, window[0]["session_id"])
        candidates = extract.find_candidates(
            client, embedder, window=window, owner_id=owner_id,
            exclude_ids=replacing,
        )
        result = judge.extract(
            conn,
            window=window,
            candidates=candidates,
            api_key=anthropic_api_key,
            gemini_api_key=gemini_api_key,
            project=project,
            location=location,
            monthly_limit_usd=monthly_limit_usd,
            model=model,
            scope_key=scope_key,
            session_date=extract._session_date(window),
            version=version,
        )
        if result.error == "monthly_cost_limit_reached":
            out.errors.append(result.error)
            break
        out.calls += 1
        out.cost_usd += result.cost_usd
        out.input_tokens += result.input_tokens
        out.output_tokens += result.output_tokens
        if result.error:
            out.errors.append(result.error)
            continue
        applied = extract.apply_ops(
            conn, client, embedder,
            ops=result.ops, owner_id=owner_id, agent_id=None,
            scope_key=scope_key, judge_run_id=result.judge_run_id,
            source_message_ids=[int(r["id"]) for r in window],
            version=version,
        )
        out.added += applied.added
        out.updated += applied.updated
        out.skipped += applied.skipped
        processed_ids.extend(int(r["id"]) for r in window)

    # Superseded last: a failure above leaves both sets intact, and the ids come back
    # in the response so a rollback is one bulk restore.
    retiring = _facts_from(conn, owner_id=owner_id, message_ids=processed_ids)
    # A fact drawn from both a re-read window and an untouched one stays: half its
    # evidence has not been replaced.
    retiring = [
        memory_id
        for memory_id in retiring
        if memory_id in set(replacing) and _fully_covered(
            conn, memory_id=memory_id, processed=set(processed_ids)
        )
    ]
    if out.added:
        for memory_id in retiring:
            try:
                mutate.set_status(
                    conn, client, embedder, memory_id=memory_id, status="superseded"
                ).apply_index(client)
                out.superseded += 1
                out.superseded_ids.append(memory_id)
            except mutate.MutationError as exc:
                out.errors.append(f"{memory_id}: {exc}")
    else:
        # Nothing new was produced, so replacing the old set would be a pure loss.
        logger.warning("re-extraction produced no facts; old set left active")
    return out
