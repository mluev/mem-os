# 0080 — Forget by request, verified, dry-run first, bound to ids

    Status:        accepted
    Date:          2026-09-29
    Supersedes:    —
    Evidence:      —
    Code:          routers/memory.py (forget_memories), prompts.py (FORGET_V1), store.py
    Contract:      ../03-api.md

## Decision

`POST /v1/memories/forget` takes a request (`query`) or exact `ids`, touches
only scopes the caller may write, and is a dry run unless `dry_run=false`.
Query mode searches, keeps candidates above `threshold`, bounds them by
`max_forget`, and — with a judge configured — lets the judge keep only those
really about the request, choosing by number among the candidates it was
shown. Forgetting archives with a `forget_reason`; a reviewer can restore.
Applying with the ids a dry run returned forgets exactly the reviewed set.

## Alternatives and why not

**Apply by default.** The match is semantic; a broad request selects more than
intended, and the preview is the only point where a person can see that.

**Hard delete.** Erasure already exists for data that must go; forgetting is
about retrieval, and must be reversible.
