# 0052 — Durable jobs and transactional outbox

    Status:        accepted
    Date:          2026-08-09
    Supersedes:    0012, 0018
    Superseded by: —
    Evidence:      ../audits/2026-08-09-engineering-audit.md
    Code:          src/memkit/jobs.py, src/memkit/outbox.py, src/memkit/reindex.py
    Contract:      ../01-architecture.md

## Decision

Every authoritative change commits to SQLite before derived indexing. An idempotent outbox repairs post-commit failure. Long operations are durable jobs with event history, leases, call limits, cooperative cancellation, and atomic budget reservation. Reindex activates a validated generation by alias instead of destroying the live index.
