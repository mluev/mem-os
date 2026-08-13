# API

`openapi.json` is canonical and generates both SDKs. Requests and responses have named schemas; request models forbid extra fields, and strings, bounds, numbers, and enumerations are validated. The API key is compared in constant time and determines the owner.

Core groups:

- evidence: `POST /v1/evidence/events`, `POST /v1/evidence/events:batch`, session close;
- memory: create/update/archive, `/v1/memories/search`, sources, history, retrieval runs, and scoped feedback;
- platform: namespaces, collections, records, record history/search, links, policies;
- profiles: `POST /v1/profiles/render`;
- privacy: `POST /v1/export`, confirmed `POST /v1/erase`;
- replay: batch list/detail/items, review, validation, approval, export, promotion gates, and confirmed promotion;
- evaluations: blinded case creation/list/review/finalization;
- jobs: list/get/cancel plus reindex, consolidation preview/apply, and legacy replay reporting;
- operations: protected health, metrics, backup status, sessions, messages, model runs, and offline policy sweeps.

Evidence and memory writes report authoritative storage separately from indexing. Search responses add optional `retrieval_id` and component timings. `POST /v1/retrieval-runs/{id}/feedback` accepts only labels for a result actually returned by that run. The legacy feedback path HMACs and immediately discards its raw query. Cursor pagination is used for large memory, record, and job lists; operations logs use bounded offset pagination.

Memory patches require `expected_revision`; record deletion requires the same integer-revision precondition. Stale mutations return 409. Replay is non-mutating by default; `POST /v1/admin/reextract` with `{"apply": true}` queues a v7 shadow batch. Promotion requires the approved immutable checksum and `confirm="PROMOTE"`.

`GET /healthz` reveals only `{"ok": true}`. `/readyz` is public for orchestration. Detailed paths require `X-API-Key`.
