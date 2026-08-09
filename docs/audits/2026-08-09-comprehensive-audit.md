# Mem OS comprehensive audit

**Date:** 2026-08-09  
**Repository:** `/Users/mlutfullaev/Dev/indie/mem-os`  
**Revision:** `0fad59dcaf4f979062552a37a52508261a1c8f73` (`master`)  
**Purpose:** audit the Mem OS / Life OS boundary, engineering quality, memory quality, missing capabilities, and direction relative to Mem0 and Supermemory.

## Executive verdict

Memkit is already a serious local personal-memory system. It has several unusually strong foundations: SQLite as the source of truth, rebuildable Qdrant indexes, detailed provenance, versioned extraction prompts, replay/re-extraction, explainable retrieval, low-token context assembly, and honest measurement documentation.

It is not yet a safe domain-agnostic memory platform.

Two independent problems must be fixed before expansion:

1. **The product boundary is wrong.** Memkit owns a complete task/Kanban product. Task state, ordering, project assignment, due-like behavior, LLM workflow inference, routes, UI, docs, and tests belong to Life OS/Hermes.
2. **Several source-of-truth guarantees are broken.** Confirmed failure tests showed SQLite/Qdrant split-brain, unrepaired raw-index failures, a reindex that can silently retain stale points, and a cost ceiling that can be exceeded.

The next milestone should be **Memory Truth + Boundary Separation**, not another feature wave.

Core principle:

> **Mem OS provides domain-neutral memory and record capabilities. Life OS provides personal meaning and behavior.**

Life OS may physically persist task records through a generic Mem OS collection. Mem OS must not know what a task means, what statuses are legal, when it is overdue, or how task transitions work.

## Audit artifacts

- [Boundary audit](./2026-08-09-boundary-audit.md)
- [Engineering audit](./2026-08-09-engineering-audit.md)
- [Product and memory-quality audit](./2026-08-09-product-memory-audit.md)

These appendices contain exact file/line references, reproduction output, detailed findings, and full migration inventories.

---

## 1. Correct architectural boundary

### Mem OS owns

- Raw evidence/events and immutable source identity.
- Semantic memory claims.
- Provenance, confidence, validity, history, and corrections.
- Generic namespaces, collections, schemas, records, metadata, and links.
- Embedding and derived indexes.
- Generic filter execution, ranking, reranking, budgeting, and explanations.
- Generic extraction/consolidation infrastructure and versioned policies.
- Storage/index reconciliation, retention, export, and deletion primitives.

### Life OS/Hermes owns

- Tasks, reminders, goals, habits, routines, projects, and personal workflows.
- Task status, due date, priority, ordering, recurrence, snooze, completion, and transitions.
- Personal-domain schemas and policies.
- Domain prompts that propose personal actions.
- Validation and application of domain commands.
- Task/reminder/workflow APIs and UI.
- Proactive behavior and orchestration.

### Physical storage does not determine authority

A valid design is:

```text
Life OS defines collection "life.tasks" and its schema
        ↓
Life OS validates task commands and transitions
        ↓
Mem OS stores generic records for collection "life.tasks"
        ↓
Mem OS indexes, filters, versions, audits, and retrieves records
```

Mem OS sees an opaque collection and schema. Life OS sees tasks.

---

## 2. Boundary violations found

The task subsystem is not an isolated endpoint. It crosses every major layer.

### Critical violations

1. **Authoritative task aggregate in core storage**
   - `task_board` table, workflow state, project grouping, ordering, optimistic versioning, migration, and backfill are in `src/memkit/db.py:120-133,165-176,239-316`.
   - Full task domain module and routes are in `src/memkit/taskboard.py:1-484`.

2. **The memory judge mutates task workflow**
   - Prompts ask the LLM to infer `todo/doing/done` in `src/memkit/prompts.py:40-46`.
   - Provider schemas expose `task_status` in `src/memkit/providers.py:83-198`.
   - Extraction and re-extraction create or mutate board state in `src/memkit/extract.py:309-405` and `src/memkit/reextract.py:195-268`.
   - Replaying historical extraction can therefore change current operational state.

3. **Memory validity is used as task due-date state**
   - Memkit correctly interprets `valid_until` as the end of a claim's validity.
   - The task UI renders the same field as a due date in `web/src/routes/Tasks.tsx:558-584,653-749`.
   - An overdue unfinished task can be expired by generic memory consolidation.

### High violations

4. Closed `type` and `scope` vocabularies include `task` and `project` across Python, provider schemas, TypeScript, docs, and tests.
5. Search contracts expose `project`, `task_key`, `scope_key`, and `task_status` as infrastructure concepts.
6. Retrieval hard-codes task decay at two days and task/project scope boosts in `src/memkit/retrieval.py:33-52,160-248`.
7. Qdrant payload/index definitions contain `project` and `task_status` in `src/memkit/vectors.py:32-42`.
8. Generic memory creation/mutation has implicit task-board side effects in `src/memkit/store.py:250-420` and `src/memkit/mutate.py:106-253`.
9. The memkit dashboard ships an 877-line task-management product in `web/src/routes/Tasks.tsx`.
10. The Hermes adapter mirrors the closed task vocabulary rather than translating a Life OS-owned model.

### Structural inconsistency caused by the coupling

The same concept is represented by five overlapping fields:

- `type="task"`
- `scope="task"`
- `task_key`
- `project_key/project`
- `task_status`

Task creation does not use task scope; task-scope extraction lacks real task IDs; unkeyed task memories can remain globally visible; the Hermes client cannot express the core's `task_key`; changing a task memory to another type leaves stale task-board/Qdrant state.

This is evidence that task identity does not belong in the memory model.

---

## 3. Confirmed engineering defects

The engineering audit used temporary databases, stub providers/embedders/Qdrant, and clean Git archives. These are reproduced defects, not speculative risks.

### P0 — source-of-truth and reliability

#### E1. Qdrant receives uncommitted memory revisions — High

`store.add_memory` and extraction paths mutate Qdrant before the caller commits SQLite.

Observed forced rollback:

```json
{"sqlite_memories": 0, "qdrant_points": 1}
```

A retrievable vector can exist for a memory that does not exist in SQLite. UPDATE and DELETE can split in the opposite semantic directions.

**Fix:** every write produces a durable SQLite `index_outbox` operation in the same transaction. Workers apply idempotent Qdrant changes after commit. Track lag, retries, and terminal failures.

#### E2. A committed message can remain permanently absent from raw search — High

`POST /v1/messages` commits SQLite, then indexes Qdrant. If indexing fails, an idempotent retry returns `deduplicated=true` before retrying the index.

Observed:

```json
{
  "sqlite_messages": 1,
  "retry_status": 201,
  "retry_deduplicated": true,
  "raw_qdrant_points": 0,
  "index_dirty": false
}
```

**Fix:** use the same outbox and report `stored` separately from `indexed`.

#### E3. Reindex can silently preserve stale points — High

`vectors.drop_collection` catches every exception. Reindex then upserts active rows, reports success, and clears `index_dirty` without proving stale points were removed.

Observed:

```json
{"reported_memories": 1, "sqlite_active": 1, "qdrant_points_after": 2, "stale_point_survived": true}
```

**Fix:** generation-named collections, validated counts/IDs, then atomic alias swap. Never swallow unexpected delete errors.

#### E4. The monthly cost ceiling is not hard — High

The code checks only already-recorded spend before making a call. It does not reserve expected maximum cost.

Observed:

```json
{"limit": 0.000001, "call_cost": 0.0003, "month_spend": 0.0003, "error": null}
```

**Fix:** atomic budget reservations shared by extraction, re-extraction, and consolidation; reconcile reservations to actual cost after calls.

#### E5. Cloud extraction holds SQLite's writer slot — High

Extraction opens a write transaction before the provider call. A simulated 11-second judge caused an unrelated write to wait 11.24 seconds.

**Fix:** short transaction to claim/lease a window, remote work outside the transaction, short conditional transaction to apply results.

#### E6. Reindex write barrier misses important writers — High

Task writes, messages, session close, background extraction, and other processes can write during reindex. A task create returned 201 during a running reindex.

**Fix:** shared durable maintenance lease or, preferably, generation rebuild plus outbox replay and alias swap.

#### E7. Bulk mutation bypasses declared validation — High

`BulkIn.value` is `Any`; shared mutation code does not validate type/scope/ranges. A request stored `type="not-a-memory-type"` with HTTP 200.

**Fix:** discriminated strict request models, shared domain validation, `extra="forbid"`, and SQLite CHECK constraints.

#### E8. Extraction can mutate another owner's memory — High

Judge UPDATE and DELETE resolve candidate IDs using only `id` and `status='active'` in `src/memkit/extract.py:357-367,407-414`. They do not require the current `owner_id`. Session creation also accepts an existing session ID without validating its stored owner/agent in `src/memkit/db.py:327-338`.

An independent temporary-database probe showed an owner-A extraction changing an owner-B memory. Another probe showed an owner-B message submitted to an owner-A session being stored under owner A.

**Fix:** bind every lookup and mutation to authenticated tenant/namespace ownership. Reject session-ID reuse with mismatched owner or agent. Derive extraction identity from the persisted session rather than caller input.

#### E9. Raw user secrets can be sent to cloud judges — High

The Hermes adapter scrubs credentials, but the Claude importer preserves ordinary user text unchanged (`src/memkit/importers/claude_code.py:112-127,159-189`). Judge rendering includes full user turns, and Gemini/Anthropic receive the resulting prompt. The generic `/v1/messages` path also lacks server-side redaction.

The instruction “never store credentials” only governs model output. It does not stop the provider from receiving the secret.

**Fix:** centralize configurable redaction immediately before every persistence and cloud-egress boundary; retain a local-only mode; record that redaction occurred without logging the removed value.

### P1 — correctness, release, and API quality

8. **Expired claims remain searchable until consolidation runs.** `valid_until` is not in Qdrant payloads or read filters.
9. **Cross-owner session close can extract under the wrong owner.** Owner is taken from the caller rather than the persisted session.
10. **Filtered session pagination reports the wrong total.** Item filtering and count filtering differ.
11. **Blank and unbounded content is accepted.** Whitespace memory creation returned 201 and stored three characters.
12. **Clean wheel omits the dashboard and Hermes plugin.** A clean-archive wheel had zero `web_dist` files and zero Hermes integration files; `memkit install-hermes` failed.
13. **Frontend lint is nonfunctional.** ESLint 9 has no `eslint.config.*`.
14. **OpenAPI TypeScript schema is an empty placeholder and unused.** Client types can drift silently.
15. **Operations UI says implemented re-extraction and consolidation APIs do not exist.**
16. **Anthropic can silently mark a window processed without structured output.** A non-refusal response lacking the required tool block returns `operations=[]` and no error, after which extraction marks the window processed.
17. **The sdist can include unrelated untracked workspace files.** An independent clean build found `.idea` content and the machine-specific untracked service plist in the source archive.

### P2 — security/privacy and operational hardening

18. One static API key can select arbitrary `owner_id`; partitions are not authorization boundaries.
19. API-key default is `change-me`; safe only while strict loopback binding remains intact.
20. Raw messages are intentionally retained forever; there is no first-class owner export/erase/retention workflow.
21. `/healthz` exposes detailed paths/counts and can return HTTP 200 while required dependencies are degraded.
22. Qdrant uses the floating `latest` image tag.
23. No CI workflow exists.
24. Deployment files and README disagree; one service plist is untracked and logs have no rotation.
25. The browser stores the admin API key in `localStorage`, so any future XSS would gain full service access.

---

## 4. Memory-quality findings

### Highest-risk quality defects

1. **Per-fact evidence is not precise.** Every extracted operation cites the entire window. One user turn can make assistant-derived claims appear user-sourced.
2. **Assistant-authored memories are labeled but not treated differently during retrieval.** `source_role` is absent from vector payload/ranking.
3. **Correction candidates are owner-wide and scope-unsafe.** Candidate output omits scope fields; UPDATE ignores returned scope.
4. **Consolidation can merge across scopes/projects.** It clusters by owner and type and inherits the newest fact's scope.
5. **Retrieval cannot intentionally stay silent.** It returns the best available memories without a calibrated relevance floor or false-injection policy.
6. **Dense-only retrieval misses exact terms.** BM25 is reserved in Qdrant but unused.
7. **Confidence is collected but not used or calibrated.**
8. **The 200-character rule is prompt-only.** The live store has legacy overlong facts.
9. **There is no stable/dynamic profile.** Query-only retrieval can omit identity and standing preferences on semantically unrelated turns.
10. **Current production data mostly predates the active extraction policy.** Do not replay it until provenance/scope/expiry correctness is fixed.

### Required memory-truth work

- Per-operation source message IDs and exact evidence spans.
- Read-path trust policy using provenance/source role.
- Scope-safe correction and consolidation.
- Hard read-path expiry.
- Relevance silence/threshold calibrated against false injection.
- Cross-scope, correction, poisoning, temporal, and long-run evals.
- Only then: dry-run, review, and replay/relabel legacy memory.

---

## 5. What is working right and should be preserved

1. **SQLite truth + rebuildable vector index** is the correct recoverability model.
2. **Detailed provenance and source inspection** are stronger than most competing systems.
3. **Idempotent message ingestion** is a good base for replay.
4. **Versioned prompts, logged judge runs, and re-extraction** enable real experimentation.
5. **Explainable ranking** exposes similarity, importance, recency, scope, dedup, and budget decisions.
6. **Local embedding/search latency** is strong for a personal system.
7. **Low-token retrieval** is proven useful: current eval produced 421 mean memory tokens versus 1,674 raw tokens, with much higher MRR per 1k tokens.
8. **Hermes adapter resilience** is thoughtful: warmup, cache fallback, circuit breaker, primary-context write restriction, secret scrubbing, and backup declaration.
9. **Dry-run and reversible maintenance patterns** are good product safety principles.
10. **Documentation contracts and migration tests** show unusually disciplined engineering.
11. **Task code is modular enough to move.** Preserve its optimistic locking and ordering quality in Life OS.

---

## 6. Tests and measurements run

### Local project tests

| Check | Result |
|---|---|
| Backend `unittest` | **399 passed** |
| Coverage run | **89% total** including tests; weakest production modules were embed 28%, providers 50%, consolidate 65%, and store 68% |
| Frontend Vitest | **6 passed** in 2 files |
| TypeScript typecheck | **Passed** |
| Frontend production build | **Passed**, but Node 20.12.1 is below Vite's supported 20.19+ floor |
| Wheel/sdist build in current checkout | **Passed** |
| Clean-archive wheel feature test | **Failed:** dashboard and Hermes plugin absent |
| Generated documentation blocks | **8/8 matched** |
| Ruff | **Failed:** 69 findings; 49 automatically fixable |
| ESLint | **Failed:** no flat config |
| Python dependency audit | **2 known vulnerabilities:** `cryptography 49.0.0`, `h2 4.4.0` |
| pnpm audit | **8 high findings** across build/development dependency graph |

Python fixes currently available:

- `cryptography` → `50.0.0`
- `h2` → `4.4.1`

The frontend advisories are primarily build/development supply-chain risk because the shipped UI is static, but they should still be upgraded and locked.

### Live/local retrieval measurements

- Qdrant was initially stopped while the API process remained alive.
- After starting Qdrant, health showed 97 active memory vectors and 319 raw vectors.
- Embedding benchmark: **49.6 ms median on MPS**.
- Retrieval comparison on 31 shared cases:
  - Raw: recall@10 0.90, MRR 0.790, mean 1,674 tokens.
  - Memories: recall@10 0.84, MRR 0.725, mean 421 tokens.
  - MRR/1k tokens: raw 0.472, memories 1.720.

Memory retrieval is substantially more token-efficient but still loses some recall. The right response is hybrid candidate generation and better evals—not simply increasing context size.

### Paid Gemini extraction eval

Ran the project's 21-case golden set with `gemini-3.5-flash-lite:v6`:

- Recall: **16/18 = 89%**
- False positives: **0**
- Credential leaks: **0**
- Correct scope: **12/13**
- Correct importance: **2/2**
- Correct operation: **1/1**
- Cost: **$0.0170**
- Failures: one mixed user/project miss; one incorrect scope; one second-fact miss.

This is good extraction quality for the small set, but the set is not yet sufficient for temporal truth, correction, poisoning, silence, or scale claims.

### Independent agents

Three parallel Codex audit passes covered:

- Mem OS/Life OS boundary.
- Engineering/security/reliability/package failure injection.
- Product, memory quality, and competitor direction.

Their detailed reports are preserved as the three appendices linked above.

A separate three-agent validation pass independently confirmed the boundary verdict, SQLite/Qdrant split-brain, incomplete reindex exclusion, stale-point risk, packaging gaps, and competitor direction. It additionally found the cross-owner UPDATE/DELETE defect, raw-secret cloud egress, and Anthropic's silent empty-extraction path. Those findings were checked against the current source and incorporated above.

---

## 7. Competitor comparison

Sources were inspected at current commits on 2026-08-09:

- Mem0: `4debc58a8337`
- Supermemory: `2731de5c06c3`

Vendor benchmark claims were not treated as independent proof.

Supermemory qualification: the inspected MIT repository contains documentation, clients, plugins, MCP, UI, and graph visualization, but not the hosted backend/embedded graph-engine implementation. Its product behavior can be compared from documented contracts; most core-engine implementation claims cannot be source-audited from that repository.

| Capability | memkit now | Mem0 direction | Supermemory direction |
|---|---|---|---|
| Source-of-truth provenance | Strong exact source/judge lineage | Broader platform, less explicit in inspected surface | Source documents and graph lineage |
| Namespacing | Fixed owner/project/task model | user/agent/run + metadata filters | Opaque container tags as isolation boundary |
| Custom information model | Closed type/scope enums | Free-form metadata, custom prompts/providers | Metadata, container settings, configurable profile buckets |
| Retrieval | Dense + importance/recency/scope | Semantic + BM25 + entity + temporal concepts | Hybrid memories/documents, rerank, rewrite, thresholds |
| Profiles | None | Memory retrieval centric | Static/dynamic profiles + custom buckets |
| Correction/history | UPDATE/DELETE/supersession/replay | Update/delete/history; current OSS direction also emphasizes additive memory | Versioned update, forget, update/extend/derive graph semantics |
| Providers | Gemini/Anthropic, fixed embedding/Qdrant | Pluggable LLM/embedder/vector/reranker | Managed and self-host configuration |
| SDKs | Hermes-specific client only | Python/TypeScript/server/CLI | Python/TypeScript/SDKs/connectors |
| Local simplicity | Strong | Broader and more complex | Much broader product surface |
| Domain neutrality | Currently violated by tasks | Generic metadata but opinionated IDs | Opaque containers, but broader hosted application concepts |

### Borrow from Mem0

- Pluggable provider interfaces.
- Generic metadata and filter algebra.
- Typed Python/TypeScript SDKs.
- Thresholded and hybrid retrieval.
- Entity candidate generation.
- History and expiration APIs.
- Public standardized benchmark discipline.

### Borrow from Supermemory

- Opaque container tags/namespaces.
- Per-container extraction context and policy.
- Configurable profile buckets.
- Static/dynamic compact profiles.
- Explicit update/extend/derive semantics.
- Queued ingestion and operation status.
- Hybrid memory/document API concepts while keeping their stores and policies distinct.
- Scoped API keys bound to containers.

### Do not copy blindly

- Do not expand into every connector/document/RAG feature before memory truth is correct.
- Do not hide OSS limitations behind managed-platform benchmark claims.
- Do not inherit Mem0's rapidly growing central implementation complexity.
- Do not turn configurable buckets into another closed domain ontology.
- Do not give agent-authored assertions the same trust as direct user evidence.
- Do not merge document RAG and personal memory into one lifecycle/ranking model.

### The right middle ground

Memkit should be:

> **A local-first, provenance-first, low-token memory and generic-record substrate with flexible namespaces/schemas, pluggable policies, excellent reconciliation, and tight Hermes integration—without becoming a monolithic document platform or a personal productivity application.**

That is a differentiated position, not a smaller clone of either competitor.

---

## 8. Recommended target architecture

```text
Applications / agents
  ├─ Life OS / Hermes
  ├─ coding agents
  ├─ other apps/providers
  └─ future integrations
          ↓
Mem OS API and SDK
  ├─ Evidence API
  ├─ Semantic Memory API
  ├─ Generic Collections/Records API
  ├─ Search/Profile API
  ├─ Policy/Schema Registry
  └─ Export/Erase/History API
          ↓
Authoritative SQLite/Postgres layer
  ├─ evidence/events
  ├─ claims + revisions + provenance
  ├─ namespaces/collections/schemas/records
  ├─ links/edges
  ├─ job leases + cost reservations
  └─ index outbox
          ↓
Derived retrieval layer
  ├─ dense vectors
  ├─ BM25/sparse vectors
  ├─ entity index
  ├─ profiles/summaries
  └─ generation-based indexes + reconciliation
```

### Three data planes

1. **Evidence plane** — raw messages/events/doc references with provenance and retention.
2. **Memory plane** — extracted semantic claims with temporal truth, confidence, correction, and trust.
3. **Record plane** — arbitrary agent-defined structured records such as `life.tasks`, without domain semantics in core.

Do not force arbitrary structured application data into semantic memory facts.

### Minimal generic API direction

```text
POST   /v1/namespaces
POST   /v1/collections
GET    /v1/collections/{name}
POST   /v1/collections/{name}/records
PATCH  /v1/collections/{name}/records/{id}
DELETE /v1/collections/{name}/records/{id}
POST   /v1/collections/{name}/search
POST   /v1/evidence/events
POST   /v1/memories
POST   /v1/memories/search
GET    /v1/memories/{id}/history
POST   /v1/profiles/render
POST   /v1/export
POST   /v1/erase
GET    /v1/jobs/{id}
```

A collection definition should support:

- Namespace and opaque name.
- JSON Schema or equivalent validated record schema.
- Indexed fields and embedding fields.
- Metadata/filter operators.
- Retention and revision policy.
- Allowed writers/readers.
- Optional extraction/consolidation policy ID.
- Optional retrieval profile ID.
- Idempotency key strategy.

### Retrieval design

- Dense + BM25 candidate arms.
- Optional entity arm.
- Generic filter AST.
- Caller-selected versioned ranking profile.
- Hard validity and trust filters.
- Calibrated relevance/silence policy.
- Tokenizer-aware budget.
- Explain output with candidate-arm and policy IDs.
- User feedback on usefulness/correctness, not only exposure counts.

---

## 9. Migration roadmap

### Phase 0 — freeze the boundary

- Add an ADR defining Mem OS versus Life OS ownership.
- Add architecture fitness tests forbidding task/workflow schemas, routes, prompt fields, and imports in core.
- Stop adding task/reminder/goal features to Mem OS.

### Phase 1 — repair memory truth

- Add durable index outbox.
- Move all Qdrant writes after SQLite commit.
- Repair raw-index retry behavior.
- Replace destructive reindex with generation + validation + alias swap.
- Add durable job leases and cost reservations.
- Enforce hard read-path expiry.
- Add strict shared validation and DB constraints.
- Remove cloud calls from write transactions.

**Gate:** failure-injection tests prove no SQLite/Qdrant split-brain and no budget overshoot.

### Phase 2 — create generic platform primitives

- Namespaces/container tags.
- Collections and versioned schemas.
- Generic records, metadata, links, and filter AST.
- Versioned retrieval/extraction policies.
- Python and TypeScript SDKs generated from real OpenAPI contracts.
- Scoped credentials/permissions.

**Gate:** a caller can create a new domain collection without changing memkit source code.

### Phase 3 — move task authority to Life OS

Current live migration footprint was verified read-only: schema version 3, 100 memories, five task memories, five matching `task_board` rows, all five tasks `done`, no orphan rows, and no task with `valid_until`. This is a small, internally consistent set whose IDs can be preserved exactly.

- Create `life.tasks` schema and Life OS task state machine.
- Give tasks Life OS IDs, statuses, project references, `due_at`, priority, ordering, and recurrence.
- Preserve optional references to Mem OS evidence/memory IDs.
- Disable LLM direct workflow mutation; LLM output becomes a proposed Life OS command.
- Migrate `task_board` rows.
- Interpret historical task `valid_until` as candidate `due_at`, not memory expiry.
- Move routes, UI, CSS, tests, and docs to Life OS.

**Gate:** re-extraction cannot mutate task state; no task vocabulary remains in Mem OS OpenAPI/schema/Qdrant.

### Phase 4 — improve memory quality

- Per-operation evidence citations.
- Read-path provenance/trust policy.
- Scope-safe correction/consolidation.
- Relevance silence.
- Hybrid retrieval and entity candidates.
- Stable/dynamic profile generation.
- Correction, poisoning, temporal, cross-scope, and 10k-distractor eval packs.

**Gate:** quality improves on held-out tests without increasing false injection or token cost beyond agreed limits.

### Phase 5 — repair and replay legacy data

- Dry-run re-extraction under corrected policies.
- Review diff and cost estimate.
- Preserve rollback/supersession.
- Rebuild derived indexes.
- Verify counts, IDs, provenance, scopes, expiry, and search quality.

Do not replay legacy data before Phases 1 and 4 establish safe semantics.

---

## 10. Immediate priority list

### Do now

1. Fix E1–E7 before trusting Mem OS as a source-of-truth service.
2. Codify the Mem OS/Life OS boundary.
3. Disable memory-extractor mutation of task workflow.
4. Split `valid_until` from Life OS `due_at`.
5. Design generic collections/schemas before moving task persistence.
6. Add failure-injection tests and CI.
7. Fix clean wheel packaging and dependency vulnerabilities.

### Do next

8. Move the task subsystem into Life OS through a compatibility adapter.
9. Add precise provenance and trust-aware retrieval.
10. Add hard expiry, retrieval silence, and scope-safe consolidation.
11. Add BM25/hybrid retrieval behind eval gates.
12. Add SDKs, profiles, scoped credentials, export/erase, and durable jobs.

### Defer

- Broad document connectors.
- Multimodal ingestion.
- Complex graph databases.
- Multi-region/enterprise scaling.
- More personal productivity domains inside Mem OS.

Those become useful only after the platform boundary and memory truth are dependable.

## Final conclusion

The project should not be rewritten. Its strongest infrastructure ideas are worth preserving.

The correct move is a deliberate extraction and hardening program:

1. make SQLite/Qdrant/cost/job invariants real;
2. make memory truth and provenance safe;
3. introduce generic collections, schemas, filters, and policies;
4. move tasks and all personal workflow semantics into Life OS;
5. then add the best ideas from Mem0 and Supermemory without inheriting their complexity or product scope.

The differentiator should be **trustworthy, local, low-token, domain-neutral memory infrastructure deeply integrated with Hermes**, with Life OS as the personalized intelligence built on top.
