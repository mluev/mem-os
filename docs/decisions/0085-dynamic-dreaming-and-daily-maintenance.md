# 0085 — Dream when a scope goes quiet; maintain once a day; list dream supersessions

    Status:        accepted
    Date:          2026-10-19
    Supersedes:    —
    Evidence:      to be measured; see ../measurements.md#to-be-re-measured
    Code:          dream.py (due_scopes, caught_up, _apply), job_runner.py (tick, schedule_maintenance, _queue_session_dreams), worker.py, config.py
    Contract:      ../04-judge.md, ../09-operations.md

## Decision

`MEMKIT_DREAMING=dynamic` dreams a scope when nothing new has arrived for
`dream_idle_minutes` (15), when `dream_batch` (20) stated memories past the
watermark have piled up, or when a session closes with its last window
extracted; not again within `dream_min_interval_minutes` (30) unless a full
batch waits. A tick in the worker, about once a minute, decides; the actor is
the author of the newest fresh memory. A dream's result reports `caught_up`.

A dream that decides one stated memory replaced another still supersedes it at
once, and now writes a `conflict` item to the actor's review queue; the existing
restore brings the old memory back.

`MEMKIT_MAINTENANCE=daily` queues one consolidation pass per 24 hours under an
advisory lock, with no actor: it expires lapsed memories, demotes stale ones and
folds exact duplicates, never groups semantically or merges, spends nothing, and
prunes retrieval telemetry.

## Why

Dreaming after every extraction showed each dream one window's fragment.
Supermemory moved to the same trigger for the same reason: memories form from
coherent units. The ADRs already called consolidation "nightly", but nothing
scheduled it, so expiry and demotion happened only when someone ran it.

## Alternatives and why not

**Review before a dream supersedes.** It would make knowledge updates wait for a
person, which is the category dreaming exists to improve; a reversible change
with a visible item is the trade.

**A cron container.** One more service to deploy and keep in step; the durable
worker already runs on every instance and the advisory lock makes it safe on
several.
