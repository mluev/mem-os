# Jev opportunities for Mem OS

Date: 2026-09-20. Status: research proposal, not an accepted architecture decision.

Based on the current working tree and live TypeSafe documentation. No Jev experiment was run, so the benefits below are hypotheses to measure. Existing uncommitted implementation work was left untouched.

## Recommendation

Build one versioned semantic judgment component, used by memory workflows and by a separate development/evaluation loop. Give Jev narrow decisions over evidence; keep generation in the existing generative providers and execution in ordinary code.

The useful target is broad semantic coverage, not maximum call count. Extra checks can reject good memories, introduce correlated errors, or distract a model with irrelevant state even when their monetary and latency costs are negligible.

Three possible approaches:

| Approach | Value | Limitation |
| --- | --- | --- |
| Evaluation only | Audits history and changes without affecting production | Does not prevent runtime mistakes |
| Shared judgments across runtime and evaluation — recommended | Reusable questions, traceable decisions, improvements throughout the system | Requires stage-specific evaluation and failure handling |
| Replace the extractor with Jev | Attractive for bounded selection tasks | Jev does not generate arbitrary memory text; a complete replacement is a poor fit |

Mem OS remains a memory service. The workflows discussed here are its ingestion, extraction, retrieval, maintenance, and engineering processes; this proposal does not introduce a task-management engine.

## What the repository already provides

- `src/memkit/extract.py::_validated_evidence` verifies citation membership, text spans, and hashes. It does not determine whether a verified span actually entails a proposed memory.
- `src/memkit/extract.py::plan_dedup` selects write-time duplicates using vector similarity and matching scope/context. This is distinct from the separate, explicit generative-model-confirmed consolidation path.
- `src/memkit/retrieval.py` already has a `Reranker` interface and an identity implementation. The relevance floor currently runs before reranking.
- `src/memkit/prompts.py` uses v10 and combines memory generation with judgments about context, routing, durability, and importance.
- `integrations/claude-code/hooks/memkit_hooks.py::recall_reason` uses English/Russian patterns and entity aliases; recall is opt-in.
- `src/memkit/profiles.py` builds five profile sections using bounded queries ordered by importance and recency.
- `eval/golden.py` and `eval/run.py` provide extraction and retrieval evaluation entry points. Their text matching is regex-based, with deterministic checks for other fields.
- Some older tooling needs repair before reuse: `eval/experiment.py` still refers to the former owner/SQLite-shaped interface, and `eval/context_review.py` imports SQLite. Their presence is not evidence of a working current experiment platform.
- ADR 0068 explicitly parks the replay/promotion program. Historical analysis and promotion into live Postgres must be treated as separate projects.

## Runtime opportunities

| Stage | Jev judgment | Resulting behavior |
| --- | --- | --- |
| Ingestion | Is this a personal assertion, quotation, hypothetical, question, or pasted instruction? | Preserve evidence, but distinguish what may support a fact. Transport provenance remains authoritative. |
| Window preparation | Which nearby turns resolve this reference or correction? | Supply relevant context across artificial ten-message boundaries, with explicit provenance. |
| Extraction coverage | Does this user span contain a durable assertion absent from the proposed operations? | Request a targeted second extraction pass; sample negative decisions to detect missed facts. |
| Evidence support | Do the cited user spans support every part of this exact claim? | Accept, retry, or hold an operation before persistence as a live memory. |
| Memory quality | Is the claim durable, self-contained, and atomic? Has it dropped a qualifier or added a detail? | Return narrowly identified defects to the generative extractor. |
| Context | Would the claim still hold outside the named project? | Evaluate the context field separately from wording, storage scope, and subject. |
| Attribution | Which supplied entity is the sentence about, or is it unknown? | Choose only among authorized candidates plus an explicit unknown outcome. |
| Sharing intent | Is this stated as a personal preference, team rule, or project fact? | Propose routing under the existing policy; code checks membership and write rights. |
| Write-time deduplication | Are these claims equivalent, compatible additions, corrections, contradictory, or unrelated? | Link evidence only for equivalent claims; preserve new details and investigate conflicts. |
| Temporal interpretation | Is the user describing a continuing state, a replacement, or a past state? | Distinguish correction from historical coexistence; code resolves dates and expiry. |
| Retrieval | How directly does each candidate help with this request? | Rerank authorized candidates using a shared relevance scale and allow an empty result. |
| Context assembly | Does this result add useful information beyond facts already selected? | Remove redundant context without hiding conflicting evidence. |
| Recall | Could remembered facts materially help this request, and do the retrieved facts actually help? | Recognize implicit memory needs beyond a phrase list and suppress unrelated injection. |
| Profiles | Which facts belong in each profile block and remain useful for this session? | Improve selection while retaining identity and explicit working constraints. |
| Consolidation | Would the proposed merged wording preserve every supported qualifier? | Reject destructive compression; retain sources and reversible revisions. |
| Historical audit | Is an existing memory unsupported, misattributed, too broadly scoped, or contradicted by later evidence? | Produce a reviewable report and proposed changes. Absence of usage is not proof of falsity. |
| Review queue | Which item is likely wrong and consequential? Which failure category applies? | Prioritize review and select a concrete question or explanation template. |
| Privacy/injection | Does already-redacted content contain suspicious instructions or sensitive context? | Add a defense signal without replacing redaction, source boundaries, or authorization. |

Examples worth testing first:

- “Use pnpm for this repository” must not become “The user always prefers pnpm.”
- “We switched from Redis to Postgres” must not be suppressed as a duplicate of “We use Redis.”
- “Alex prefers dark mode” must not acquire another teammate's identity merely because the names are similar.
- “Continue the approach we settled on” may justify recall even without an existing trigger phrase.
- A newer claim about a different project must not supersede an older claim about this one.

## Development, testing, and iteration

### Semantic assertions

Supplement exact tests with questions such as “Does the saved memory preserve the user's exception?” and “Does this result answer the query rather than merely share its topic?” Keep exact ID, authorization, date, citation, and transaction assertions deterministic.

Jev-generated labels are provisional. A verifier cannot establish its own accuracy, and using the same model to make and grade a decision can conceal shared mistakes. Maintain human-adjudicated examples and independently review a sample of both accepted and rejected outcomes.

### Systematic test expansion

A generative model creates variations; Jev classifies their semantic properties and filters candidates for review. Useful axes include negation, paraphrase, implied corrections, quoted instructions, assistant contamination, name collisions, code-switching, project context, conflicting dates, and repeated facts.

Use transformations with known expectations wherever possible: changing an assistant message should not create user evidence; adding an irrelevant message should not change attribution; revoking access must remove visibility irrespective of every model answer. Execute those expectations in code.

### Automatic experiment loop

1. Run the baseline against a labeled development set.
2. Use Jev to categorize errors: unsupported detail, missing fact, context drift, wrong subject, candidate omission, or irrelevant retrieval.
3. Have a coding/generative model propose one targeted change to prompts, candidate construction, or policy.
4. Run paired comparisons and deterministic checks.
5. Evaluate the selected candidate on an untouched test set and retain a reviewable artifact.

Split by session and, where feasible, by person/project rather than randomly splitting near-duplicate turns. Keep generated variants of the same example together. Do not repeatedly tune against the final test set or silently relabel it to fit the newest system.

### Learned ranking features

Jev can produce reusable dimensions: direct relevance, specificity, applicability to the current project, support from evidence, and redundancy. Combine them with existing dense/lexical scores, recency, and importance. Start with transparent rules; consider a small learned ranker once independently labeled usefulness data is sufficient.

This is training a downstream model on Jev outputs, not fine-tuning Jev. Correctness and usefulness remain distinct labels: a true memory can still be irrelevant.

### Better development assistance

Use narrow judgments to route a change to relevant tests and documentation, rank potentially relevant ADRs, classify failures, and flag an apparent mismatch between a proposed patch and a stated requirement. A coding model investigates and edits; compilers, tests, and reviewers establish correctness. Jev cannot prove a migration safe or validate concurrent behavior by reading prose alone.

### Production feedback and universality

Sample low-confidence cases, disagreements between systems, surprising corrections, and high-confidence decisions. This last group detects confidently wrong behavior. Map reviewer actions to their actual reason: declining an irrelevant fact is not necessarily saying it was false.

Evaluate English, Russian, additional intended languages, mixed-language turns, different professions, unfamiliar domains, and different agent transcript formats separately. Universal behavior requires measured coverage, not only removing domain-specific keywords. Preserve transport-specific parsers where message roles and boundaries are known exactly.

## Integration shape

Create a small shared package, with the name to be chosen during implementation, containing the provider adapter, typed question definitions, composition policies, and audit records. Expose domain operations such as `check_support`, `classify_relation`, and `score_relevance` to callers. Avoid embedding provider prompts throughout hooks and handlers.

Each judgment receives only the state it needs: redacted source spans, explicitly distinguished surrounding context, candidate memory, authorized entity choices, and known dates. Candidate memories and assistant context must not become substitute evidence for a new claim.

Record the question/schema version, resolved model version, evidence references or hashes, candidate IDs/revisions, raw probabilities, selected outcome, and the code policy's action. Records and caches inherit scope controls, redaction, and erasure requirements. An evidence hash identifies an input; it does not retain the input for replay after deletion.

Batch independent questions over the same small state. A dependent question belongs in a subsequent request. Repeated near-identical questions are correlated opinions, not an independent ensemble, and their probabilities must not be multiplied as though they were independent observations.

Keep optional judgment failures distinct from negative answers. Retrieval may fall back to the established ranking policy. A mandatory support check should defer the proposed write on service failure while leaving evidence available for retry. Model calls remain outside write transactions; revision and authorization checks run again when committing.

Two changes need explicit design attention:

1. **Pending is already live.** A held semantic proposal needs a separate disposition before `apply_ops` writes a memory. Reusing `review_status=pending` does not quarantine it. Preserve current review semantics for accepted writes.
2. **Reranking cannot recover omitted candidates.** First use the existing interface to evaluate ordering. Then separately test a broader candidate pool or a revised pre-rerank relevance floor. All scope, provenance, expiry, and request filters still apply before provider egress. Measure candidate recall separately from ranking quality.

Jev is not a drop-in `ProviderResult` implementation: that contract generates free-form operations and memory text. It complements that interface. Adding calls also requires revisiting the existing accounting assumption that one extraction window equals one provider call, even if spending itself is not a constraint.

## Proving an improvement

Start with evidence support, write-time relation checks, and retrieval scoring in observation mode. Compare each addition separately against the current system before combining them. Track:

- unsupported-write rate **and** false rejection of supported facts;
- duplicate suppression **and** false merges/lost corrections;
- correct context, subject, and scope independently;
- candidate recall, ranking quality, useful context delivered, and wrong abstentions;
- reviewer workload and reasons for corrections;
- calibration and accepted-case error by language, domain, and decision type;
- service failure behavior and end-to-end task outcomes.

Use paired cases, repeated runs where relevant, uncertainty intervals, and per-slice results. The existing golden corpus is a regression seed, not sufficient evidence for universal reliability. Choose acceptance thresholds from labeled outcomes and the consequences of each action; do not borrow a cookbook's thresholds.

Keep deterministic tests offline and use stubs/recorded responses for composition, timeouts, retries, and stale revisions. Run real-provider quality evaluations in an explicit separate job with model and question versions recorded. A successful API response is not a successful semantic evaluation.

After these three integrations show improvements, expand to coverage recovery, context/attribution, profiles, recall, and historical audits. For history, generate proposed diffs first; live promotion requires its own concurrency, review, and rollback design under Postgres, as ADR 0068 describes.

## Verified TypeSafe capabilities and sources

- Jev supplies Choice, Noul, and Score judgments; software composes them. Choice selects among options, Noul estimates whether a condition holds, and Score places content on described ordered levels. [Building guide](https://docs.typesafe.ai/concepts/how-to-build-with-system-one), [Python SDK](https://docs.typesafe.ai/sdk/python).
- The model page currently lists `jev-1.13.0`; pin the tested resolved version. It accepts text, and the documentation says English is its strongest language. [Models](https://docs.typesafe.ai/models).
- Choice/Score confidence describes the concentration of the answer distribution. It is not a guarantee of factual truth or end-to-end correctness. Noul has no separate confidence field. [Confidence](https://docs.typesafe.ai/confidence).
- Citation checking pairs deterministic quote lookup with semantic support classification. [Citation cookbook](https://docs.typesafe.ai/cookbooks/citation_check).
- Candidate retrieval followed by per-candidate judgment is a documented pattern. Benchmark gains in its example are not evidence of gains for Mem OS. [Reranking cookbook](https://docs.typesafe.ai/cookbooks/rerank_typesafe).
- A generative proposer can discover questions whose Jev answers become features for a separately trained model. [Feature discovery cookbook](https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery).
- Documented weaknesses include numerical/date comparisons, indirection, distracting state, and adversarial content. Keep arithmetic and exact guarantees in code; keep free-form generation in a generative model. [Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
