# Semantic corpora

`multiscenario-v1.json` contains 72 authored probes in **12 related scenario
families**, across development, education and personal assistance. Each cohort
has English, Russian, Uzbek and mixed-language scenarios. These are fictional
profiles, not real users, and labels have not had independent human review.

Each family contributes an equivalent pair, a different pair, an answerable and
an unanswerable query, and positive/negative source-support checks. The family,
not every derived probe, is the independence unit. The same scenarios were later
reused for hybrid retrieval and batched duplicate diagnostics; those are not new
heldout sets. v2 questions and thresholds were frozen before the first run.

Retrieval labels include both conflicting accounts about the requested fact:
both can help disclose a conflict. A ranking judgment cannot decide which is true
or authorize overwriting one. Different-person/project distractors are irrelevant.

External JSON corpora can use the same fields: unique `id`, `split` (`dev` or
`heldout`), `stage` (`support`, `relation`, `relevance`), `language`, `scenario`,
`cohort`, `state`, and `expected`. Support labels are booleans; relation labels use
the question registry; relevance labels are zero-based candidate indexes.

Use pseudonymous cohort identifiers for private participants, document consent
and label provenance outside public fixtures, and keep private inputs/reports in
access-controlled storage. New independent user cohorts should be held back until
the questions and thresholds are frozen. Do not tune on this already opened set.
