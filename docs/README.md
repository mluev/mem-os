# Mem OS documentation

Normative reading order:

1. [Architecture](01-architecture.md)
2. [Data model](02-data-model.md)
3. [API](03-api.md)
4. [Model extraction](04-judge.md)
5. [Retrieval](05-retrieval.md)
6. [Delivery status](06-roadmap.md)
7. [Hermes adapter](07-hermes-adapter.md)
8. [Testing](08-testing.md)
9. [Upgrade and recovery](09-operations.md)

Every measured number lives in [measurements.md](measurements.md), with its date and the command that produced it, and nowhere else; every "why not the alternative" lives in [decisions/](decisions/README.md).

The [consolidated handoff](releases/2026-09-20-handoff.md) gathers the current delivery and artifact bundle. The [September readiness review](reviews/2026-09-20-production-readiness.md) separates verified safety behavior, measured retrieval quality, and remaining release limitations.

The audit inputs remain under `audits/`; accepted design is in `plans/`. ADRs are append-only. Superseded ADRs retain their original reasoning and link to the replacement decision.
