# 0067 — The records platform is removed; policies stay

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      tests/test_api_v4.py (the records platform and the task board are gone)
    Code:          src/memkit/policies.py; src/memkit/platform.py (deleted)
    Contract:      ../01-architecture.md#extensibility, ../06-roadmap.md

## Decision

`namespaces`, `collections`, `records`, `record_revisions` and `links` are gone, with their endpoints, their JSON-Schema validation, their revision preconditions and their tests. `policies` survives, re-keyed from owner to scope: versioned, immutable, `(scope_id, kind, name, version)` unique, with a `NULL` scope meaning instance-wide.

## Alternatives and why not

**Keep it and add `scope_id`.** The port was mechanical and that is what made it worth questioning. In the whole life of the single-owner build, nothing wrote a record: no integration created a namespace, no client defined a collection schema, and the only rows the tables ever held were the ones its own tests inserted. Carrying a caller-defined structured store into the team model means giving every one of its tables, endpoints, filters and revision checks a scope predicate and a place in the fitness walk — the full authorization cost of the feature, paid for a feature with no users.

**Keep it dormant.** Unused code is not free when authorization is the property being defended. Every additional table that holds caller data is another surface where a missing predicate leaks, another set of routes in the security audit, and another reason for someone to reason about the system as "memory plus a document store" when it is a memory service.

**Delete policies as well.** They look like the same shape: a generic JSON blob with a version. They are not caller-defined data — they are how a measured ranking change is adopted and rolled back. `core-retrieval-neutral-v1` is read on every search, and pointing at an older version is the whole rollback plan for a retrieval change ([0051](0051-memory-boundary-and-hybrid-retrieval.md)). Removing them would leave the weights and the abstention floor as constants in code, which turns a rollback into a deploy.

**Replace records with something.** Nothing replaces them. Entities are the extension point now: a project, product, company or ad-hoc grouping is a row with a slug, aliases and members, and it needs no new table, no new endpoint and no migration. That covers what namespaces were reached for, without a second content model.

## Consequences

Fewer tables, and one fewer authorization surface. A caller that needs to store arbitrary structured data alongside memory now stores it in whatever system already owns it and puts the durable claim here — which was always the stated boundary ("memory, not workflow") and is now also the shape of the schema. The absence is asserted rather than assumed: the retired routes are tested for 404, because a stale mount would answer and nothing else in the suite would notice.
