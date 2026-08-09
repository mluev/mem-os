# Hermes adapter

The wheel contains the Hermes provider; `memkit install-hermes` copies it to `$HERMES_HOME/plugins/memkit`. It speaks the strict single-owner HTTP API and never sends an owner field.

User/assistant turns are uploaded as one idempotent evidence batch. Tool results are excluded by default; if explicitly enabled, they remain role=`tool` and are scrubbed both in the adapter and service. Non-primary agent contexts are read-only.

Prefetch uses normal trust-aware memory search with a short timeout, circuit breaker, and last-good cache. Tools expose neutral query context and free-form memory kind, not product workflow fields. Direct model-authored memories are labelled `assistant` and therefore excluded from normal retrieval.

The provider exposes Hermes lifecycle/config/tool methods and backup paths. Configuration needs `base_url`, `MEMKIT_API_KEY`, budgets/timeouts, and optional SQLite/Qdrant paths for Hermes backup discovery.
