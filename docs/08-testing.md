# Testing

The deterministic suite covers:

- rollback versus post-commit index failure and retry;
- generation rebuild exact-ID validation and safe alias activation;
- concurrent budget reservation, durable job history, heartbeat/lease recovery, message-window claims, and cancellation;
- immutable outbox claim/version behavior, stale delivery recovery, and erase/delivery exclusion;
- model latency outside SQLite transactions;
- secret removal from messages, memory, generic records, stored model audit, and provider egress;
- owner/context correction isolation, assistant/agent poisoning, and expiry;
- correction, silence, exact-term, temporal cases, and 10,000 distractors;
- JSON Schema records, SQL-backed filters, idempotency, memory/record revisions, links, snapshot export, and artifact-complete erasure;
- strict API ownership and removal of workflow endpoints;
- wheel installation with bundled dashboard and Hermes adapter, generated SDK authentication, and TypeScript package declarations;
- frontend API-key lifecycle, request headers, unauthorized behavior, and query encoding.
- FTS5 equivalence and bounded candidate retrieval, privacy-safe telemetry, migration rollback, backup/restore rollback, replay review/promotion, worker dependency recovery, and generated service management;
- Playwright flows for feedback, replay edits/approval, blinded evaluation, backup status, and failed promotion rollback.

Run all local gates:

```bash
uv run pytest -q
uv run ruff check src tests tools integrations/hermes eval
uv run ruff format --check src tests tools integrations/hermes eval
uv run pytest -q --cov=memkit --cov-fail-under=75
uv run python -m eval.golden --schema-only
pnpm --dir web lint
pnpm --dir web typecheck
pnpm --dir web test
pnpm --dir web test:e2e
pnpm --dir web build
python -m tools.docblocks --check
```

CI adds dependency audits, migration tests, clean-wheel and clean-SDK consumer installation, browser workflows, and a real pinned-Qdrant integration. Model-quality experiments remain explicit and budgeted; deterministic CI never calls a paid provider. The protected 100k benchmark, paid golden comparison, replay audit, and human evaluation are release artifacts rather than ordinary CI fixtures.
