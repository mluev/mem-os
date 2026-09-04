# 0062 — Scope predicates in the application, guarded by a fitness test, not row-level security

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_architecture_fitness.py (scope safety)
    Code:          src/memkit/api.py, src/memkit/principal.py, src/memkit/store.py
    Contract:      ../01-architecture.md#ownership-and-trust, ../08-testing.md

## Decision

The scope predicate is written in the application: `scope_id = ANY(%(scopes)s)` in SQL, a keyword filter in Qdrant, taken in both cases from the request's `Principal`. Postgres row-level security is not enabled.

What keeps that honest is a fitness test rather than discipline. `test_every_handler_touching_a_scoped_table_names_the_principal` parses `api.py`, finds every function whose SQL literals mention a scoped table, and fails unless that function also names `principal`. Its allowance list for helpers that receive an already-authorised scope list is currently empty, and a companion test fails if an entry in it goes stale. Two further walks fail if an operation declares no security, if an `/v1/admin` route is neither admin-guarded nor on an explicit principal-narrowed list, or if the string `owner_id` reappears anywhere in the package outside prose.

## Alternatives and why not

**Postgres RLS.** The database enforcing the boundary is genuinely stronger than every developer remembering to: a policy applies to a query nobody reviewed, including one written in psql at three in the morning. Two things make it the wrong fit here.

RLS *filters*. That is its entire semantics — a row that fails the policy is not there. This product's rule is the opposite: a scope the caller names and does not hold must be refused, `403`, and refusing is not something a policy can express. Under RLS the application would still have to check membership before the query in order to produce that refusal, at which point the policy is a second implementation of a check that already ran, and the two can disagree — which is worse than one check, because the disagreement is silent.

The worker runs without a principal. Index delivery, generation reindex, consolidation, export and erasure operate across every scope by design, and reindex in particular must read the entire store to rebuild it. Under RLS each of those needs `SET LOCAL ROLE`, a bypass role, or a `SECURITY DEFINER` wrapper, and every one of those is a hole in the policy with a name. A boundary whose enforcement is disabled for the processes that touch the most rows is documentation with a `pg_policy` row behind it.

Two smaller costs, recorded because they would surface immediately: the pool hands connections to whoever asks next, so `SET LOCAL app.user_id` has to be re-established per transaction rather than per connection, and forgetting it fails open on a pooled connection that still carries the previous caller's setting. And the planner sees policy predicates it cannot always push into the index the way an explicit `= ANY` is pushed.

**Trust code review.** This is what the single-owner build did, because there was nothing to get wrong: one owner, read from settings, in forty handlers. In a team instance one forgotten predicate is one person's memory reaching another, and that is the single bug class the system cannot survive. Review does not catch a missing `WHERE` clause reliably; an AST walk does, every run, including on the handler somebody adds next month.

## Consequences

The fitness test is a static approximation and says so: it proves a handler *mentions* the principal, not that it used it correctly. It is paired with behavioural tests — a teammate's private fact unreachable, a revoked membership taking effect before the index catches up, a Qdrant point whose payload lies about its scope still refused by the Postgres re-read. If RLS is ever adopted it should be added *underneath* these predicates as defence in depth, not in place of them.
