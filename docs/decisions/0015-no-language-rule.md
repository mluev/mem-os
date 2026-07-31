# 0015 — The "write in the user's language" prompt rule is removed

    Status:        declined
    Date:          2026-07-31
    Supersedes:    prompt versions v2–v5, rule 8/9
    Superseded by: —
    Evidence:      ../experiments/extractor-prompts.md
    Code:          src/memkit/prompts.py (v6)
    Contract:      ../04-judge.md#what-the-prompt-is-made-of

## Decision

The extractor prompt no longer instructs the model to write a memory in the same
language the user used. Facts are stored in whatever language the model produces,
which in practice is English.

## Alternatives and why not

The rule was in v2 through v5 and reads as obviously correct: a Russian speaker's
preferences should be recorded in Russian.

Measured, it was **ignored about 70% of the time** — 20% of the corpus input is
Russian against 6% of stored facts — and it bought nothing when it was obeyed. A
Russian query retrieves the matching English fact at rank 1, which is precisely what
BGE-M3 was chosen for: it is a multilingual embedding model, and cross-language
retrieval is its main advantage over a cheaper English-only one.

A rule the model ignores most of the time is worse than no rule. It makes the prompt
longer, it makes the output inconsistent — some facts in one language, most in
another, for no reason a reader can discern — and it creates the impression that
storage language is under control when it is not.

One language also keeps the dedup and consolidation cosines comparable. Two
statements of the same preference in different languages score lower against each
other than two paraphrases in one language, so a mixed store makes both thresholds
mean different things depending on which pair they are applied to. That effect was
not measured, and it points the same way.

## What would change this

If facts are ever surfaced directly to the user rather than injected into a model's
context, storage language becomes a presentation concern and this should be reopened
— though the better answer then is probably to translate at read time rather than to
constrain the extractor.
