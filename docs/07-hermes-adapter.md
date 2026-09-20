# Hermes adapter

The wheel contains the Hermes provider; `memkit install-hermes` copies it to `$HERMES_HOME/plugins/memkit`. It carries a **per-user API key** and never sends a user, owner, or scope field: the key names its user, and an unqualified write lands in that user's private scope. Sharing one key between two people is therefore sharing one memory, which is what `memkit api-keys create --user <handle>` exists to avoid.

The key is read from `api_key_file` — refused unless the file is `0600` and at least 32 characters — or from `MEMKIT_API_KEY`. Nothing in the adapter holds a session cookie, so the CSRF header does not apply to it.

User/assistant turns are uploaded as one idempotent evidence batch. Tool results are excluded by default; if explicitly enabled, they remain role=`tool` and are scrubbed both in the adapter and the service. Non-primary agent contexts are read-only, because a cron system prompt or a subagent's scratch reasoning is not the user talking.

Prefetch uses normal trust-aware memory search with a short timeout, circuit breaker, and last-good cache, and it warms the connection in the background at initialize rather than letting the first turn's prefetch eat the timeout. Tools expose neutral query context and free-form memory kind, not product workflow fields. A fact the user tells the agent to remember is written `source_role="manual"`; a fact the model decides to keep on its own is `agent` and is excluded from normal retrieval by design (decisions/0006, 0058).

The provider exposes Hermes lifecycle/config/tool methods and backup paths. `memkit install-hermes` activates the provider and configures the restricted `api_key_file`, so Hermes works outside a repository shell without copying a secret into YAML. `MEMKIT_API_KEY` remains an explicit environment override.
