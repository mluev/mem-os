# 0020 — Reindex loads `status='active'` only

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    —
    Superseded by: —
    Evidence:      —
    Code:          src/memkit/store.py (`reindex`)
    Contract:      ../02-data-model.md#rebuilding-the-index

## Decision

`POST /v1/admin/reindex` drops both collections and reloads only facts with
`status='active'`.

## Why this is a decision

The obvious reading of "Qdrant rebuilds from SQLite" is "reload everything", and
that would resurrect every soft-deleted and superseded fact — turning the one
operation the design promises is always safe into the one that silently undoes
every correction ever made. Deletion is soft precisely so the row survives for
re-extraction; the index is where the fact stops being visible.

`tests/test_invariants.py` asserts it: delete a fact, rebuild, and the point must
not come back while the row must still be there.
