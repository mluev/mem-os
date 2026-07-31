# 0008 — The judge is `gemini-3.5-flash-lite` on the Gemini Developer API

    Status:        accepted
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/04-judge.md (Haiku 4.5 on the Claude API)
    Superseded by: —
    Evidence:      ../measurements.md#cost
    Code:          src/memkit/config.py, src/memkit/providers.py
    Contract:      ../04-judge.md#model-and-provider

## Decision

The default extractor and consolidator model is `gemini-3.5-flash-lite`, reached
through the **Gemini Developer API** — an API key alone, no GCP project and no
gcloud. Vertex AI is also supported and needs `VERTEX_PROJECT` plus
`VERTEX_LOCATION`; it is a second supported path, not a requirement. Claude models
stay wired so prompt versions can be compared on one eval.

## Alternatives and why not

The archived spec chose `claude-haiku-4-5` and priced the project around it. Two
things changed.

**Cost.** Flash-Lite is $0.30/$2.50 per Mtok against Haiku's $1.00/$5.00 —
roughly $0.0009 per call against $0.0023, and about $0.21 against $0.55 for a full
corpus backfill.

**Quality, measured, and in the opposite direction to expectation.** On the golden
set, Flash-Lite scored 8/8 on scope with zero false positives. `gemini-3.5-flash`
invented a fact from a work log and emitted ADD where UPDATE was correct.
`claude-sonnet-5` produced more facts per window but wrote 2,161-character walls —
whole session changelogs stored as single memories. For this task, which is mostly
*declining* to store things, the bigger models were worse.

## Note on three contradictory claims

Before this reconciliation, the project asserted in three places that the judge
was Haiku 4.5 on the Claude API, Flash-Lite on Vertex AI, and `claude-sonnet-5`.
All three were wrong in some respect: the model is Flash-Lite, the provider is the
Developer API by default, and Sonnet 5 appears only in 25 comparison runs. This is
the single most-repeated error in the old documentation and the reason the model
name is now generated from `judge.MODELS` rather than typed.
