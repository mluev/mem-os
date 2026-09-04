# 0065 — Postgres `russian` full text plus pg_trgm replaces FTS5

    Status:        accepted
    Date:          2026-09-04
    Supersedes:    the lexical arm of 0051
    Superseded by: —
    Evidence:      tests/test_fulltext.py; ../measurements.md#to-be-re-measured
    Code:          src/memkit/db.py (search_tsv), src/memkit/retrieval.py
    Contract:      ../05-retrieval.md

## Decision

The lexical arm is a stored generated column, `to_tsvector('russian', text)`, with a GIN index over active rows, queried with `plainto_tsquery('russian', …)` and ranked by `ts_rank_cd`. Caller terms are extracted by the word regex and joined, so input is never interpreted as query syntax. Ranks are unbounded and higher-is-better, so the arm is normalised by its own best hit before fusion.

Exact identifiers get a second, independent arm: `ILIKE` over a `gin_trgm_ops` index.

## Alternatives and why not

**Keep FTS5.** Not available: FTS5 is SQLite. But the reason this is an improvement rather than a substitution is that the old arm was quietly broken for the corpus it served. FTS5's default tokenizer does no stemming at all, so `предпочитаю` and `предпочитает` were different terms, and a query in one inflection could not reach a fact written in another. This project's users write Russian. The lexical arm carries 0.30 of the relevance score, and for most Russian queries it was contributing close to nothing — the dense arm was covering for it, which is exactly why the gap went unnoticed.

**`simple` configuration, or `english`.** `simple` is FTS5's behaviour with extra steps: no stemming, same blindness. `english` stems ASCII and passes Cyrillic through unchanged, which fixes the language that was already working. The `russian` configuration maps Cyrillic through `russian_stem` and ASCII through `english_stem` in one column, so a mixed-language store — which every conversation here is — needs one index and one query, not two of each with a language guess in front.

**A per-row language column and two tsvectors.** Correct in principle and unimplementable in practice on this data: a memory is a single sentence, often mixed ("предпочитает pnpm"), and per-row language detection at that length is a coin flip. One configuration that handles both alphabets is less precise in theory and right more often in fact.

**Fold identifiers into the text-search arm.** Tried under FTS5 and it is why the identifier arm now uses trigrams. `ERR_X91Q` has no lexeme to stem, and `plainto_tsquery` ANDs its terms, so one ordinary word alongside the code empties the arm. Trigram matching also makes the two arms genuinely independent — under a shared FTS table the entity arm was a subset of the lexical one, so the 0.10 weight was double-counting the 0.30.

**pgvector for the dense arm at the same time.** Considered and deferred with the store itself; see [0059](0059-postgres-truth-qdrant-index.md).

## Consequences

Lexical search cannot drift from the row: a generated column is recomputed by the database on every write, so there are no insert/update/delete triggers to maintain and no equivalence test to keep the projection honest. Migrating the stemmer means a schema change and a table rewrite rather than a rebuild of a side table, which is the fair price for that.

Every retrieval number measured before this change was measured against an unstemmed lexical arm and does not carry over. `measurements.md` marks them superseded; the eval must be re-run before the 0.60/0.30/0.10 weights or the 0.18 floor are defended again.
