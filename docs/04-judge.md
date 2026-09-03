# Model extraction

The versioned extractor receives redacted evidence, same-context candidates, neutral context, and the window's recording date, which anchors relative time and `valid_until`. Each ADD/UPDATE must cite message ID and exact character range. The service verifies membership, bounds, non-empty text, hashes the excerpt, derives source trust from the cited role, and only then writes. Rejected operations are counted and recorded with a per-op reason in the job result.

Assistant/agent-only evidence cannot add or update memory. DELETE is allowed because it cannot inject a claim. UPDATE/DELETE targets are constrained by owner and exact context.

Structured output is provider-enforced and then parsed again by `judge.Op`. Provider calls occur outside write transactions. Before a call, the job reserves a conservative maximum cost under `BEGIN IMMEDIATE`; actual cost reconciles afterward. Spend plus active reservations cannot exceed the configured monthly ceiling.

One extraction job drains its session rather than a single window: it claims and processes windows in sequence, bounded by the job's call limit, and stops on the first window that makes no progress. A forced run whose backlog exceeds that limit queues a continuation. Each window is one provider call, so the limit is both the spend bound and the work bound.

## The rate card

Prices are per million tokens, generated from `judge.MODELS`. An unknown model is
priced at the most expensive known rate, so an unrecognised identifier can never
under-report against the ceiling. A failure that proves no billing occurred
(missing key, refused connection, 4xx) records zero rather than the reserved
maximum; anything else is estimated for the prompt alone, since a completion
that never arrived was never charged.

<!-- generated:judge-rate-card -->
| model | $/Mtok in | $/Mtok out | |
|---|---|---|---|
| `gemini-3.5-flash-lite` | 0.30 | 2.50 |  |
| `gemini-3.1-flash-lite` | 0.30 | 2.50 | unverified |
| `gemini-3-flash-preview` | 0.30 | 2.50 | unverified |
| `gemini-3.5-flash` | 0.60 | 3.50 | unverified |
| `claude-haiku-4-5` | 1.00 | 5.00 |  |
| `claude-sonnet-5` | 2.00 | 10.00 |  |
| `claude-opus-5` | 5.00 | 25.00 |  |
<!-- /generated:judge-rate-card -->

## The registry

The prompt registry is in `prompts.py`; new rows carry its version. Provider failures, empty Anthropic tool output, tokens, latency, and cost are preserved in `judge_runs`. Secrets are scrubbed again immediately before provider egress.
