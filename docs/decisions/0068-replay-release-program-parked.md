# 0068 — The replay/release/evaluation program is parked, keeping the planner

    Status:        deferred
    Date:          2026-09-04
    Supersedes:    —
    Superseded by: —
    Evidence:      ../measurements.md#to-be-re-measured
    Code:          src/memkit/reextract.py; src/memkit/replay.py, release.py, evaluations.py, policy_sweep.py, benchmark.py (deleted)
    Contract:      ../06-roadmap.md

## Decision

Shadow replay, the promotion gates, the blinded four-arm evaluation, the offline policy sweep and the 100k benchmark are removed, along with `replay_batches`, `replay_items`, `evaluation_runs` and `evaluation_cases`.

`reextract.dry_run_report` survives as a planner, reachable as `memkit reextract-report` and `POST /v1/admin/reextract`. It answers the question the program was actually being asked: how many windows, over which scopes, at what model cost, at which prompt version, with what provenance and review distribution — and it writes nothing.

## Alternatives and why not

**Port it.** The replay design rested on a property SQLite gave for free: a consistent copy of the database is one file, so a replay ran against the copy, produced a reviewable diff, and promotion swapped the file back with a protected checkpoint for rollback. On Postgres a "copy" is a second database — provisioned, migrated, loaded from a dump, kept somewhere while a human reviews a batch, and then merged rather than swapped, because the live database has moved on. That is a different piece of work, not a port, and it would land in the same release as a database migration and a tenancy model.

**Port it later, keeping the tables.** Rejected because empty tables are a claim. Four tables, their endpoints, their scope predicates and their fitness-walk entries would be carried for a program with no rows, and the next person reading the schema would reasonably conclude the feature exists.

**Drop the report too.** It was the only part in regular use, it is eighty lines, it takes no lock and spends no money, and it is what turns "should we re-extract?" from a guess into a number.

## Revisit when

A prompt change needs to be **applied to history**, not merely measured on a golden set. Concretely: a measured v9-to-vNext improvement large enough that leaving existing facts at the old version is more expensive than rebuilding them — visible as a golden-set recall or false-positive gap that the planner then prices at more than a few dollars over the corpus. At that point the shape to build is a shadow database plus a reviewed net diff, and the promotion gates from the old program are the right specification for it.

The evaluation half has its own trigger and it is nearer: enabling confidence-based rank, or moving the abstention floor, still requires a blinded comparison, and that is currently a manual eval run rather than a stored program. If that happens twice, the harness is worth rebuilding — for the harness, not for the release machinery around it.
