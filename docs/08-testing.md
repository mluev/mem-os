# Testing

The deterministic suite covers:

- rollback versus post-commit index failure and retry;
- generation rebuild exact-ID validation and safe alias activation;
- concurrent budget reservation, durable job history, leases, and cancellation;
- model latency outside SQLite transactions;
- secret removal from messages, memory, generic records, stored model audit, and provider egress;
- owner/context correction isolation, assistant/agent poisoning, and expiry;
- correction, silence, exact-term, temporal cases, and 10,000 distractors;
- JSON Schema records, idempotency, revisions, filters, policies, links, export, and complete erasure;
- strict API ownership and removal of workflow endpoints;
- wheel installation with bundled dashboard and Hermes adapter.

Run all local gates:

```bash
uv run pytest -q
uv run ruff check src tests tools integrations/hermes
uv run ruff format --check src tests tools integrations/hermes
pnpm --dir web lint
pnpm --dir web typecheck
pnpm --dir web test
pnpm --dir web build
python -m tools.docblocks --check
```

CI adds dependency audits, migration tests, clean-wheel installation, and a real Qdrant service integration. Model-quality experiments remain explicit and budgeted; deterministic CI never calls a paid provider.
