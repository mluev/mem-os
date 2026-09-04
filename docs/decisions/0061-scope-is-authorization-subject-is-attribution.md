# 0061 — Scope is the authorization boundary; subject is attribution

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_entities.py, tests/test_api_v4.py
    Code:          src/memkit/principal.py, src/memkit/store.py, src/memkit/db.py
    Contract:      ../01-architecture.md#ownership-and-trust

## Decision

Two columns, and the distinction between them is the whole tenancy model.

`scope_id` is the entity whose space holds a row. It is the only thing authorization consults: a principal may read the scopes it belongs to and write the ones where its membership is above viewer. `subject_id` is the entity a fact is *about*. It carries no permission at all — any entity the caller can see may be named as a subject, including a teammate whose private scope stays closed — and `NULL` means the fact is about the scope itself.

**A scope named in a request that the caller does not hold is refused: `403`. A scope that does not exist is `404`.** Not an empty result. The one place the rule inverts is a lookup *by id*: a memory in an unreachable scope is `404`, never `403`, because the caller did not name a scope and telling them "forbidden" would confirm the row exists.

## Alternatives and why not

**One `owner_id` and a visibility flag.** The obvious minimal step from the single-owner schema, and it cannot express the case the product is for: a fact about Alice, written by Bob, visible to the team, deletable by Alice. With one owner column that fact has to pick — Bob's, so Alice cannot manage it, or Alice's, so it is not the team's record. Splitting the column into two is what makes the case representable at all.

**Make the subject an authorization input too.** Tempting because "facts about me" sounds like a permission. It is not: a fact about a person can live in the team scope, in a project scope, or in someone's private notes, and the reader's right to see it comes from where it lives, not who it mentions. Conflating them would either leak (any mention of you grants you the containing scope) or lose (only you can see facts about you, so the team's picture of the team vanishes).

**Filter forbidden scopes away instead of refusing.** This is the alternative that looks safer and is worse. An empty result and a forbidden result are different answers to different questions, and a caller that cannot tell them apart will retry, cache the emptiness, or report "no memory" for a permissions bug. Neither can a test: an assertion that a filtered query returns nothing passes identically when the predicate is right and when the row simply is not there. The refusal is what makes both observable.

**Filter on a lookup by id, too.** Rejected in the other direction, for the reason above: a 403 on `GET /v1/memories/{id}` is an existence oracle. Whoever holds a key could enumerate ids and learn which of them are real facts in scopes they cannot read. A named scope is information the caller already had; a row id is not.

## Consequences

Every query that touches memory takes its scope set from the principal, and the mutating store functions take the writable set as an argument rather than an owner — with no scopes, nothing is writable, so a handler cannot lose the check by forgetting to pass one. A missing scope on a write means the caller's own private space: a fact that should have been shared can be moved, while one that should not have been cannot be unshared.
