# 0052 — Durable jobs and transactional outbox

    Status:        accepted
    Date:          2026-08-09
    Supersedes:    0012, 0018
    Superseded by: 0059, in part — Postgres replaces SQLite and advisory locks replace the
                   owner barriers; the outbox, leases and generation reindex stand
    Evidence:      ../audits/2026-08-09-engineering-audit.md
    Code:          src/memkit/jobs.py, src/memkit/outbox.py, src/memkit/reindex.py
    Contract:      ../01-architecture.md

## Decision

Every authoritative change commits to SQLite before derived indexing. Immutable per-entity outbox operations use leased claims and claim-token completion; erasure, delivery, and reindex share owner-scoped barriers. Long operations are claimed by a polling worker with event history, renewable leases, startup recovery, call limits, cooperative cancellation, atomic message-window claims, and budget reservation. Reindex activates a validated generation by alias instead of destroying the live index.
