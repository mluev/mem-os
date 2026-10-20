# 0084 — The server chooses the default retrieval policy; v3 trusts assistant info

    Status:        accepted
    Date:          2026-10-19
    Supersedes:    —
    Evidence:      to be measured; see ../measurements.md#to-be-re-measured
    Code:          config.py (default_policy), schemas.py (SearchIn.policy_id), routers/memory.py, api.py (check_default_policy), db.py (_seed_core_policies), retrieval.py (assistant_penalty)
    Contract:      ../05-retrieval.md

## Decision

A search that names no policy uses `MEMKIT_DEFAULT_POLICY` (default
`neutral-v1`); an unknown name refuses to start. `core-retrieval-v3` (alias
`assistant-v3`) is v2 with `assistant` added to the trusted roles and an
`assistant_penalty` of 0.05 for unconfirmed assistant memories; raw assistant
passages are returned to a policy that trusts the role. `/v1/admin/health`
reports the prompt version, judge model, default policy, dreaming mode,
reranker and index settings, so a measurement can name what it measured.

## Why

No client sends `policy_id`, so v2 could only ever be the default by editing
every client or the schema. A setting lets a deployment switch the policy the
benchmark chose without a release, and roll it back the same way. v3 keeps v2's
weights so the trust change is measurable on its own.

## Alternatives and why not

**Retune v2 to admit assistant memories.** Policies are immutable rows so a
ranking change can be rolled back by name.
