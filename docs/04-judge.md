# Model extraction

The versioned extractor receives redacted evidence, same-context candidates, a numbered block of the entities the speaker can see, neutral context, and the window's recording date, which anchors relative time and `valid_until`. Each ADD/UPDATE must cite message ID and exact character range, or a verbatim `quote` from which the service derives the offsets. The service verifies membership, bounds, non-empty text, hashes the excerpt, derives source trust from the cited role, resolves routing, and only then writes. Rejected operations are counted and recorded with a per-op reason in the job result.

Assistant/agent-only evidence cannot add or update memory. DELETE is allowed because it cannot inject a claim. UPDATE/DELETE targets are constrained by scope and exact context.

Structured output is provider-enforced and then parsed again by `judge.Op`. Provider calls occur outside every write transaction, as do the embedding and index round-trips that plan write-time dedup: nothing slow may hold a write transaction open. Before a call, the job reserves a conservative maximum cost — the UTF-8 byte count of the prompt as an input floor, plus a full 4,096-token completion — and reconciles the actual cost afterwards. Spend plus active reservations cannot exceed the configured monthly ceiling.

One extraction job drains its session rather than a single window: it claims and processes windows in sequence, bounded by the job's call limit, and stops on the first window that makes no progress — nothing left to claim, a refusal by the gate, a provider error, or cancellation. Each window is one provider call, so the limit is both the spend bound and the work bound.

## Routing

A team instance has more than one place a fact can go, and the model is the only participant that has just read the sentence, so it decides — but only by number, and only among entities it was shown. The prompt renders the block as `1. you, the speaker: …`, `2. team: …`, then projects, products, and teammates, each with the aliases people actually say. Operations return `scope` and `subject` as integers into that list. This is the same remap that stopped fabricated candidate ids (decisions/0054): a uuid shown to a model comes back subtly mutated, a name comes back guessed, while an integer outside the block is provably fabricated and is dropped as `unknown_entity`. The map is recorded with the run, so a stored fact can be explained later.

The rules, in the order they apply:

- A fact about the speaker needs no scope and no subject; when torn between the speaker and the team, the prompt says choose the speaker.
- A fact about a listed teammate sets `subject` and omits `scope`, and lands in the **team** scope with that person as subject. Deliberately not private: the team's picture of a person is shared, and the person can see and delete it (decisions/0063).
- A fact about a listed project, product, or company sets `scope` to its number; a rule stated for everyone sets `scope` to the team's number with no subject.
- A person who is *not* in the list resolves to nothing. The name is copied verbatim into `subject_name`, the fact stays in the speaker's private scope and unattributed, and a `needs_attention` item asks a human who was meant. Guessing which teammate was meant would put a claim on the wrong person's profile, which is worse than leaving it unattached.

Alias resolution is exact on the case-folded form. A named scope the speaker may not write to is refused rather than quietly redirected, because a fact written to the wrong scope is either a leak or a loss.

## Rejection reasons

Recorded per operation in the job result, so a prompt regression is legible without a new table:

`evidence_invalid` (no citation, a message outside the window, an ambiguous or non-verbatim quote, an out-of-range span), `assistant_only_source`, `context_mismatch` (op context that cannot be mapped onto the session's own keys), `unknown_candidate`, `unknown_entity`, `scope_not_allowed`, `target_scope_mismatch`, `target_context_mismatch`. A vanished UPDATE/DELETE target counts as `skipped` rather than rejected; a near-verbatim ADD absorbed into an existing memory counts as `deduplicated`, and its citations are linked to that memory rather than lost.

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

The prompt registry is in `prompts.py`; new rows carry its version. v9 is v8 plus the entity block and the routing rules above. Provider failures, empty Anthropic tool output, tokens, latency, and cost are preserved in `judge_runs`. Secrets are scrubbed again immediately before provider egress.
