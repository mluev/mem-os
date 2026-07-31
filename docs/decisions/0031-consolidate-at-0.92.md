# 0031 — Consolidation clusters at cosine 0.92

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/05-retrieval.md (predicted it would merge nothing)
    Superseded by: —
    Evidence:      ../measurements.md#consolidation
    Code:          src/memkit/config.py (`consolidate_cosine`)
    Contract:      ../04-judge.md#the-consolidator

## Decision

Nightly consolidation clusters facts at cosine 0.92, overridable per request and
by `MEMKIT_CONSOLIDATE_COSINE`. Deliberately stricter than the read-path dedup at
0.90, because dedup hides a duplicate from one answer while consolidation rewrites
the store — a wrong hide is invisible next query, a wrong merge is permanent.

## The prediction it overturned

The retrieval document predicted 0.92 would cluster almost nothing, reasoning from
the dedup measurements where a real paraphrase scored 0.8979. That was a
reasonable inference and it was wrong, because the paraphrases that matter for
consolidation are not the ones that matter for dedup.

The first real run found one cluster: "User's name is Maga Luev" against "User's
name is Maga (or MagaLoviev)" at **0.9278**. The pair that must never merge
("Prefers pnpm" / "Prefers pytest") sits at 0.7422. There is room between them.

Since then, live data has produced a pair at **0.9925** and another at **0.9821** —
both well clear.

## What the first run also showed

The surviving merged fact preserved two incorrect spellings of the user's name.
Consolidation combines what it is given; it does not adjudicate. A merge cannot fix
bad input, and expecting it to is a category error worth writing down, since the
temptation to treat the consolidator as a cleanup pass is strong.

## The real constraint is not the threshold

The 0.9821 pair will never merge, because clustering partitions by `type` and the
agent that wrote both labelled one `project` and one `fact`
([0032](0032-cluster-connected-components.md)). At present the type partition
blocks more merges than the threshold does.
