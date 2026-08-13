"""Resumable shadow replay, immutable review manifests, and guarded promotion."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from . import jobs, judge, reextract
from .config import Settings
from .db import connect, transaction, utcnow
from .limits import MAX_MEMORY_CHARS


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _source_checksum(conn: sqlite3.Connection, *, owner_id: str) -> str:
    digest = hashlib.sha256()
    memories = conn.execute(
        "SELECT id,revision,status FROM memories WHERE owner_id=? ORDER BY id", (owner_id,)
    ).fetchall()
    messages = conn.execute(
        """SELECT m.id,m.content FROM messages m JOIN sessions s ON s.id=m.session_id
            WHERE s.owner_id=? ORDER BY m.id""",
        (owner_id,),
    ).fetchall()
    for row in memories:
        digest.update(_canonical(dict(row)).encode())
    for row in messages:
        digest.update(str(row["id"]).encode())
        digest.update(hashlib.sha256(str(row["content"]).encode()).digest())
    return digest.hexdigest()


def _copy_database(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(".db.tmp")
    source_conn = connect(source)
    target_conn = sqlite3.connect(temporary)
    try:
        source_conn.backup(target_conn)
    finally:
        target_conn.close()
        source_conn.close()
    os.chmod(temporary, 0o600)
    temporary.replace(target)


def copy_database(source: Path, target: Path) -> None:
    """Create a consistent, permission-restricted SQLite copy."""
    _copy_database(source, target)


def create_batch(conn: sqlite3.Connection, *, settings: Settings) -> dict[str, str]:
    active = conn.execute(
        """SELECT id FROM replay_batches
            WHERE status IN ('queued','running','review','validated','approved','promoting')
            LIMIT 1"""
    ).fetchone()
    if active is not None:
        raise RuntimeError(f"replay batch {active['id']} is still active")
    batch_id = str(uuid.uuid4())
    path = settings.export_dir / "replays" / f"{batch_id}.db"
    _copy_database(settings.db_path, path)
    report = reextract.dry_run_report(
        conn,
        owner_id=settings.owner_id,
        model=settings.judge_model,
        output_dir=settings.export_dir / "replays" / batch_id,
    )
    job_id = jobs.create(
        conn,
        kind="shadow_replay",
        input_data={"batch_id": batch_id},
        call_limit=int(report["estimated_windows"]),
    )
    now = utcnow()
    with transaction(conn):
        conn.execute(
            """INSERT INTO replay_batches
               (id,owner_id,job_id,status,model,prompt_version,source_checksum,
                shadow_path,stats_json,created_at,updated_at)
               VALUES (?,?,?,'queued',?,?,?,?,?,?,?)""",
            (
                batch_id,
                settings.owner_id,
                job_id,
                settings.judge_model,
                judge.PROMPT_VERSION,
                _source_checksum(conn, owner_id=settings.owner_id),
                str(path),
                _canonical(
                    {
                        "estimated_windows": report["estimated_windows"],
                        "estimated_cost_usd": report["estimated_cost_usd"],
                    }
                ),
                now,
                now,
            ),
        )
    return {"batch_id": batch_id, "job_id": job_id}


def _memory(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "revision": int(row["revision"]),
        "agent_id": row["agent_id"],
        "text": str(row["text"]),
        "kind": str(row["kind"]),
        "context": json.loads(row["context_json"] or "{}"),
        "tags": json.loads(row["tags_json"] or "[]"),
        "importance": float(row["importance"]),
        "confidence": float(row["confidence"]),
        "valid_until": row["valid_until"],
        "status": str(row["status"]),
        "source_role": str(row["source_role"]),
        "extraction_version": str(row["extraction_version"]),
    }


def _evidence(conn: sqlite3.Connection, memory_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT e.message_id,e.start_char,e.end_char,e.excerpt_sha256,m.content
             FROM memory_evidence e JOIN messages m ON m.id=e.message_id
            WHERE e.memory_id=? ORDER BY e.message_id,e.start_char,e.end_char""",
        (memory_id,),
    ).fetchall()
    evidence = []
    for row in rows:
        excerpt = str(row["content"])[int(row["start_char"]) : int(row["end_char"])]
        if hashlib.sha256(excerpt.encode()).hexdigest() != row["excerpt_sha256"]:
            raise RuntimeError(f"evidence checksum mismatch for memory {memory_id}")
        evidence.append(
            {
                "message_id": int(row["message_id"]),
                "start_char": int(row["start_char"]),
                "end_char": int(row["end_char"]),
                "excerpt_sha256": str(row["excerpt_sha256"]),
                "excerpt": excerpt,
            }
        )
    return evidence


def _changed(before: dict[str, Any], proposed: dict[str, Any]) -> bool:
    fields = (
        "text",
        "kind",
        "context",
        "tags",
        "importance",
        "confidence",
        "valid_until",
        "status",
        "source_role",
        "extraction_version",
    )
    return any(before.get(field) != proposed.get(field) for field in fields)


def _write_diff(
    live: sqlite3.Connection,
    shadow: sqlite3.Connection,
    *,
    batch_id: str,
    owner_id: str,
) -> dict[str, int]:
    before = {
        str(row["id"]): _memory(row)
        for row in live.execute("SELECT * FROM memories WHERE owner_id=?", (owner_id,))
    }
    after = {
        str(row["id"]): _memory(row)
        for row in shadow.execute("SELECT * FROM memories WHERE owner_id=?", (owner_id,))
    }
    items: list[dict[str, Any]] = []
    for memory_id in sorted(set(before) | set(after)):
        old = before.get(memory_id)
        new = after.get(memory_id)
        action: str | None = None
        if old is None and new is not None and new["status"] == "active":
            action = "ADD"
        elif (
            old is not None
            and old["status"] == "active"
            and (new is None or new["status"] != "active")
        ):
            action = "DELETE"
        elif old is not None and new is not None and _changed(old, new):
            action = "UPDATE"
        if action is None:
            continue
        evidence_conn = shadow if action != "DELETE" else live
        evidence = _evidence(evidence_conn, memory_id)
        source_role = str((new or old or {})["source_role"])
        items.append(
            {
                "id": str(uuid.uuid4()),
                "action": action,
                "target": None if action == "ADD" else memory_id,
                "source_revision": old["revision"] if old is not None else None,
                "before": old,
                "proposed": new if action != "DELETE" else None,
                "evidence": evidence,
                "source_role": source_role,
            }
        )
    with transaction(live):
        live.execute("DELETE FROM replay_items WHERE batch_id=?", (batch_id,))
        for sequence, item in enumerate(items):
            live.execute(
                """INSERT INTO replay_items
                   (id,batch_id,sequence,action,target_memory_id,source_revision,
                    before_json,proposed_json,evidence_json,source_role,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item["id"],
                    batch_id,
                    sequence,
                    item["action"],
                    item["target"],
                    item["source_revision"],
                    _canonical(item["before"]) if item["before"] is not None else None,
                    _canonical(item["proposed"]) if item["proposed"] is not None else None,
                    _canonical(item["evidence"]),
                    item["source_role"],
                    utcnow(),
                ),
            )
    return {
        "items": len(items),
        "adds": sum(item["action"] == "ADD" for item in items),
        "updates": sum(item["action"] == "UPDATE" for item in items),
        "deletes": sum(item["action"] == "DELETE" for item in items),
    }


def run_shadow_replay(
    live: sqlite3.Connection,
    *,
    settings: Settings,
    batch_id: str,
    job_id: str,
    cancelled: Any,
) -> dict[str, Any]:
    batch = live.execute("SELECT * FROM replay_batches WHERE id=?", (batch_id,)).fetchone()
    if batch is None:
        raise LookupError(batch_id)
    if batch["status"] in {"review", "validated", "approved", "promoted", "cancelled"}:
        # The live diff and cost ledger are committed together before the worker job is
        # completed. If the process dies between those commits, retrying must not rerun
        # the model or replace decisions already made by a reviewer.
        stats = json.loads(batch["stats_json"] or "{}")
        return {"batch_id": batch_id, **stats}
    with transaction(live):
        live.execute(
            "UPDATE replay_batches SET status='running',updated_at=? WHERE id=?",
            (utcnow(), batch_id),
        )
    program_spend = float(
        live.execute(
            """SELECT COALESCE(SUM(cost_usd),0) FROM judge_runs
                WHERE kind LIKE 'improvement-%'"""
        ).fetchone()[0]
    )
    allowance = settings.improvement_budget_usd - program_spend
    if allowance <= 0:
        raise jobs.BudgetExceeded("the $10 improvement-program budget is exhausted")
    reservation = jobs.reserve_budget(
        live,
        period=utcnow()[:7],
        amount_usd=allowance,
        limit_usd=settings.monthly_cost_limit_usd,
        job_id=job_id,
    )
    shadow = connect(Path(batch["shadow_path"]))
    try:
        live_job = jobs.get(live, job_id)
        with transaction(shadow):
            shadow.execute(
                """INSERT OR IGNORE INTO jobs
                   (id,kind,status,input_json,call_limit,calls_completed,cancel_requested,
                    attempts,created_at,started_at,updated_at)
                   VALUES (?,?,'running',?,?,0,0,1,?,?,?)""",
                (
                    job_id,
                    "shadow_replay",
                    live_job["input_json"],
                    live_job["call_limit"],
                    live_job["created_at"],
                    utcnow(),
                    utcnow(),
                ),
            )
            shadow.execute(
                """UPDATE jobs SET status='running',input_json=?,call_limit=?,
                                      cancel_requested=0,updated_at=?
                     WHERE id=?""",
                (live_job["input_json"], live_job["call_limit"], utcnow(), job_id),
            )
        baseline_spend = judge.month_spend_usd(shadow)
        replay_result = reextract.apply_replay(
            shadow,
            owner_id=settings.owner_id,
            api_key=settings.anthropic_api_key,
            gemini_api_key=settings.gemini_api_key,
            project=settings.vertex_project,
            location=settings.vertex_location,
            monthly_limit_usd=baseline_spend + allowance,
            model=str(batch["model"]),
            job_id=job_id,
            cancelled=cancelled,
        )
        # The replay job id is unique and survives in the database copy. Selecting by
        # it accounts for calls completed before a crash as well as calls after resume.
        paid_rows = shadow.execute(
            "SELECT * FROM judge_runs WHERE job_id=? ORDER BY id", (job_id,)
        ).fetchall()
        actual = sum(float(row["cost_usd"] or 0.0) for row in paid_rows)
        if actual > allowance + 1e-9:
            raise jobs.BudgetExceeded("shadow replay exceeded its reserved program budget")
        diff = _write_diff(live, shadow, batch_id=batch_id, owner_id=settings.owner_id)
        with transaction(live):
            # Idempotent if the worker completed the batch commit but died before it
            # could mark the outer job complete.
            live.execute(
                "DELETE FROM judge_runs WHERE job_id=? AND kind='improvement-shadow-replay'",
                (job_id,),
            )
            for row in paid_rows:
                live.execute(
                    """INSERT INTO judge_runs
                       (owner_id,job_id,kind,model,prompt_version,input_json,error,
                        input_tokens,output_tokens,cost_usd,latency_ms,created_at)
                       VALUES (?,?,'improvement-shadow-replay',?,?,?,?,?,?,?,?,?)""",
                    (
                        settings.owner_id,
                        job_id,
                        row["model"],
                        row["prompt_version"],
                        _canonical({"batch_id": batch_id}),
                        "provider_call_failed" if row["error"] else None,
                        row["input_tokens"],
                        row["output_tokens"],
                        row["cost_usd"],
                        row["latency_ms"],
                        row["created_at"],
                    ),
                )
            calls = int(
                shadow.execute("SELECT calls_completed FROM jobs WHERE id=?", (job_id,)).fetchone()[
                    0
                ]
            )
            stats = {**json.loads(batch["stats_json"]), **replay_result, **diff, "cost_usd": actual}
            live.execute(
                """UPDATE replay_batches SET status=?,stats_json=?,updated_at=? WHERE id=?""",
                (
                    "cancelled" if replay_result["cancelled"] else "review",
                    _canonical(stats),
                    utcnow(),
                    batch_id,
                ),
            )
            live.execute(
                "UPDATE jobs SET calls_completed=?,updated_at=? WHERE id=?",
                (calls, utcnow(), job_id),
            )
        jobs.reconcile_budget(live, reservation, actual_usd=actual)
        return {"batch_id": batch_id, **replay_result, **diff, "cost_usd": actual}
    except Exception:
        jobs.release_budget(live, reservation)
        with transaction(live):
            live.execute(
                "UPDATE replay_batches SET status='failed',error=?,updated_at=? WHERE id=?",
                ("shadow replay failed; inspect the job error", utcnow(), batch_id),
            )
        raise
    finally:
        shadow.close()


def list_batches(conn: sqlite3.Connection, *, owner_id: str) -> list[dict[str, Any]]:
    return [
        _batch_dict(row)
        for row in conn.execute(
            "SELECT * FROM replay_batches WHERE owner_id=? ORDER BY created_at DESC,id DESC",
            (owner_id,),
        )
    ]


def _batch_dict(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["stats"] = json.loads(value.pop("stats_json") or "{}")
    return value


def get_batch(conn: sqlite3.Connection, *, batch_id: str, owner_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM replay_batches WHERE id=? AND owner_id=?", (batch_id, owner_id)
    ).fetchone()
    if row is None:
        raise LookupError(batch_id)
    result = _batch_dict(row)
    result["decisions"] = {
        decision: count
        for decision, count in conn.execute(
            "SELECT decision,COUNT(*) FROM replay_items WHERE batch_id=? GROUP BY decision",
            (batch_id,),
        )
    }
    return result


def list_items(conn: sqlite3.Connection, *, batch_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM replay_items WHERE batch_id=? ORDER BY sequence", (batch_id,)
    ).fetchall()
    items = []
    for row in rows:
        value = dict(row)
        for source, target in (
            ("before_json", "before"),
            ("proposed_json", "proposed"),
            ("evidence_json", "evidence"),
            ("reviewed_json", "reviewed"),
        ):
            raw = value.pop(source)
            value[target] = json.loads(raw) if raw is not None else None
        items.append(value)
    return items


def review_item(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    item_id: str,
    decision: str,
    edits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if decision not in {"accepted", "rejected", "edited"}:
        raise ValueError("decision must be accepted, rejected, or edited")
    row = conn.execute(
        """SELECT i.*,b.status batch_status FROM replay_items i
             JOIN replay_batches b ON b.id=i.batch_id
            WHERE i.id=? AND i.batch_id=?""",
        (item_id, batch_id),
    ).fetchone()
    if row is None:
        raise LookupError(item_id)
    if row["batch_status"] not in {"review", "validated"}:
        raise RuntimeError("batch is not open for review")
    proposed = json.loads(row["proposed_json"]) if row["proposed_json"] else None
    reviewed = proposed
    if decision == "edited":
        if row["action"] == "DELETE":
            raise ValueError("delete items cannot be edited")
        edits = edits or {}
        forbidden = set(edits) - {"text", "kind", "context", "tags"}
        if forbidden:
            raise ValueError(f"immutable replay fields cannot be edited: {sorted(forbidden)}")
        reviewed = {**(proposed or {}), **edits}
        text = str(reviewed.get("text") or "").strip()
        kind = str(reviewed.get("kind") or "").strip()
        tags = reviewed.get("tags")
        context = reviewed.get("context")
        if not text or len(text) > min(200, MAX_MEMORY_CHARS):
            raise ValueError("reviewed text must contain 1–200 characters")
        if not kind or len(kind) > 64:
            raise ValueError("reviewed kind must contain 1–64 characters")
        if not isinstance(context, dict) or not isinstance(tags, list) or len(tags) > 20:
            raise ValueError("reviewed context or tags are invalid")
    if decision == "rejected":
        reviewed = None
    with transaction(conn):
        conn.execute(
            """UPDATE replay_items SET decision=?,reviewed_json=?,reviewed_at=?
                 WHERE id=? AND batch_id=?""",
            (
                decision,
                _canonical(reviewed) if reviewed is not None else None,
                utcnow(),
                item_id,
                batch_id,
            ),
        )
        conn.execute(
            "UPDATE replay_batches SET status='review',approval_checksum=NULL,updated_at=? WHERE id=?",
            (utcnow(), batch_id),
        )
    return next(item for item in list_items(conn, batch_id=batch_id) if item["id"] == item_id)


def _approved_manifest(conn: sqlite3.Connection, batch_id: str) -> list[dict[str, Any]]:
    return [
        {
            "sequence": item["sequence"],
            "action": item["action"],
            "target_memory_id": item["target_memory_id"],
            "source_revision": item["source_revision"],
            "source_role": item["source_role"],
            "decision": item["decision"],
            "reviewed": item["reviewed"],
            "evidence": item["evidence"],
        }
        for item in list_items(conn, batch_id=batch_id)
    ]


def approved_manifest(conn: sqlite3.Connection, batch_id: str) -> list[dict[str, Any]]:
    return _approved_manifest(conn, batch_id)


def validate_batch(
    conn: sqlite3.Connection,
    *,
    batch_id: str,
    owner_id: str,
    update_status: bool = True,
) -> dict[str, Any]:
    get_batch(conn, batch_id=batch_id, owner_id=owner_id)
    manifest = _approved_manifest(conn, batch_id)
    pending = [item for item in manifest if item["decision"] == "pending"]
    if pending:
        raise RuntimeError(f"{len(pending)} replay decisions remain pending")
    for item in manifest:
        target = item["target_memory_id"]
        if target is not None:
            current = conn.execute(
                "SELECT revision FROM memories WHERE id=? AND owner_id=?", (target, owner_id)
            ).fetchone()
            if current is None or int(current["revision"]) != int(item["source_revision"]):
                raise RuntimeError(f"source revision changed for {target}")
        if item["decision"] != "rejected" and item["action"] in {"ADD", "UPDATE"}:
            if not item["evidence"]:
                raise RuntimeError("accepted add/update has no exact evidence")
            for evidence in item["evidence"]:
                row = conn.execute(
                    "SELECT content FROM messages WHERE id=?", (evidence["message_id"],)
                ).fetchone()
                if row is None:
                    raise RuntimeError("source evidence was removed")
                excerpt = str(row["content"])[evidence["start_char"] : evidence["end_char"]]
                if hashlib.sha256(excerpt.encode()).hexdigest() != evidence["excerpt_sha256"]:
                    raise RuntimeError("source evidence changed")
    checksum = hashlib.sha256(_canonical(manifest).encode()).hexdigest()
    if update_status:
        with transaction(conn):
            conn.execute(
                """UPDATE replay_batches SET status='validated',approval_checksum=?,updated_at=?
                     WHERE id=?""",
                (checksum, utcnow(), batch_id),
            )
    return {"batch_id": batch_id, "items": len(manifest), "checksum": checksum}


def approve_batch(
    conn: sqlite3.Connection, *, batch_id: str, owner_id: str, checksum: str
) -> dict[str, Any]:
    batch = get_batch(conn, batch_id=batch_id, owner_id=owner_id)
    if batch["status"] != "validated" or batch["approval_checksum"] != checksum:
        raise RuntimeError("batch must be validated with the same immutable checksum")
    gates = batch["stats"].get("deterministic_gates") or {}
    if not gates.get("passed"):
        raise RuntimeError("deterministic candidate gates have not passed")
    with transaction(conn):
        conn.execute(
            "UPDATE replay_batches SET status='approved',updated_at=? WHERE id=?",
            (utcnow(), batch_id),
        )
    return {"batch_id": batch_id, "status": "approved", "checksum": checksum}


def export_batch(
    conn: sqlite3.Connection, *, batch_id: str, owner_id: str, output_dir: Path
) -> dict[str, Any]:
    batch = get_batch(conn, batch_id=batch_id, owner_id=owner_id)
    manifest = _approved_manifest(conn, batch_id)
    body = {"batch": batch, "manifest": manifest}
    checksum = hashlib.sha256(_canonical(body).encode()).hexdigest()
    artifact = {"sha256": checksum, **body}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"replay-review-{batch_id}.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return {"path": str(path), "sha256": checksum, "items": len(manifest)}
