# Retrieval

Policy `core-retrieval-neutral-v1` fuses local dense, BM25, and exact entity scores:

```text
relevance = 0.60 × dense + 0.30 × normalized_BM25 + 0.10 × exact_entity
score = relevance + 0.10 × importance + 0.05 × recency
```

Before scoring, retrieval hard-filters wrong owner, inactive/expired rows, unrequested kinds/context, and assistant/agent provenance. Confidence is stored for audit but not used in ranking until an evaluation proves value.

The policy has an explicit minimum relevance. Below it, search returns nothing. Exact identifiers get their own candidate arm in addition to BM25, while unrelated requests can remain silent. Token budgeting uses `tiktoken` and a conservative Unicode fallback.

Generic filters support equality, membership, existence/absence, and logical `AND` over kind, agent, tags, and nested neutral context. The returned explanation includes dense, lexical, entity, final score, dropped IDs by reason, policy ID, token use, and timing.

`include_sources` attaches up to three verbatim evidence spans per returned memory, each re-sliced from the retained message and verified against its stored hash; a span that no longer matches is dropped, never returned altered. Ranking is unaffected — search runs over atomic facts, the spans carry the detail.

Profiles split stable kinds from recent dynamic context under the same expiry and trust rules. Retrieval feedback records independent usefulness and correctness signals.
