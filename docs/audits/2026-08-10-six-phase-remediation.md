# Six-phase verification remediation

Date: 2026-08-10
Input: `mem-os-six-phase-verification.md`

## Repository verdict

Every actionable finding owned by this repository is repaired and covered by a deterministic gate.

- Owner-scoped delivery barriers and authoritative-row rechecks prevent erase/reindex resurrection.
- Outbox operations are immutable, sequenced, lease-claimed, and completed with claim-token CAS.
- Memory mutations use redaction, integer revision CAS, and immutable history; record deletion is revisioned.
- Extraction windows, background jobs, budget reservations, and stale recovery use durable claims/leases.
- Export is snapshot-consistent and includes judge runs plus memory/record revisions; erase purges managed exports and migration backups.
- Generic record filters execute in SQLite; inert indexing/embedding settings are no longer public API fields.
- Hermes explicit remember uses `manual` trust and default backup includes SQLite.
- V7 eval tools and corpora use neutral context/kind/evidence; replay has a restart-safe apply path.
- OpenAPI responses have named schemas. Python uses `X-API-Key`; TypeScript packages `schema.d.ts`; CI regenerates and clean-consumer tests both SDKs.
- CI targets `master`, audits exported locked runtime requirements, enforces 65% coverage, and checks v7 schema cases.
- Vulnerable `cryptography` and `h2` locks were upgraded to fixed versions.

## Verification

- Backend: 118 passed, 1 skipped; 65.78% production-module coverage (65% gate).
- Qdrant integration: 1 passed against the running local service; CI uses the pinned server image.
- Frontend: 7 passed; lint, typecheck, and production build passed.
- V7 golden corpus: 21 schema/contract cases validated without a paid provider call.
- Python locked dependency audit: no known vulnerabilities.
- Frontend dependency audit: no known high-severity vulnerabilities.
- OpenAPI parity, documentation contract, Ruff, package builds, TypeScript packed-consumer compile, and clean Python SDK/core-wheel imports passed.

## External completion required

These are not changes that can be truthfully completed inside this repository:

1. Import the source-identified v3 task handoff into Life OS and validate its temporary compatibility adapter. No Life OS workspace or import contract is available here.
2. Enable required checks/branch protection for `master`, deploy the built release with a copied-database rollback drill, and replace the running `qdrant/qdrant:latest` container with the pinned image. These mutate live GitHub/service state.
3. Run the v7 golden corpus against the configured paid provider and approve the measured quality baseline. Deterministic CI intentionally performs schema validation only.
