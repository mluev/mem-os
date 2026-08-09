# Model extraction

The versioned extractor receives redacted evidence, same-context candidates, and neutral context. Each ADD/UPDATE must cite message ID and exact character range. The service verifies membership, bounds, non-empty text, hashes the excerpt, derives source trust from the cited role, and only then writes.

Assistant/agent-only evidence cannot add or update memory. DELETE is allowed because it cannot inject a claim. UPDATE/DELETE targets are constrained by owner and exact context.

Structured output is provider-enforced and then parsed again by `judge.Op`. Provider calls occur outside write transactions. Before a call, the job reserves a conservative maximum cost under `BEGIN IMMEDIATE`; actual cost reconciles afterward. Spend plus active reservations cannot exceed the configured monthly ceiling.

The prompt registry is in `prompts.py`; new rows carry its version. Provider failures, empty Anthropic tool output, tokens, latency, and cost are preserved in `judge_runs`. Secrets are scrubbed again immediately before provider egress.
