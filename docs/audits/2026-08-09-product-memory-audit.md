# memkit product and memory-quality audit

**Audit date:** 2026-08-09  
**Mode:** read-only repository audit. No repository file was modified.  
**Scope:** extraction, provenance, personalization, correction, consolidation, retrieval relevance, token efficiency, latency, extensibility, evals, and developer/API ergonomics.

## Executive verdict

memkit is a thoughtful, unusually auditable **single-user, local long-term memory service**. Its strongest product qualities are reversibility, inspectability, local read latency, source preservation, prompt/version discipline, and explicit cost control. It is materially beyond a toy: the source of truth is recoverable, mutations are mostly reversible, extraction runs are logged, search decisions can be explained, and the test suite is broad.

It is not yet a safe general-purpose memory substrate for arbitrary agents. Four issues dominate:

1. **Provenance is recorded better than it is enforced.** Every extracted operation cites the whole window, so any user turn makes every fact look user-sourced; direct assistant-authored memories are labeled but still retrieved and injected without that label. The self-reinforcement loop is visible, not closed.
2. **Correction and consolidation are not scope-safe.** Extraction candidates are owner-wide and omit scope metadata; UPDATE ignores a returned scope. Consolidation clusters by owner+type across scopes and inherits the newest member's scope.
3. **Retrieval cannot intentionally stay silent on an irrelevant query.** There is no relevance threshold or adaptive output policy, and the eval has zero “not a memory question” cases. The evidence used to decline a threshold therefore does not test the main reason to have one.
4. **The current store has not converged to the current design.** A read-only aggregate query found 97 active memories, but 60 are still `v4`, only one is `v6`, 60/97 are project-scoped, and 18 exceed the prompt's 200-character limit.

**Product position:** strong personal/local memory system; mixed memory quality under correction and long-run operation; weak as a multi-agent, user-extensible memory platform.

## Evidence and method

- Inspected all core Python paths, docs, ADRs, eval harnesses, Hermes integration, and representative tests.
- Ran the offline suite with bytecode writes disabled: **399 tests passed in 10.692 s**. This validates plumbing, not live judge quality or scale.
- Queried `data/memkit.db` through SQLite `mode=ro` for aggregate state only. No fact text or private content is reproduced here.
- Did not call a paid judge, mutate SQLite/Qdrant, run re-extraction/consolidation, or exercise live search.
- Network access worked. The external comparison uses current official repositories/docs and is explicitly separated from local evidence.

## Scorecard

| Area | Assessment | Bottom line |
|---|---|---|
| Extraction | **Strong design, mixed enforcement** | Good gates, context windows, structured output, replay, and prompt iteration; candidate scope and per-operation evidence are unsafe. |
| Provenance | **Excellent observability, incomplete trust policy** | Source links and judge logs are first-rate; assistant-origin facts can still re-enter prompts as ordinary facts. |
| Personalization | **Useful but narrow** | Owner/project/task scope works; no maintained profile, agent-specific retrieval, or configurable ontology. |
| Correction | **Mixed** | UPDATE/DELETE, soft lifecycle, optimistic concurrency, supersession, and replay exist; automatic updates miss scope and global contradictions. |
| Consolidation | **Promising but unsafe across scopes/types** | Reversible merges and provenance inheritance are good; cluster partitions are too weak and expiry is periodic only. |
| Retrieval relevance | **Good ranking foundation, weak precision control** | Scope filtering and composite scoring are sound; dense-only retrieval and no “silence” policy limit relevance. |
| Token efficiency | **Strong locally, approximate end-to-end** | Facts are far denser than raw turns; budgeting uses a character heuristic and old overlong facts remain active. |
| Latency | **Good for one local user, unproven under load** | Local embeddings and async extraction are right; network calls occur inside write transactions and vector search is currently brute-force. |
| Arbitrary agent information | **Missing as a platform capability** | Text can be forced into `fact`, but types/scopes/metadata/lifecycle are hard-coded. |
| Eval design | **Intellectually strong, coverage-limited** | Honest partitions, MRR/token, negative extraction cases, and content assertions; missing temporal, silence, scale, and response-quality coverage. |
| Developer/API ergonomics | **Good operator surface, immature SDK surface** | OpenAPI, dry runs, idempotency, explainer, and admin UI are good; no SDK, ignored fields, ambiguous scope parameters, and weak async-job semantics. |

## Priority recommendations

### P0 — protect memory truth before adding retrieval features

#### 1. Close the provenance loop

Require `source_message_ids` per operation, validate that they are members of the presented window, and derive provenance from those cited messages. Reject assistant-only ADD/UPDATE by default. For direct writes, either separate human/manual and agent credentials or require an explicit writer class with a restrictive default.

Put `source_role` on the read path: return it in search, expose it to the consuming agent, and make retrieval policy able to exclude/down-rank assistant-authored facts. Today Hermes correctly sends `source_role="assistant"` ([client.py:132](/Users/mlutfullaev/dev/indie/mem-os/integrations/hermes/memkit/client.py:132)), but the Qdrant payload omits it ([store.py:333](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/store.py:333)) and ranking does not use it ([retrieval.py:251](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:251)).

Acceptance cases:

- A mixed window with one user turn and an assistant-only proposed fact is rejected.
- An assistant-authored direct memory is absent from normal prefetch unless the caller explicitly opts in.
- Search/prefetch identifies the authority of every returned fact.

#### 2. Make correction and consolidation scope-safe

Use the same owner/scope constraints for extraction candidates as for retrieval, or at minimum include `scope` and `scope_key` in the candidate prompt and reject cross-scope UPDATEs unless the operation explicitly changes scope. Apply a returned scope on UPDATE—or remove it from UPDATE schema and make the limitation explicit. Candidate selection currently filters only owner and active status ([extract.py:223](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:223)), returns no scope fields ([extract.py:238](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:238)), and UPDATE does not apply `op.scope` ([extract.py:357](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:357)).

Partition consolidation by at least `(owner_id, type, scope, scope_key)`, or show scope to the merge judge and require an explicit target scope. Current clustering searches by owner+type ([consolidate.py:159](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:159)), selects no scope columns ([consolidate.py:197](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:197)), and inherits the newest fact's scope ([consolidate.py:405](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:405)). Add cross-project and user-vs-project consolidation tests; none are present in the consolidation suite.

#### 3. Make “no useful memory” and validity hard read-path properties

Add eval cases first for irrelevant/degenerate queries, then calibrate a relevance policy using precision, false-injection rate, and answer quality—not recall alone. A threshold, calibrated score margin, query classifier, or adaptive mode is acceptable; unconditional nearest-neighbor fill is not.

Also exclude expired-by-date facts during search, independent of a nightly job. The consolidator explicitly says the read path does not enforce `valid_until` ([consolidate.py:1](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:1)); scope filtering only requires owner/status/scope ([retrieval.py:199](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:199)). A missed launchd run must not make an expired plan true again.

### P1 — repair quality and operational consistency

1. **Repair the live store after P0 changes.** Dry-run and review a v6 re-extraction/relabel pass. Current read-only aggregates: 60 active v4 facts, one v6 fact, 60 project-scoped vs 37 user-scoped, and 18 active texts over 200 characters. Preserve rollback through the existing supersession path ([reextract.py:274](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/reextract.py:274)).
2. **Complete UPDATE semantics.** Support scope correction, allow `valid_until` to be explicitly cleared (current `or` preserves it: [extract.py:368](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:368)), validate timestamps, and enforce fact length in code/schema rather than only in prompt text.
3. **Shorten database write transactions and make jobs durable.** Extraction starts a transaction around embedding and the cloud call ([api.py:196](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:196)); re-extraction and consolidation wrap entire multi-call runs in one transaction ([admin.py:1009](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/admin.py:1009), [admin.py:1058](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/admin.py:1058)). Stage model calls outside short write transactions, add job identity/status, and serialize maintenance work.
4. **Fix raw-index delivery consistency.** `POST /v1/messages` commits SQLite, then indexes Qdrant ([api.py:222](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:222)); a retry with the same external id returns early as deduplicated ([api.py:233](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:233)). If the first indexing call fails, that message stays unindexed until a manual reindex. Record index-dirty state or use a retryable outbox.
5. **Add hybrid retrieval behind an eval.** Exact terms, identifiers, filenames, and acronyms are the visible dense-retrieval weakness. The collection already reserves a sparse slot ([vectors.py:49](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/vectors.py:49)); implement BM25 plus fusion only with arm-by-arm metrics and exact-term cases.
6. **Use confidence and provenance in ranking.** The model writes `confidence`, but the composite score uses similarity, importance, recency, and scope only ([retrieval.py:188](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:188)). Calibrate whether confidence helps; do not add it by intuition.
7. **Expand evals to correction and long-run memory health.** Add contradiction/update, expiry, supersession, cross-scope, multi-session temporal, assistant-poisoning, and store-growth cases. Run at multiple corpus sizes.

### P2 — turn the service into a reusable memory platform

1. Add namespaces/container tags and free-form validated metadata; allow application-defined categories and lifecycle policies without schema migrations.
2. Add a profile endpoint that returns compact stable/dynamic context, with configurable sections. Retrieval alone cannot guarantee that identity and standing preferences appear when the query is unrelated.
3. Publish a small typed Python/TypeScript SDK. Generate and check clients from OpenAPI; the repository already admits the checked-in web schema can drift ([08-testing.md:219](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:219)).
4. Remove or implement API ambiguities: `agent_id` is accepted but unused, and `scope_key`/`project` are overlapping ways to state context ([03-api.md:82](/Users/mlutfullaev/dev/indie/mem-os/docs/03-api.md:82)).
5. Add tokenizer-aware budgeting with a conservative fallback, response-envelope models, cursor pagination, batch ingest, and an extraction job/status API.
6. Benchmark concurrency and 10k/100k-memory behavior; define when to enable HNSW, and report p50/p95/p99 end-to-end search latency rather than embedding latency alone.

## Detailed audit

### 1. Extraction

**What works**

- Ten-message windows preserve conversational context, while assistant-only runs are fast-forwarded and three lead-in turns are retained ([extract.py:79](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:79), [extract.py:97](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:97)).
- Candidate embeddings use user turns only, reducing work-log dilution ([extract.py:172](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:172)).
- The active v6 prompt is concrete about durability, atomicity, self-contained facts, correction signals, negative cases, scope, credentials, and importance calibration ([prompts.py:454](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/prompts.py:454)).
- Provider schemas are strict and `Op.parse` enforces cross-field validity ([providers.py:83](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/providers.py:83), [judge.py:166](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/judge.py:166)).
- Prompt versions are replayable and stamped on facts ([prompts.py:554](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/prompts.py:554), [reextract.py:195](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/reextract.py:195)).
- Calls log model, prompt version, input/output, tokens, cost, latency, and error ([judge.py:450](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/judge.py:450)).
- Cost and failure controls are practical: an extraction gate, no-user fast-forward, three-attempt abandonment, and a monthly spend check ([judge.py:316](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/judge.py:316), [extract.py:478](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:478)).

**What is missing or risky**

- Every operation cites every message in the window, rather than its actual evidence ([extract.py:291](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:291)). This defeats per-fact provenance and makes the assistant-only guard unable to fire in normal extraction, as the repository itself acknowledges ([provenance.py:13](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/provenance.py:13)).
- Candidate recall is capped at eight similar facts, dense-only, across all owner scopes ([extract.py:24](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:24), [extract.py:205](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:205)). Contradictions outside that pool become ADDs.
- The 200-character rule is not schema-enforced. `Op.parse` only requires non-empty text ([judge.py:173](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/judge.py:173)); direct API text is also unbounded ([api.py:79](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:79)).
- The monthly “hard ceiling” can overshoot by one call because it checks only already-recorded spend before calling the provider ([judge.py:390](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/judge.py:390)). This is small at current prices but should be described accurately.
- Background tasks are process-local, not durable. Messages remain recoverable, but a lost tail waits for a later trigger, session close, or manual backfill.

### 2. Provenance

**What works**

- Raw messages are append-only; facts link to source messages; judge runs and supersession chains remain inspectable ([db.py:48](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/db.py:48), [db.py:135](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/db.py:135)).
- `source_role` is NOT NULL, constrained, and deliberately has no default in SQLite ([db.py:104](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/db.py:104)).
- The sources API returns messages, role tallies, judge output, task metadata, and both sides of the supersession chain ([api.py:304](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:304)).
- Consolidation preserves all source links and inherits the weakest authority label, avoiding provenance laundering during merges ([consolidate.py:416](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:416), [consolidate.py:438](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:438)).

**What is missing or risky**

- Empty-evidence direct writes are allowed and default to `manual` ([provenance.py:104](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/provenance.py:104), [store.py:250](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/store.py:250)). For an API primarily called by agents, a forgotten `source_role` overstates authority.
- Assistant-authored facts are counted but neither rejected nor treated differently during search. The main self-poisoning threat is therefore observable after the fact, not prevented before prompt injection.
- `source_role` is a single collapsed label. It cannot express “direct user statement,” “inferred from user behavior,” “agent observation,” “tool result,” or the exact evidence span. Per-operation citations would materially improve auditability.
- Tool messages are mapped to assistant at ingest because the HTTP schema accepts only user/assistant ([Hermes provider:304](/Users/mlutfullaev/dev/indie/mem-os/integrations/hermes/memkit/__init__.py:304)). The `tool` provenance vocabulary is currently unreachable.

### 3. Personalization

**What works**

- Owner isolation and user/project/task scope are first-class in SQLite and Qdrant ([db.py:84](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/db.py:84), [vectors.py:35](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/vectors.py:35)).
- Foreign-project facts are filtered before ranking, not merely down-weighted ([retrieval.py:199](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:199)).
- Per-type decay distinguishes durable identity/preferences from short-lived tasks ([retrieval.py:40](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:40)).
- The prompt's “travel test” corrected a measured tendency to bind personal preferences to repositories ([judge.py:194](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/judge.py:194)).

**What is missing or risky**

- There is no maintained user profile or stable/dynamic summary. Search is query-dependent; identity may disappear when a turn is semantically unrelated. An unused `render_profile` helper exists ([prompts.py:673](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/prompts.py:673)), but production v6 does not consume it.
- `agent_id` is stored and indexed but ignored by `/v1/search` semantics. The API accepts a control it does not honor ([api.py:58](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:58), [03-api.md:93](/Users/mlutfullaev/dev/indie/mem-os/docs/03-api.md:93)).
- One static API key can request any `owner_id`; owner IDs are partitions, not an authorization boundary. The roadmap explicitly says second-user authentication is not started ([06-roadmap.md:69](/Users/mlutfullaev/dev/indie/mem-os/docs/06-roadmap.md:69)).
- The v6 design explicitly accepts some cross-project leakage to avoid hiding personal facts ([prompts.py:565](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/prompts.py:565)). That trade needs a cross-project precision metric, not only scope-label recall.

### 4. Correction

**What works**

- The judge can ADD, UPDATE, and DELETE; hallucinated IDs are skipped; deletion is soft ([extract.py:357](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:357), [extract.py:407](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/extract.py:407)).
- Manual edits use optimistic concurrency, re-embed changed text, and update Qdrant after SQLite commit with dirty-index reporting ([mutate.py:148](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/mutate.py:148), [admin.py:162](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/admin.py:162)).
- Supersession prevents cycles and preserves the old row ([mutate.py:273](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/mutate.py:273)).
- Re-extraction creates a fresh set and retires old facts only after successful replacement, with rollback IDs returned ([reextract.py:218](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/reextract.py:218)).

**What is missing or risky**

- Automatic correction depends on the contradictory fact appearing among eight dense candidates. There is no global contradiction pass, entity/current-state index, or lexical/entity candidate arm.
- UPDATE changes text/type/importance/confidence/validity but not scope or scope key, despite the operation schema carrying scope.
- A null `valid_until` cannot clear an old value in judge-driven UPDATE.
- There is no end-user correction/feedback endpoint distinct from administrative PATCH, nor an eval metric for accepted/rejected corrections over time.

### 5. Consolidation

**What works**

- Expiry, stale demotion, near-duplicate clustering, model-reviewed merge, and reporting are separated and observable ([consolidate.py:1](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:1)).
- Merges are reversible: a new survivor is written and inputs are superseded rather than deleted ([consolidate.py:396](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:396)).
- The model has an explicit “decline merge” result, important because semantic similarity is not equivalence ([prompts.py:586](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/prompts.py:586)).
- Connected components catch transitive duplicate clusters; oversized clusters are skipped defensively ([consolidate.py:182](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/consolidate.py:182)).

**What is missing or risky**

- Same-type partitioning misses duplicates mislabeled with different types; the repository has measured exactly this failure ([measurements.md:187](/Users/mlutfullaev/dev/indie/mem-os/docs/measurements.md:187)).
- Conversely, same-type facts from different scopes/projects can merge because scope is absent from clustering and the merge prompt.
- A connected component may contain A~B and B~C while A and C are meaningfully different. The judge can decline the whole cluster but cannot partition it into safe sub-merges.
- Demotion is usage-only. A frequently retrieved wrong fact strengthens its operational persistence; no correctness feedback offsets retrieval count.
- Scheduling is a hard-coded local launchd artifact, not a portable scheduler or durable worker ([README.md:89](/Users/mlutfullaev/dev/indie/mem-os/README.md:89)).

### 6. Retrieval relevance

**What works**

- Retrieval combines similarity, importance, per-type recency, and scope ([retrieval.py:33](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:33)).
- Qdrant enforces owner, active status, and valid scope before the top-50 pool, preventing foreign-project crowd-out ([retrieval.py:212](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:212)).
- Greedy vector dedup retains the highest-ranked near-duplicate ([retrieval.py:310](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:310)).
- The explainer exposes chosen facts and scope/dedup/budget drops plus live weights and embedding time ([retrieval.py:105](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:105)).
- Measured facts are much denser than raw turns: the repository reports MRR 0.728 vs 0.790 but 423 vs 1,674 mean tokens, a 3.7× MRR/token advantage ([measurements.md:143](/Users/mlutfullaev/dev/indie/mem-os/docs/measurements.md:143)).

**What is missing or risky**

- Dense cosine is the only retrieval signal. BM25 is declared but unused ([0050 ADR:11](/Users/mlutfullaev/dev/indie/mem-os/docs/decisions/0050-bm25-deferred.md:11)).
- No minimum relevance or adaptive output size means unrelated queries normally receive the best available in-scope facts. Empty output is realistically reached only when scope excludes everything or the budget is too small; with user-scoped facts and the default budget, that is uncommon.
- Importance is model-assigned and contributes a near-constant base score. High-importance generic facts can surface repeatedly even at low semantic similarity.
- Retrieval feedback records exposure, not utility or correctness ([store.py:228](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/store.py:228)). It cannot tell helpful retrieval from harmful prompt pollution.
- Current scale claims are not transferable: the measured store has 97 active facts and no built HNSW index; the docs warn latency will not hold at 10,000 facts ([measurements.md:213](/Users/mlutfullaev/dev/indie/mem-os/docs/measurements.md:213)).

### 7. Token efficiency

**What works**

- Read context is compact, locally generated, and bounded by caller budget. Oversized items are skipped rather than terminating the fill ([retrieval.py:355](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:355)).
- Assistant turns are truncated to 220 characters for judge prompts, while user turns remain intact ([judge.py:331](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/judge.py:331)).
- Assistant-only windows are skipped and candidate embeddings use only user turns, reducing both judge cost and duplicate-producing context dilution.
- Current measured extraction averages about 2,990 input and 90 output tokens per call; local read context averages 423 tokens in the published eval ([measurements.md:118](/Users/mlutfullaev/dev/indie/mem-os/docs/measurements.md:118), [measurements.md:148](/Users/mlutfullaev/dev/indie/mem-os/docs/measurements.md:148)).

**What is missing or risky**

- `len(text)//3` is only a rough estimate and does not count bullet formatting, labels, or the target model's tokenizer ([retrieval.py:380](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:380)).
- The 200-character extraction target is advisory. Current read-only data contains 18 active facts over 200 characters and three over 600; the longest is 2,161 characters.
- A fixed 800-token budget is not query-adaptive. Narrow turns can receive avoidable memory; broad profile questions can be truncated.
- No profile synthesis means frequently useful standing context is paid repeatedly as separate facts rather than periodically compacted.

### 8. Latency

**What works**

- Embeddings and Qdrant are local; extraction is off the interactive message path ([01-architecture.md:24](/Users/mlutfullaev/dev/indie/mem-os/docs/01-architecture.md:24)).
- The embedder is eagerly loaded and warmed before traffic, avoiding a 11–17 s first-request penalty ([api.py:98](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:98)).
- Published embedding median is 36.9 ms on MPS; Hermes warm prefetch is reported at 75–93 ms with a 0.4 s bound ([measurements.md:78](/Users/mlutfullaev/dev/indie/mem-os/docs/measurements.md:78), [07-hermes-adapter.md:94](/Users/mlutfullaev/dev/indie/mem-os/docs/07-hermes-adapter.md:94)).
- Hermes has warm-up, cache fallback, timeout, and a circuit breaker; prefetch never breaks the agent turn ([Hermes provider:213](/Users/mlutfullaev/dev/indie/mem-os/integrations/hermes/memkit/__init__.py:213), [client.py:73](/Users/mlutfullaev/dev/indie/mem-os/integrations/hermes/memkit/client.py:73)).

**What is missing or risky**

- The MPS embedder is protected by one process-wide lock ([embed.py:77](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/embed.py:77)); concurrent searches serialize at embedding.
- Cloud judge calls happen while a SQLite transaction is open. Current read-only judge aggregates show extraction averaging ~1.7 s, long enough to create write contention; SQLite permits one writer and has a 5 s busy timeout ([db.py:357](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/db.py:357)).
- Search returns `took_ms`, but search latency is not persisted or summarized as p95/p99. Judge latency is logged; read-path SLOs are not.
- Returning 50 full 1,024-dimensional vectors for dedup is acceptable locally but should be measured at concurrency and larger pools ([retrieval.py:449](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/retrieval.py:449)).

### 9. Extensibility for arbitrary agent-defined information

**What works**

- The HTTP boundary lets multiple agents share one service, and `owner_id`, `agent_id`, scope, type, and raw session metadata exist from the start.
- Direct writes allow agents to bypass extraction for explicit memories.
- The separate task-board table demonstrates that specialized lifecycle metadata can coexist without corrupting memory recency ([02-data-model.md:60](/Users/mlutfullaev/dev/indie/mem-os/docs/02-data-model.md:60)).

**What is missing or risky**

- The ontology is fixed to seven memory types and three scopes at API, schema, prompt, provider, retrieval, dashboard, and tests ([api.py:36](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/api.py:36), [providers.py:39](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/providers.py:39)). Adding an agent-defined kind is a cross-cutting release, not configuration.
- Memories have no free-form metadata/tags, custom namespace, JSON value, schema ID, relation edge, or application-defined decay/importance policy.
- Only conversational `user`/`assistant` messages are accepted; there is no generic event, observation, tool artifact, document, or structured-state ingest contract.
- Task support is a bespoke vertical feature. It proves extension is possible, but also illustrates the cost: new table, routes, retrieval payload, migration, UI, and extensive tests.
- The architecture intentionally excludes documents/code from memory ([01-architecture.md:77](/Users/mlutfullaev/dev/indie/mem-os/docs/01-architecture.md:77)). That boundary is sensible for quality, but means arbitrary agent knowledge requires another service today.

Recommended abstraction: keep durable personal memory strict, but add configurable **containers** with a declared purpose, allowed writers, extraction prompt/policy, metadata schema, retrieval policy, and retention. Do not collapse documents and personal facts into one untyped collection.

### 10. Eval design

**What works**

- Four layers separate observability, deterministic plumbing, paid extraction quality, retrieval quality, and long-run health ([08-testing.md:20](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:20)).
- The extraction golden set scores leaks, recall, false positives, scope, importance, operation correctness, and over-emission; negative cases are first-class ([golden.py:10](/Users/mlutfullaev/dev/indie/mem-os/eval/golden.py:10), [golden.py:115](/Users/mlutfullaev/dev/indie/mem-os/eval/golden.py:115)).
- Retrieval assertions use content regexes rather than unstable IDs ([run.py:1](/Users/mlutfullaev/dev/indie/mem-os/eval/run.py:1)).
- Raw-vs-memory comparison uses exactly the shared answerable set; the harness explicitly prevents the previous mismatched-case error ([run.py:260](/Users/mlutfullaev/dev/indie/mem-os/eval/run.py:260)).
- MRR, top-1, reject violations, mean/max tokens, and MRR/token provide a better view than recall alone ([run.py:293](/Users/mlutfullaev/dev/indie/mem-os/eval/run.py:293)).
- The docs candidly state that the 21-case golden set has topped out as a discriminator ([08-testing.md:102](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:102)).

**What is missing or risky**

- The extraction golden set has only 5/21 empty-expectation cases against its own 50% target ([08-testing.md:90](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:90)).
- Retrieval has zero cases for stale/forgotten facts, irrelevant queries, degenerate queries, and many-relevant-fact adaptivity ([08-testing.md:132](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:132)).
- There is no end-to-end measure of whether injected memory improves the final agent answer, nor a penalty for irrelevant facts that do not match a small reject list.
- No benchmark covers knowledge updates, temporal questions, multi-hop/entity reasoning, conflicting sources, assistant-origin poisoning, or correction latency.
- Results are one author's small live corpus. There are no confidence intervals, repeated retrieval runs, corpus-size sweeps, or held-out users/projects.
- Long-run metrics are prescribed but manual; no CI or scheduled quality gate exists ([08-testing.md:159](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:159), [08-testing.md:209](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:209)).
- Provider parsers lack realistic recorded-response tests, and CLI/web coverage is thin ([08-testing.md:213](/Users/mlutfullaev/dev/indie/mem-os/docs/08-testing.md:213)).

Minimum next eval pack: 10 no-memory queries, 5 stale/superseded/expired cases, 5 cross-project collisions, 5 corrections, 5 assistant-poisoning cases, 5 exact-term cases, 5 multi-fact/profile queries, and a 10k synthetic distractor sweep. Gate on false injection, current-fact accuracy, cross-scope leakage, MRR/token, and p95 latency.

### 11. Developer/API ergonomics

**What works**

- The API is compact, authenticated, bounded by Pydantic, and documented through generated route/schema contracts ([03-api.md:6](/Users/mlutfullaev/dev/indie/mem-os/docs/03-api.md:6)).
- External IDs make ingest idempotent ([store.py:26](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/store.py:26)).
- Search returns component scores, tokens, and latency; admin preview explains drops.
- Dry-run-first re-extraction/consolidation, cost estimates, reversible soft deletes, bulk safety caps, optimistic locks, health/index drift, and reindex are excellent operator features.
- The Hermes adapter handles caching, circuit breaking, secret scrubbing, read-only subagent/cron contexts, backup declaration, and explicit remember/search tools ([07-hermes-adapter.md:50](/Users/mlutfullaev/dev/indie/mem-os/docs/07-hermes-adapter.md:50)).

**What is missing or risky**

- There is no public SDK; the only client is integration-specific stdlib `urllib` ([client.py:55](/Users/mlutfullaev/dev/indie/mem-os/integrations/hermes/memkit/client.py:55)).
- Several endpoints return untyped dictionaries, weakening OpenAPI response contracts and generated clients.
- `extraction_queued` has no job ID, status, retry count, or completion endpoint. Operators must infer success from judge runs/backlog.
- `scope_key` is “required in practice” but optional in schema; omission silently hides project facts ([03-api.md:82](/Users/mlutfullaev/dev/indie/mem-os/docs/03-api.md:82)).
- `agent_id` is accepted but ignored; `scope_key` and `project` overlap; `budget_tokens=0` means unlimited internally. These are learnability hazards.
- API-key default is insecure (`change-me`) and becomes dangerous if bind address changes ([config.py:11](/Users/mlutfullaev/dev/indie/mem-os/src/memkit/config.py:11)).
- Python is pinned to 3.12 and installation requires Docker/Qdrant plus a large local embedding model ([pyproject.toml:1](/Users/mlutfullaev/dev/indie/mem-os/pyproject.toml:1)). This is reasonable for the chosen hardware but a high adoption floor.

## Current workspace observations (not source-controlled claims)

These figures came from read-only aggregate SQL against `data/memkit.db` on 2026-08-09. They should not be confused with the dated, source-controlled 2026-07-31 snapshot in [measurements.md:33](/Users/mlutfullaev/dev/indie/mem-os/docs/measurements.md:33).

| Observation | Current value | Product implication |
|---|---:|---|
| Messages / sessions / unprocessed | 4,294 / 92 / 15 | Small live corpus; two sessions have pending tails. |
| Memories | 97 active, 1 expired, 2 superseded | Consolidation/correction history is still very small. |
| Active scope | 60 project, 37 user | Most memory remains unavailable without project context. |
| Active versions | 60 v4, 16 v1, 8 v2, 11 manual, 1 v6, 1 consolidated | Production data mostly predates the active v6 policy. |
| Active source roles | 87 user, 10 manual, 0 assistant | Good current label count, but retrospective manual labels are known to be blind. |
| Length | avg 193 chars; 18 >200; max 2,161 | Prompt cap is not an invariant; legacy facts consume/skew budgets. |
| Retrieval | 51/97 never retrieved | Half the store has no observed retrieval utility yet. |
| Extract judge | 253 calls, 1 error; avg ~2,990 in / 90 out tokens; avg ~1.7 s | Cost is low, but model calls are long relative to SQLite write locking. |
| Active already past `valid_until` | 0 | No current expiry leak, though architecture permits one if scheduling fails. |

The current data reinforces two priorities: fix scope/provenance semantics first, then replay/relabel the legacy store. Replaying before those fixes risks faithfully regenerating the same classes of defect.

## External comparison: current Mem0 and Supermemory concepts

This section is **external observation**, not evidence about this repository. Sources were accessed on 2026-08-09 and are official project repositories/docs. Vendor benchmark claims are self-reported and are not treated as independently verified.

### Mem0 (current open-source repository)

The current Mem0 repository presents a substantially broader extension and retrieval surface: user/agent/run scopes, arbitrary metadata, raw-vs-inferred adds, expiration, a procedural-memory type, custom prompts, thresholded search, history, filters, multiple vector/LLM/embedder providers, and self-hosted server/SDK/CLI options. See its [current core API reference](https://github.com/mem0ai/mem0/blob/main/LLM.md) and [open-source implementation](https://github.com/mem0ai/mem0/blob/main/mem0/memory/main.py).

Its April 2026 README describes a new algorithm built around ADD-only accumulation, first-class agent-generated facts, entity linking, semantic+BM25+entity fusion, and temporal retrieval. It explicitly warns that reported managed-platform benchmark results include proprietary optimizations and are not identical to OSS behavior ([Mem0 README](https://github.com/mem0ai/mem0#new-memory-algorithm-april-2026)).

Conceptual comparison:

| Concept | memkit | Current Mem0 OSS direction |
|---|---|---|
| Trust/provenance | Source messages, roles, judge runs, soft history; strongest area | Broader roles/entities, but current README gives agent-generated facts equal weight. memkit's distrust of model self-assertion is the safer principle if enforcement is completed. |
| Correction | Explicit UPDATE/DELETE and supersession/replay | README direction is ADD-only plus temporal/entity-aware retrieval; source API still exposes update/delete/history. |
| Retrieval | Dense + importance/recency/scope; no floor | Hybrid semantic/BM25/entity concepts and thresholded search surface. |
| Extensibility | Fixed types/scopes, no custom metadata | Free-form metadata, user/agent/run filters, provider configuration, procedural memory, custom prompt. |
| Ergonomics | Local service + CLI + one Hermes adapter | Python/TypeScript OSS APIs, server, CLI, integrations, skills. |
| Auditability | Rich exact source-message provenance | History API exists, but memkit's raw-message and judge-run linkage is more explicit in the inspected surface. |

What to borrow: generic metadata/filters, SDK shape, threshold option, provider interfaces, hybrid/entity candidate generation, and reproducible public benchmarks. What **not** to copy uncritically: equal-weight agent-authored facts or managed benchmark numbers as proof of OSS behavior.

### Supermemory (current public repository and official docs)

Supermemory's public repository describes a locally runnable memory/context engine plus hosted APIs. Its public concepts combine documents/RAG, extracted memories, graph relationships, profiles, connectors, multimodal ingestion, and hybrid search ([Supermemory repository](https://github.com/supermemoryai/supermemory)). Official docs distinguish source documents from extracted memories and model memory edges as `updates`, `extends`, and `derives`, with latest-state retrieval and forgetting ([graph memory docs](https://supermemory.ai/docs/concepts/graph-memory)).

Its profile API separates static and dynamic context, can search in the same call, and supports configurable topical “buckets” with classifier-guiding descriptions ([quickstart](https://supermemory.ai/docs/quickstart), [profile buckets](https://supermemory.ai/docs/user-profiles/buckets)). Search also exposes a relevance `threshold` in the official quickstart. The public README reports hybrid memory+document retrieval and self-reported benchmark/token figures; OSS/local parity for every hosted feature should be verified before treating those as implementation guarantees.

Conceptual comparison:

| Concept | memkit | Current Supermemory direction |
|---|---|---|
| Memory vs documents | Strictly separated; documents deliberately excluded | One API/context layer, but documents and extracted memories remain distinct retrieval concepts. |
| Personalization | Query-time fact retrieval only | Maintained static/dynamic profiles and configurable buckets. |
| Correction | UPDATE/DELETE + supersession | Graph `updates`, `extends`, `derives`, latest-state fields, and forgetting. |
| Retrieval | Dense facts, optional raw baseline | Hybrid memory/document modes, related-memory traversal, threshold. |
| Arbitrary information | Fixed ontology | Container tags, arbitrary metadata, custom profile buckets, documents/connectors/multimodal sources. |
| Provenance | Exact messages and judge runs | Parent/child memory relations and source documents; memkit's inspected local lineage is simpler and more explicit. |

What to borrow: an always-on compact profile, configurable buckets/containers, explicit update/extend semantics, thresholded retrieval, and standardized memory benchmarks. Preserve memkit's separation of personal memory from document RAG unless a unified API can keep their ranking/lifecycle policies distinct.

## Final assessment

memkit's best ideas are worth keeping: SQLite truth with rebuildable vectors, append-only evidence, source inspection, local reads, scope filtering before ranking, prompt/version replay, dry-run-first destructive work, and unusually honest eval documentation.

The next milestone should not be “more features.” It should be a **memory truth milestone**:

1. per-operation evidence and read-path trust policy;
2. scope-safe candidate updates and consolidation;
3. hard expiry plus calibrated silence;
4. correction/poisoning/cross-scope evals;
5. only then, replay the legacy store.

After that, hybrid retrieval, profiles, configurable containers/metadata, SDKs, and scale work can turn a strong personal system into a credible general agent-memory platform.
