# API

`openapi.json` is canonical and generates both SDKs. Request models forbid extra fields; strings, bounds, numbers, and enumerations are validated. The API key is compared in constant time and determines the owner.

Core groups:

- evidence: `POST /v1/evidence/events`, `POST /v1/evidence/events:batch`, session close;
- memory: create/update/archive, `/v1/memories/search`, sources, history, retrieval feedback;
- platform: namespaces, collections, records, record history/search, links, policies;
- profiles: `POST /v1/profiles/render`;
- privacy: `POST /v1/export`, confirmed `POST /v1/erase`;
- jobs: list/get/cancel plus reindex, consolidation preview/apply, and legacy replay report;
- operations: protected health, metrics, sessions, messages, and model runs.

Evidence and memory writes report authoritative storage separately from indexing. Cursor pagination is used for large memory, record, and job lists; operations logs use bounded offset pagination.

`GET /healthz` reveals only `{"ok": true}`. `/readyz` is public for orchestration. Detailed paths require `X-API-Key`.
