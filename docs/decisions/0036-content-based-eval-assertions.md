# 0036 — Eval assertions are regexes over text, never memory ids

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/05-retrieval.md (`expect: ["m-7f2a"]`)
    Superseded by: —
    Evidence:      ../measurements.md#retrieval-eval
    Code:          eval/run.py
    Contract:      ../08-testing.md#layer-3-search

## Decision

Eval cases assert regexes against the text of returned results. They never pin
memory ids, and they do not compare embeddings to a reference phrasing.

## Alternatives and why not

**Pinned ids**, as originally specified, invalidate themselves on the first
re-extraction: `POST /v1/admin/reextract` mints new ids by design. An eval file
that breaks whenever you exercise the operation the whole design is built around
is an eval file that gets disabled.

**Embedding similarity to a reference sentence**, also originally specified, is
more robust to paraphrase and introduces a second embedding-quality question into
the measurement. When such a case fails you cannot tell whether retrieval got
worse or the reference phrasing was unlucky. A regex fails for exactly one reason.

## The cost, acknowledged

Regexes systematically favour raw transcript search, which contains the user's own
words, over extracted facts, which are paraphrases by construction. That bias
sits directly under the stage-2 gate comparison
([0038](0038-stage-2-exit-gate.md)) and is not quantified. It is the strongest
known objection to the numbers in [../measurements.md](../measurements.md), and it
is stated there too.
