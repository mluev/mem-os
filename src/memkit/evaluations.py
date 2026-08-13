"""Blinded four-arm evaluations scored only by a human reviewer."""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from typing import Any

from .db import transaction, utcnow

ARM_NAMES = ("no_memory", "current_memory", "reviewed_v7", "oracle_memory")
LABELS = ("A", "B", "C", "D")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def create(
    conn: sqlite3.Connection,
    *,
    model: str,
    cases: list[dict[str, Any]],
    rubric: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not cases or len(cases) > 32:
        raise ValueError("an evaluation requires 1–32 cases")
    evaluation_id = str(uuid.uuid4())
    now = utcnow()
    with transaction(conn):
        conn.execute(
            """INSERT INTO evaluation_runs
               (id,status,model,rubric_json,created_at,updated_at)
               VALUES (?,'ready',?,?,?,?)""",
            (
                evaluation_id,
                model,
                _json(
                    rubric
                    or {
                        "judge": "human-only",
                        "criteria": ["correctness", "helpfulness", "safety"],
                    }
                ),
                now,
                now,
            ),
        )
        for index, case in enumerate(cases):
            arms = case.get("arms") or {}
            if set(arms) != set(ARM_NAMES):
                raise ValueError(f"case {index + 1} must contain all four named arms")
            shuffled = list(ARM_NAMES)
            secrets.SystemRandom().shuffle(shuffled)
            order = dict(zip(LABELS, shuffled, strict=True))
            conn.execute(
                """INSERT INTO evaluation_cases
                   (id,evaluation_id,case_key,prompt,arms_json,order_json)
                   VALUES (?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()),
                    evaluation_id,
                    str(case.get("case_key") or f"case-{index + 1:02d}"),
                    str(case.get("prompt") or "").strip(),
                    _json(arms),
                    _json(order),
                ),
            )
    return {"id": evaluation_id, "status": "ready", "cases": len(cases), "model": model}


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        _run(row) for row in conn.execute("SELECT * FROM evaluation_runs ORDER BY created_at DESC")
    ]


def _run(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["rubric"] = json.loads(value.pop("rubric_json"))
    value["summary"] = json.loads(value.pop("summary_json"))
    return value


def get_run(conn: sqlite3.Connection, evaluation_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM evaluation_runs WHERE id=?", (evaluation_id,)).fetchone()
    if row is None:
        raise LookupError(evaluation_id)
    value = _run(row)
    counts = conn.execute(
        """SELECT COUNT(*) total,COUNT(review_json) reviewed
             FROM evaluation_cases WHERE evaluation_id=?""",
        (evaluation_id,),
    ).fetchone()
    value.update({"total_cases": int(counts["total"]), "reviewed_cases": int(counts["reviewed"])})
    return value


def get_case(
    conn: sqlite3.Connection, *, evaluation_id: str, case_id: str, reveal: bool = False
) -> dict[str, Any]:
    run = get_run(conn, evaluation_id)
    row = conn.execute(
        "SELECT * FROM evaluation_cases WHERE id=? AND evaluation_id=?",
        (case_id, evaluation_id),
    ).fetchone()
    if row is None:
        raise LookupError(case_id)
    arms = json.loads(row["arms_json"])
    order = json.loads(row["order_json"])
    result = {
        "id": row["id"],
        "case_key": row["case_key"],
        "prompt": row["prompt"],
        "arms": {label: arms[name] for label, name in order.items()},
        "review": json.loads(row["review_json"]) if row["review_json"] else None,
    }
    if reveal or run["status"] == "complete":
        result["mapping"] = order
    return result


def list_cases(conn: sqlite3.Connection, *, evaluation_id: str) -> list[dict[str, Any]]:
    run = get_run(conn, evaluation_id)
    rows = conn.execute(
        "SELECT id FROM evaluation_cases WHERE evaluation_id=? ORDER BY case_key,id",
        (evaluation_id,),
    ).fetchall()
    return [
        get_case(
            conn,
            evaluation_id=evaluation_id,
            case_id=str(row["id"]),
            reveal=run["status"] == "complete",
        )
        for row in rows
    ]


def review_case(
    conn: sqlite3.Connection,
    *,
    evaluation_id: str,
    case_id: str,
    ranking: list[str],
    harmful: list[str],
    notes: str,
    current_vs_v7: str | None = None,
) -> dict[str, Any]:
    run = get_run(conn, evaluation_id)
    if run["status"] not in {"ready", "reviewing"}:
        raise RuntimeError("evaluation is not open for review")
    if sorted(ranking) != sorted(LABELS):
        raise ValueError("ranking must contain A, B, C, and D exactly once")
    if any(label not in LABELS for label in harmful):
        raise ValueError("harmful labels must be A, B, C, or D")
    if current_vs_v7 not in {None, "v7_win", "current_win", "tie"}:
        raise ValueError("current_vs_v7 must be v7_win, current_win, or tie")
    get_case(conn, evaluation_id=evaluation_id, case_id=case_id)
    review = {
        "ranking": ranking,
        "harmful": sorted(set(harmful)),
        "notes": notes.strip()[:2000],
        "judge": "human",
        "current_vs_v7": current_vs_v7,
    }
    with transaction(conn):
        conn.execute(
            """UPDATE evaluation_cases SET review_json=?,reviewed_at=?
                 WHERE id=? AND evaluation_id=?""",
            (_json(review), utcnow(), case_id, evaluation_id),
        )
        conn.execute(
            "UPDATE evaluation_runs SET status='reviewing',updated_at=? WHERE id=?",
            (utcnow(), evaluation_id),
        )
    return get_case(conn, evaluation_id=evaluation_id, case_id=case_id)


def finalize(conn: sqlite3.Connection, *, evaluation_id: str) -> dict[str, Any]:
    run = get_run(conn, evaluation_id)
    cases = list_cases(conn, evaluation_id=evaluation_id)
    if len(cases) != 32:
        raise RuntimeError("release evaluation requires exactly 32 cases")
    if any(case["review"] is None for case in cases):
        raise RuntimeError("every evaluation case requires human review")
    wins = losses = ties = harmful = 0
    for case in cases:
        row = conn.execute(
            "SELECT order_json FROM evaluation_cases WHERE id=?", (case["id"],)
        ).fetchone()
        mapping = json.loads(row["order_json"])
        labels = {arm: label for label, arm in mapping.items()}
        ranking = case["review"]["ranking"]
        v7_position = ranking.index(labels["reviewed_v7"])
        current_position = ranking.index(labels["current_memory"])
        comparison = case["review"].get("current_vs_v7")
        if comparison == "v7_win" or (comparison is None and v7_position < current_position):
            wins += 1
        elif comparison == "current_win" or (comparison is None and v7_position > current_position):
            losses += 1
        else:
            ties += 1
        harmful += int(labels["reviewed_v7"] in case["review"]["harmful"])
    passed = wins >= 7 and losses <= 1 and harmful == 0 and run["model"] == "gpt-5.6-sol"
    summary = {
        "reviewed_v7_wins": wins,
        "reviewed_v7_losses": losses,
        "ties": ties,
        "reviewed_v7_harmful": harmful,
        "model": run["model"],
        "human_review_only": True,
        "release_gate_passed": passed,
    }
    with transaction(conn):
        conn.execute(
            """UPDATE evaluation_runs SET status='complete',summary_json=?,updated_at=?
                 WHERE id=?""",
            (_json(summary), utcnow(), evaluation_id),
        )
    return {"id": evaluation_id, **summary}


def latest_release_gate(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT * FROM evaluation_runs WHERE status='complete'
            ORDER BY updated_at DESC,id DESC LIMIT 1"""
    ).fetchone()
    return _run(row) if row is not None else None
