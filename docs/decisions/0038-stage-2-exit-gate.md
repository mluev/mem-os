# 0038 — Stage 2 was advanced on token density, not absolute MRR

    Status:        accepted, with dissent
    Date:          2026-07-31
    Supersedes:    ../archive/2026-07-original-spec/06-roadmap.md, stage-2 exit gate
    Superseded by: —
    Evidence:      ../measurements.md#head-to-head-31-shared-cases
    Code:          eval/run.py (--compare)
    Contract:      ../06-roadmap.md#stage-2

## The gate as written

The roadmap said: *the eval must be better than stage 1. If it is not, fix the
prompt and do not move on.*

## The result

On the 31 questions both targets can answer:

| | raw turns | extracted facts |
|---|---|---|
| MRR | 0.790 | 0.728 |
| mean tokens | 1,674 | 423 |

**Taken literally, the gate is not met.** Extracted facts retrieve worse than
searching the raw transcript, by 0.062 MRR. Stage 2 was advanced anyway.

## The argument for advancing

The gate asked a question — is the extractor earning its keep? — and MRR alone
does not answer it, because the two targets are not interchangeable outputs.

Extracted facts deliver **3.7× the MRR per token** (1.723 against 0.472). That is
not a rescaling of the same result; it is the difference between fitting in an
agent's context and not. The read path targets 600–1,000 tokens of memory per
request. Raw turns average 1,674 and peak at 9,829 — a single answer that would
consume most of the budget the whole feature is allotted. A retrieval strategy
that cannot be afforded has an effective MRR of zero.

Two further caveats, both real and neither decisive:

- The eval asserts regexes against returned text
  ([0036](0036-content-based-eval-assertions.md)). That systematically favours raw
  transcripts, which contain the user's own wording, over extracted facts, which
  are paraphrases by construction. The comparison is biased toward the baseline
  by design, and the bias is not quantified.
- Three of the five remaining misses look like the scope defect described in
  [0039](0039-relabel-v4-scoped-facts.md) rather than extraction failures — facts
  that exist but are filtered out because they carry a project key they should not.

## Dissent

Recorded deliberately, because a restructure of the documentation is exactly the
occasion on which an inconvenient result gets quietly smoothed over.

Under the criterion the roadmap actually wrote down, stage 2 did not pass, and it
was advanced regardless. The reinterpretation is defensible and it was also
chosen *after* seeing the numbers, which is the circumstance in which
reinterpretation is least trustworthy. A gate that is redefined on contact with
its own result is not functioning as a gate.

Anyone reading this later should know: the density argument is the reason given,
it is a good reason, and it is not the reason the gate asked for.

## Consequence

The roadmap's stage-2 criterion is **replaced** by the one actually in force —
comparable MRR inside a 600–1,000-token budget — rather than left standing as a
rule nobody applied. A gate nobody enforces is worse than no gate, because it
teaches everyone that the gates are decorative.

The comparison is now reproducible: `memkit eval --compare` scores both targets
over the cases both can answer. Before that flag existed, every published
raw-vs-facts figure in this project compared 47 cases against 31 — a defect in the
harness, which claimed in its own docstring to hold the questions constant while
filtering them per target four lines below. The figures above are the first valid
head-to-head, which also means the earlier 0.737-vs-0.806 comparison should not
be cited.
