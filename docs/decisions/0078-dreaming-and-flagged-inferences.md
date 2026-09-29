# 0078 — Dreaming links and infers; inferences are flagged and never premises

    Status:        accepted
    Date:          2026-09-29
    Supersedes:    —
    Evidence:      ../research/2026-09-29-supermemory.md
    Code:          dream.py, prompts.py (DREAM_V1), judge.py (structured_call), job_runner.py
    Contract:      ../04-judge.md, ../05-retrieval.md

## Decision

After an extraction writes into a scope — when a judge is configured and
`MEMKIT_DREAMING=after_extraction` (the default) — queue one dream for that
scope unless one is already waiting. A dream takes the scope's memories changed
since its last dream, gathers each one's nearest same-scope neighbours, and
asks the judge per cluster for `updates`/`extends` links and at most two
inferences, all by number among the memories shown.

Nothing is trusted as returned. A supersession must point forward in time
between stated claims with the same subject and context. An inference needs
two or more live stated premises, confidence of at least 0.7, fewer than 200
characters, and must not restate an existing memory; it is written with
`source_role='inference'`, `review_status='pending'` and a `derives` edge to
each premise, and it is never itself a premise. Profiles show an inference
only after confirmation. Calls reserve against the monthly ceiling and are
logged in `judge_runs` with ids, never text. `memkit dream` and `POST /v1/dream`
run it on demand; a dry run plans clusters without calling a model.

## Alternatives and why not

**No inference.** What several memories imply together is invisible to any
single window; it is also where the review queue earns its place.

**Trusted inferences.** A model's guess ranked like the user's words is the
closed loop decisions/0006 exists to prevent.

**Cross-scope clusters.** An inference in a shared scope drawn from a private
premise would publish the private fact in other words.
