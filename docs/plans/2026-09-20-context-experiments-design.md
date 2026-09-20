# Detail-preserving context experiments

User-authorized direction: run live Jev experiments, compare against no-Jev
baselines, and implement improvements supported by results. Prioritize useful
context and retained details over reducing provider calls. Existing unrelated
working-tree edits and configured production storage are outside this experiment.

## Frozen questions and comparisons

Use a new synthetic corpus with development and confirmation families separated
before the first provider call. Labels are authored, not independently reviewed;
confirmation is a regression challenge, not evidence about production users.
Use real BGE embeddings, PostgreSQL hybrid retrieval and local exact Qdrant in
disposable storage. Never open the configured application database.

Compare the same token budget and candidate data:

1. Current hybrid facts, without Jev.
2. Current hybrid facts with existing Jev relevance filtering.
3. Broader candidates with Jev filtering (isolates candidate loss).
4. Facts plus verbatim evidence, without Jev (isolates evidence availability).
5. Facts plus evidence with Jev relevance scoring.
6. The same plus semantic redundancy selection (isolates packing).

Separately compare narrow evidence-coverage judgments with exact text matching:
does a source contain a useful detail missing from a proposed memory? This is a
retry/review signal, never a hard admission gate. Explore relation judgments for
context redundancy without changing stored facts or merging history.

Freeze all labels before live calls. Tune questions/policies on development only;
record rejected variants. Freeze the chosen policy before confirmation. Preserve
exact requests, typed answers, errors, corpus/question/source hashes, token use,
latency and pricing assumptions in immutable archives. Report candidate coverage,
detail coverage, irrelevant context, wrong abstentions, redundancy and token use
separately. Repeated requests do not increase the number of independent cases.

## Adoption boundary

Keep existing authorization, trust, expiry and citation validation before provider
egress. Jev calls must occur outside write transactions. Copy evidence exactly;
semantic selection must never turn an assistant assertion into user evidence.
An outage must preserve the baseline, not silently return an empty result.
Bound candidate count, request size and end-to-end work. Retain model/question
versioning and observation-only modes. Promote only independently selectable
blocks that improve the measured workflow; document where evidence remains weak.

Generation stays with the generative extractor; indexes still retrieve candidates.
No automatic evidence-support gate: previous tests lost correct facts. No
production restart or deployment is required for local experiments and code work.

## Development selection, before confirmation

The first score-based filter lost useful partial answers: rubric level 2 means a
partial answer, but its probability-weighted score often falls just below 2.
Observed examples include 1.87 for Harbor's quiet-hours reason and 1.95 for the
Iris animation rationale. This is a question/policy mismatch, not missing data.

Development runs retained 32/40 details with the old evidence filter; contribution
Noul at 0.70 retained 36/40. Redundancy at 0.95 changed nothing. At 0.70, using only
already-kept candidates as coverage, compaction retained 40/40 within 160 tokens,
versus 33/40 for evidence hybrid alone. No irrelevant candidates survived this
development variant. Batch size 30 reduced sequential provider work versus 10.

Freeze before opening confirmation: contribution question v1, floor 0.70,
redundancy question context-v1, floor 0.70, candidate limit 60, batches of 30,
compaction limit 12, context budget 160 including six wrapper tokens per passage.
Retain all original baselines and the unsuccessful 0.95 compaction variant.
Confirmation must not be used to tune these questions or thresholds.
