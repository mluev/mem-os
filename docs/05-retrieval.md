# Retrieval

Policy `core-retrieval-neutral-v1` fuses three bounded candidate arms:

```text
relevance = 0.60 × dense + 0.30 × normalized_lexical + 0.10 × exact_entity
score     = relevance + 0.10 × importance + 0.05 × recency
```

The **dense** arm is Qdrant cosine over the `memories` collection, filtered on `scope_id` and `status`. The **lexical** arm is Postgres full text: caller terms are combined with `plainto_tsquery('russian', …)` — never interpreted as query syntax — and ranked by `ts_rank_cd` over the generated `search_tsv` column. This is BM25-style lexical ranking, and it replaces the FTS5 arm the weight was chosen for; `ts_rank_cd` is unbounded and higher-is-better, so scores are normalised by the best hit in the arm, which keeps it comparable with cosine without pushing an equally relevant second result below the abstention floor. Qdrant's collections still declare an unused `bm25` sparse slot (decisions/0050); nothing writes to it. The **exact-entity** arm matches literal substrings through the trigram index, because `ERR_X91Q` has no lexeme to stem, which is also what makes it independent of the lexical arm rather than a subset of it as it was under a shared FTS table.

Every arm carries the scope predicate: `scope_id = ANY(caller's scopes)` in SQL, a keyword filter in Qdrant. The dense filter is then re-applied when the candidate rows are fetched from Postgres, because the index is derived and can lag — a stale point must not leak a memory from a scope the caller has lost access to. A scope *named* in the request that the caller does not hold is a 403 before any arm runs; the predicate is for the default case of "everything I can read".

Before scoring, retrieval hard-filters inactive and expired rows, unrequested kinds and context, and assistant/agent provenance unless `include_untrusted` is set. Review status is not a filter: a pending memory is live and retrievable. Confidence is stored for audit but not used in ranking until an evaluation proves it is worth using.

The policy has an explicit minimum relevance (0.18 as seeded). Below it, search returns nothing, so an unrelated request stays silent rather than being answered with the least-distant fact. Token budgeting uses `tiktoken` with a conservative Unicode-aware fallback that counts words and punctuation independently rather than dividing by three.

An optional [semantic relevance block](experiments/jev.md) runs after the existing
filters and relevance floor, before the final limit and token budget. Shadow mode
observes without changing output, rerank changes ordering, and filter also removes
candidates below a configured usefulness score. Provider failure restores the
baseline. Scored items use the semantic 0–3 scale; unchecked tail items in pure
rerank mode retain their hybrid scores. Filter mode excludes the unchecked tail.
The block cannot recover a fact absent from the initial candidate set.

Generic filters support equality, membership, existence/absence, and logical `AND` over kind, agent, tags, and nested neutral context; `subject` narrows to facts about one entity. The returned explanation includes dense, lexical, entity and final scores, dropped IDs by reason, policy ID, token use, and per-arm timings. Each result also names its scope and subject, because a team instance returns facts from several scopes in one response and a caller that cannot tell them apart cannot say "the team decided" rather than "you decided".

`include_sources` attaches up to three verbatim evidence spans per returned memory, each re-sliced from the retained message and verified against its stored hash; a span that no longer matches is dropped, never returned altered. Ranking is unaffected — search runs over atomic facts, the spans carry the detail.

## Profiles

The session preamble is a separate read path: no query, one bounded SQL statement per block, under the same expiry and trust rules. Five blocks, because they answer different questions and a single ranked list answers none of them well — **about** (identity, from the user's own scope), **style** (how they want an agent to work), **team** (rules everyone shares, excluding facts about a particular person, which belong on that person's page rather than in everyone's preamble), **project** (the workspace this session is in, when the caller's workspace resolves to an entity they can read), and **recent** (what has changed lately across every scope they can see). Each block gets a share of the token budget — 0.20/0.35/0.20/0.20/0.05 — and unspent budget rolls forward, so a user with no team rules gets a longer style block rather than a shorter profile.

Splitting them fixed a failure of the earlier stable/dynamic pair: the stable half was selected by `kind`, identity facts fell outside the configured kinds, and a user's name and role dropped out of context entirely once they were older than the dynamic window.

Retrieval feedback records independent usefulness and correctness signals against a run that actually returned the result.

## Optional contribution and source context

`MEMKIT_SEMANTIC_RETRIEVAL=contribution` uses a binary judgment of whether a
candidate supplies any requested detail. The older Score-based filter stays
available. See [the paired experiments](experiments/context-details.md) for the
observed partial-answer regression and the limitations of the new policy.

`MEMKIT_SEMANTIC_CONTEXT=select|compact` applies only to searches explicitly using
`include_raw=true`. It selects facts and user quotations together, returning facts
in `memories` and quotations in `raw`. Both spend `budget_tokens`; `used_tokens`
counts content plus six wrapper tokens per item, including supplemental
`include_sources` quotations. Quoted passages preserve message ID, exact character
offsets, scope and timestamp. A quotation is historical evidence, not a confirmed
current claim. All distributed semantic options remain off by default.

This path re-fetches raw hit IDs from Postgres before any model call, enforcing
current session scope, user role and request filters. The fact path retains its
existing trust/expiry rules. Explicit kind filters admit passages only when they
include `evidence`; subject filters cannot match unattributed raw passages.
Source excerpts attached by ordinary search also recheck the source session's
scope, which can differ from the scope of an extracted team fact.

Candidate arms are interleaved up to 60 items. Contribution is evaluated in
batches of 30 at a measured probability floor of 0.70. Optional compaction uses
at most 12 candidates and the same 0.70 floor for a separate redundancy judgment.
Only surviving earlier items may justify omitting a later one. Outages preserve
the input ordering; compaction failure preserves the relevance-ranked list.
See [decision 0073](decisions/0073-contribution-and-budgeted-source-context.md).
