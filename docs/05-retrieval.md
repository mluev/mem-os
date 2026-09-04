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

Generic filters support equality, membership, existence/absence, and logical `AND` over kind, agent, tags, and nested neutral context; `subject` narrows to facts about one entity. The returned explanation includes dense, lexical, entity and final scores, dropped IDs by reason, policy ID, token use, and per-arm timings. Each result also names its scope and subject, because a team instance returns facts from several scopes in one response and a caller that cannot tell them apart cannot say "the team decided" rather than "you decided".

`include_sources` attaches up to three verbatim evidence spans per returned memory, each re-sliced from the retained message and verified against its stored hash; a span that no longer matches is dropped, never returned altered. Ranking is unaffected — search runs over atomic facts, the spans carry the detail.

## Profiles

The session preamble is a separate read path: no query, one bounded SQL statement per block, under the same expiry and trust rules. Five blocks, because they answer different questions and a single ranked list answers none of them well — **about** (identity, from the user's own scope), **style** (how they want an agent to work), **team** (rules everyone shares, excluding facts about a particular person, which belong on that person's page rather than in everyone's preamble), **project** (the workspace this session is in, when the caller's workspace resolves to an entity they can read), and **recent** (what has changed lately across every scope they can see). Each block gets a share of the token budget — 0.20/0.35/0.20/0.20/0.05 — and unspent budget rolls forward, so a user with no team rules gets a longer style block rather than a shorter profile.

Splitting them fixed a failure of the earlier stable/dynamic pair: the stable half was selected by `kind`, identity facts fell outside the configured kinds, and a user's name and role dropped out of context entirely once they were older than the dynamic window.

Retrieval feedback records independent usefulness and correctness signals against a run that actually returned the result.
