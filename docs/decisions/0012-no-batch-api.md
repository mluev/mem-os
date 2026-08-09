# 0012 — Batch API is used nowhere

    Status:        superseded
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/03-api.md, `use_batch`
    Superseded by: 0052
    Evidence:      ../measurements.md#cost
    Code:          src/memkit/admin.py (`reextract`)
    Contract:      ../03-api.md#post-v1adminreextract

## Decision

Neither extraction nor consolidation uses a provider Batch API.
`POST /v1/admin/reextract` accepts `use_batch` in the request body and answers
**422** — it is refused explicitly, not ignored.

## Alternatives and why not

The archived spec recommended Batch as the main cost lever, at roughly half
price. The arithmetic no longer favours it: a full replay of the entire corpus
costs about **$0.29** on the default model, and total spend since the project
began is $0.51. Halving $0.29 saves fifteen cents and buys asynchronous
submission, polling, partial-failure handling and a code path that is exercised
once a month.

Consolidation is worse suited still — the whole nightly run is a handful of calls
on fewer than a hundred facts, measured at $0.00025 per merge.

## Why 422 rather than ignoring the flag

Accepting a documented parameter and silently doing something else is the
failure mode this whole reconciliation is about. A caller who passes
`use_batch: true` believes they are getting half price; if the service quietly
declines, the discount appears in their reasoning and not in the bill. Refusing
loudly costs one error response and keeps the request body honest.
