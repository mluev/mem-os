# 0018 — Extraction runs as a background task; there is no queue

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/01-architecture.md, `asyncio.Queue`
    Superseded by: —
    Evidence:      —
    Code:          src/memkit/api.py (`_extract_now`)
    Contract:      ../01-architecture.md#the-write-path

## Decision

Extraction runs through FastAPI's `BackgroundTasks`. There is no `asyncio.Queue`,
no worker pool and no `jobs` table. `queue_depth` in `GET /healthz` means "messages
with `processed = 0`" — the unprocessed backlog waiting for the judge.

## Alternatives and why not

The architecture document sketched an in-process `asyncio.Queue`. A background
task is what a queue of depth one would be, minus the machinery, and the property
that actually matters is already guaranteed by the database rather than by the
runtime: a message is marked `processed` only after its window has been applied,
so an interrupted extraction retries on the next message. A crash loses no work
because the work item lives in SQLite, not in memory. A queue would add a second,
weaker representation of the same state.

The naming is a compromise worth flagging. `queue_depth` is a promise the
architecture document made and callers may depend on, so the field kept its name
and changed its meaning to the honest equivalent. The backlog is the number worth
watching anyway — it is what tells you the judge has fallen behind.
