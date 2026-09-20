# 0072 — Independent semantic blocks and durable experiment archives

    Status:        accepted
    Date:          2026-09-20
    Supersedes:    dedup target eligibility and revalidation in 0055
    Evidence:      ../measurements.md (modular semantic blocks)
    Code:          semantic.py, semantic_runtime.py, extract.py, eval/reports.py

## Decision

Treat semantic understanding as a replaceable provider protocol. Independently
configure duplicate verification, retrieval relevance, and advisory source support.
All distributed defaults are off; a key by itself enables no provider calls.

`semantic_dedup=verify` can veto a cosine proposal but cannot create a new proposal,
correct a fact, or delete one. It requires the same resolved scope, subject,
context, kind and validity, with a trusted live target. The write transaction
rechecks the target revision and constraints under a row lock. Unconfirmed or
failed checks preserve the incoming fact as a separate row. `shadow` observes
the proposal without changing this decision.

`semantic_retrieval` supports shadow, rerank and filter. Scope/trust/expiry/request
filters run before provider egress. A service error restores baseline ordering
and scores. Unchecked tail candidates cannot bypass the semantic floor in filter
mode. These judgments do not grant access or resolve conflicting evidence.

`semantic_support=shadow` checks exact cited user spans with conversation, known
entities and recording date as reference context. No support score gates a write.
Diagnostics enter the scoped job result as counts. Operational logs contain only
counts, model/version, usage and timing; they do not contain source/query text or
request hashes. Jev usage is observed separately from generative-provider budgets.

All live evaluation runners save an immutable common archive. Reports distinguish
execution provenance from later archival provenance, retain failed variants,
hash original results, and record labels, dataset/question versions, thresholds,
language/cohort slices, limitations and decisions. Public archives contain only
synthetic fixtures. Private user studies use private storage and their own labels.

## Evidence and limits

In 24 synthetic pair checks, cosine proposed two false duplicates; the real batched
verification block vetoed both, while retaining 9 of 12 true duplicates versus
11 for cosine alone. The lost merge opportunities produce extra rows, not lost
incoming facts. This is a precision/recall tradeoff, not an accuracy gain.

Across 24 synthetic queries through real PostgreSQL, BGE and local exact Qdrant,
filtering preserved all 21 relevant returned facts and removed 334 irrelevant
returns. Top-1 stayed 12/12; no ranking gain was established. Server ANN and real
user traffic remain unmeasured. Expanded evidence state still reduced golden
retention from 27 to 14 of 31 expected facts if used as a gate; that gate is rejected.
