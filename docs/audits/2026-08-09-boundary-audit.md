# Mem OS / memkit Architecture Boundary Audit

Date: 2026-08-09  
Repository: `/Users/mlutfullaev/dev/indie/mem-os`  
Mode: read-only static architecture audit

## Executive verdict

**The repository does not satisfy the primary invariant.** Memkit contains a reasonably strong local-memory engine, but it also owns a complete task/Kanban domain: task persistence, workflow states, ordering, due-date-like behavior, LLM task-state inference, task-aware retrieval, task HTTP APIs, a task UI, documentation, and tests. That ownership belongs in Life OS/Hermes.

This is not an isolated route or UI leak. Task semantics cross every important layer:

1. SQLite and Qdrant schemas.
2. Public and admin API contracts.
3. Python and TypeScript types.
4. Extractor prompts and provider schemas.
5. Mutation and consolidation behavior.
6. Retrieval filtering, boosting, and decay.
7. The shipped admin application.
8. Normative documentation and generated documentation contracts.
9. Unit, route, integration, migration, frontend, and evaluation tests.

The most dangerous consequence is semantic, not cosmetic: the task UI treats `valid_until` like a deadline, while memkit's generic consolidation treats it as the expiration of a memory's truth. An unfinished overdue task can therefore be expired or archived by memory maintenance.

No production goal, reminder, habit, calendar, or general personal-workflow aggregate was found. The current major violation is the first-class task subsystem and its project/coding-specific context model. The Claude importer strings `<task-notification>` and `<system-reminder>` are transport-noise classifiers, not Life OS task/reminder implementations (`src/memkit/importers/claude_code.py:37-59`). Likewise, `REMEMBER_RE` is an explicit memory-capture trigger, not reminder scheduling (`src/memkit/judge.py:102-108`).

## Boundary used for this audit

Memkit may own:

- durable content, source messages, evidence, provenance, and lifecycle state;
- embeddings and derived indexes;
- generic filtering and ranking machinery;
- generic validity intervals for claims;
- opaque caller-provided namespaces, labels, metadata, and policy parameters;
- extraction of domain-neutral durable claims, or execution of caller-supplied extraction policies.

Life OS/Hermes must own:

- task identity, status, due date, priority, ordering, project assignment, and transitions;
- reminders, schedules, goals, habits, and personal-workflow rules;
- domain prompts and model outputs that create or mutate those objects;
- domain-specific retrieval policy and context mapping;
- task/workflow APIs and UI;
- the authoritative database for those objects.

A generic memory may be evidence for, or be referenced by, a Life OS object. It must not silently become that object.

## Findings summary

| ID | Severity | Finding |
|---|---|---|
| B1 | Critical | Memkit owns the authoritative task aggregate and Kanban API. |
| B2 | Critical | Memkit's LLM extractor decides and mutates task workflow state. |
| B3 | Critical | Memory validity is conflated with task due dates. |
| B4 | High | Task and project semantics leak through all supposedly generic contracts. |
| B5 | High | Retrieval policy embeds task/project domain behavior. |
| B6 | High | `type`, `scope`, `project_key`, `task_key`, and `task_status` form an inconsistent domain model. |
| B7 | High | The memkit admin application is also a task-management product. |
| B8 | Medium | Hermes is correctly isolated as an adapter, but it mirrors rather than owns/translates the domain. |
| B9 | Medium | Normative documentation canonizes the violations and omits the governing boundary. |
| B10 | Medium | Tests and generated contracts harden the wrong ownership boundary. |
| B11 | Medium | Source-specific Claude/project assumptions create an inverted dependency in generic storage. |
| B12 | Medium | Domain coupling causes stale and asymmetric state during generic type mutation. |

## Detailed findings

### B1 — Memkit owns the authoritative task aggregate and Kanban API

**Severity: Critical**

The core database contains an authoritative `task_board` table with workflow status, project grouping, ordering, timestamps, and optimistic versioning (`src/memkit/db.py:120-133`). Schema initialization and migration explicitly preserve and backfill it (`src/memkit/db.py:165-176`, `src/memkit/db.py:239-316`). The core memory table's foreign-key migration is made more complex specifically to preserve task-board rows (`src/memkit/db.py:257-260`).

`src/memkit/taskboard.py` is a complete domain module, not generic metadata support:

- fixed workflow states and transitions: `src/memkit/taskboard.py:17-24`;
- task metadata creation and repair: `src/memkit/taskboard.py:45-87`;
- model-inferred workflow mutation: `src/memkit/taskboard.py:90-123`;
- board projection grouped by project: `src/memkit/taskboard.py:133-198`;
- domain create/patch DTOs: `src/memkit/taskboard.py:201-246`;
- anchor-based ordering and rebalancing: `src/memkit/taskboard.py:249-335`;
- vector payload synchronization: `src/memkit/taskboard.py:338-351`;
- board, create-task, and patch-task endpoints: `src/memkit/taskboard.py:354-484`.

The router is mounted by the main memkit application (`src/memkit/api.py:29`, `src/memkit/api.py:158-160`). The normative API table exposes `POST /v1/admin/tasks`, `GET /v1/admin/task-board`, and `PATCH /v1/admin/tasks/{memory_id}` as memkit routes (`docs/03-api.md:11-46`). The provenance/source response even reports task-board rows as part of the generic memory API (`src/memkit/api.py:304-381`, especially `src/memkit/api.py:363-375`).

Creating a task through this route creates a memory, assigns project/user scope, and writes the task aggregate in one core transaction (`src/memkit/taskboard.py:354-384`). Updating it coordinates memory and board locks and changes workflow/project/order inside memkit (`src/memkit/taskboard.py:387-483`).

**Why this violates the invariant:** status, board order, project assignment, and workflow version are Life OS state. Memkit should retain the underlying claim/event and evidence, while a Life OS task references its `memory_id` if useful.

**Required boundary:** move the table, migrations, routes, DTOs, transition rules, ordering logic, and vector-domain projection to Life OS/Hermes. Keep only a generic memory reference and generic metadata/filter capability in memkit.

### B2 — Memkit's LLM extractor decides and mutates task workflow state

**Severity: Critical**

The extractor prompt tells the model to assign `todo`, `doing`, or `done` (`src/memkit/prompts.py:40-46`). That rule is injected into active prompt versions (`src/memkit/prompts.py:616-670`, especially `src/memkit/prompts.py:643-648`). Task state is not merely observed as text; it is a structured model output.

Both structured-output provider schemas expose `task_status` and the closed task workflow vocabulary:

- Anthropic schema: `src/memkit/providers.py:83-134`, especially `src/memkit/providers.py:105-128`;
- Gemini schema: `src/memkit/providers.py:137-198`, especially `src/memkit/providers.py:169-193`.

The parsed operation contains `task_status` (`src/memkit/judge.py:148-164`), and the parser validates it against the domain workflow (`src/memkit/judge.py:166-223`). Candidate rendering also exposes the current task status to the judge (`src/memkit/judge.py:350-358`).

The extraction pipeline propagates status into candidate operations (`src/memkit/extract.py:205-267`), creates or updates the board row (`src/memkit/extract.py:309-343`, `src/memkit/extract.py:357-405`), and updates the vector payload. Re-extraction replays the same project/task-aware path (`src/memkit/reextract.py:195-268`). Thus changing a prompt or replaying an extraction can mutate operational workflow state.

This violates authority in two ways:

1. A probabilistic memory extractor becomes the task state machine.
2. Reprocessing historical memory can change current Life OS state.

The prompt itself is internally conflicted. It applies a durable “still useful in three months” test (`src/memkit/prompts.py:454-458`) while defining task scope as short-lived (`src/memkit/prompts.py:493-502`). The architecture guide similarly says memories should still matter in three months (`docs/01-architecture.md:77-88`), yet retrieval gives tasks a two-day half-life (`docs/05-retrieval.md:55-81`).

**Required boundary:** memkit may emit a generic extracted claim or immutable observation such as “the user said X,” with evidence. A Life OS-owned interpreter may propose a task command. Only the Life OS state machine may validate and apply task transitions. Re-extraction must never directly mutate live workflow state.

### B3 — Memory validity is conflated with task due dates

**Severity: Critical**

`valid_until` has a legitimate infrastructure meaning: after that time, the claim is no longer considered valid. Consolidation finds expired memories by that field (`src/memkit/consolidate.py:111-126`) and applies the expired/archive lifecycle (`src/memkit/consolidate.py:320-337`).

The task UI, however, renders the same value as a due date, marks it overdue when it is in the past, and exempts completed tasks from the overdue treatment (`web/src/routes/Tasks.tsx:558-584`). Its create/edit dialog exposes the same field in task workflow (`web/src/routes/Tasks.tsx:653-699`, `web/src/routes/Tasks.tsx:746-749`). Tests reinforce this by putting `valid_until` on a task named “Sprint goal” and expecting generic expiration behavior (`tests/test_consolidate.py:61-90`).

An overdue task remains an actionable task. An expired claim is no longer true/current. Treating these timestamps as one concept means nightly memory maintenance can remove an unfinished task from normal visibility precisely when it becomes overdue.

**Required boundary:** retain `valid_until` only for temporal truth in memkit. Life OS owns a separate `due_at`/`remind_at`, overdue rules, recurrence, snooze, and completion interaction. During migration, existing task `valid_until` values must be interpreted deliberately as due dates rather than blindly retained as memory expiry.

### B4 — Task and project semantics leak through generic contracts

**Severity: High**

The core closes both memory type and scope over domain values:

- API literals: `src/memkit/api.py:36-39`;
- provider constants: `src/memkit/providers.py:39-47`;
- direct memory input: `src/memkit/api.py:79-95`;
- admin patch input: `src/memkit/admin.py:176-188`.

The generic search contract has named `project`, `task_key`, and `scope_key` fields (`src/memkit/api.py:58-76`), and the handler translates them into task/project retrieval behavior (`src/memkit/api.py:384-424`). Admin search preview repeats the same domain context (`src/memkit/admin.py:788-826`). Search results return `task_status` as a first-class field (`src/memkit/retrieval.py:66-102`).

The persistence/indexing layer is similarly coupled:

- Qdrant indexes include `project` and `task_status`: `src/memkit/vectors.py:32-42`;
- generic `add_memory` accepts task status and creates a board row: `src/memkit/store.py:250-324`;
- vector upsert and full reindex join the task table: `src/memkit/store.py:333-420`;
- generic mutations ensure a task-board row: `src/memkit/mutate.py:106-145`, `src/memkit/mutate.py:225-246`.

The browser client mirrors these as fundamental types (`web/src/api/types.ts:1-54`) and constants (`web/src/lib/constants.ts:1-19`). Memory creation/filtering exposes user/project/task scope directly (`web/src/routes/Memories.tsx:147-190`, `web/src/routes/Memories.tsx:239-320`). Search Playground has named project/task context (`web/src/routes/SearchPlayground.tsx:50-100`). Analytics charts group by the same closed taxonomy (`web/src/components/AnalyticsCharts.tsx:15-30`, `web/src/components/AnalyticsCharts.tsx:176-254`).

The problem is broader than the word `task`: domain extensions require coordinated edits to Python literals, provider JSON schemas, SQL checks, vector indexes, UI unions, constants, documentation blocks, and tests. This is a closed application schema disguised as generic infrastructure.

**Required boundary:** use an opaque or registered `kind`/tag model and a generic context/filter representation. Memkit may offer stable built-in infrastructure classes where behavior truly differs, but caller-defined domain types must not require core releases.

### B5 — Retrieval policy embeds task/project domain behavior

**Severity: High**

Retrieval assigns hard-coded half-lives by semantic type, including a two-day task half-life (`src/memkit/retrieval.py:40-52`). Normative documentation explains that choice as product behavior (`docs/05-retrieval.md:55-81`). It also hard-codes scope weights (`src/memkit/retrieval.py:33-38`) and project/task boosts (`src/memkit/retrieval.py:160-185`).

The task policy is particularly unsafe: unkeyed task memories remain globally visible through the fallback branch (`src/memkit/retrieval.py:160-185`). Qdrant filtering independently encodes user/project/task cases (`src/memkit/retrieval.py:199-248`). Search and explain APIs accept named project/task context and apply the same logic (`src/memkit/retrieval.py:384-444`). The documentation makes the three named scopes normative (`docs/05-retrieval.md:83-106`).

Task recency, project isolation, current-goal activation, and completed-task visibility are domain policy. Different callers can reasonably choose different decay, completion, privacy, and context behavior. A single built-in formula prevents that and makes memkit unusable as neutral infrastructure for other domains.

**Required boundary:** memkit should execute a generic filter algebra and ranking profile supplied by the caller or registered policy. The profile can specify context matches, half-lives, boosts, lifecycle filters, and token budgets. Life OS selects task/project policy; memkit computes it and explains the score.

### B6 — The task context model is redundant and inconsistent

**Severity: High**

The same domain concept is modeled along several axes:

- `type="task"` identifies a memory as a task;
- `scope="task"` describes visibility;
- `task_key` selects a task context;
- `project_key`/`project` group and filter tasks;
- `task_status` supplies workflow state.

They do not compose consistently. The task creation endpoint maps a task to `scope="project"` when it has a project and otherwise to `scope="user"`; it does not use `scope="task"` (`src/memkit/taskboard.py:364-384`). Conversely, extractor-created task-scoped memories are deliberately unkeyed because the core has no task IDs at extraction time (`src/memkit/extract.py:309-343`, especially `src/memkit/extract.py:314-319`). Retrieval then makes those unkeyed task memories broadly visible (`src/memkit/retrieval.py:160-185`).

The Hermes tool schema exposes `user/project/task` scopes and a project field (`integrations/hermes/memkit/__init__.py:60-111`), but the HTTP client search method has no `task_key` parameter (`integrations/hermes/memkit/client.py:105-127`). Prefetch consequently cannot supply keyed task context (`integrations/hermes/memkit/__init__.py:213-244`), and the tool handler maps only scope and project (`integrations/hermes/memkit/__init__.py:381-421`). The core API supports `task_key`, but the primary adapter cannot express it.

This is evidence that the concepts lack a stable infrastructure meaning. They arose from task-domain needs without a domain-owned identity model.

**Required boundary:** Life OS owns real task and project identifiers. Memkit receives opaque context dimensions, for example `{ "workspace": "…", "subject": "…" }`, or a generic filter expression. A Life OS task can point to relevant memkit records; memkit should not infer task identity from memory scope.

### B7 — The memkit admin application is also a task-management product

**Severity: High**

The main router and navigation make Tasks a first-class memkit destination (`web/src/router.tsx:46-55`, `web/src/router.tsx:62-72`, `web/src/components/AppShell.tsx:38-46`). `web/src/routes/Tasks.tsx` is an 877-line task product with:

- fixed statuses and task types: `web/src/routes/Tasks.tsx:78-114`;
- board fetching, filtering, and project grouping: `web/src/routes/Tasks.tsx:158-198`;
- status transitions and drag ordering: `web/src/routes/Tasks.tsx:200-279`;
- task archive/restore/delete actions: `web/src/routes/Tasks.tsx:281-324`;
- project-board presentation: `web/src/routes/Tasks.tsx:326-410`;
- columns, cards, and workflow behavior: `web/src/routes/Tasks.tsx:448-625`;
- create/edit task dialogs and fields: `web/src/routes/Tasks.tsx:640-760`;
- workflow/project/action details: `web/src/routes/Tasks.tsx:762-876`.

Dedicated task-board styling occupies `web/src/styles/globals.css:1237-1484`; drag-and-drop dependencies are product dependencies in `web/package.json:14-17`. Project and branch fields are also presented as fixed session-domain UI (`web/src/routes/Sessions.tsx:25-44`).

**Required boundary:** the memkit admin UI should inspect storage, sources, evidence, extraction, lifecycle, indexes, and generic retrieval. Task boards, workflow buttons, due state, and task dialogs belong in Life OS/Hermes. A diagnostic rendering of opaque metadata is acceptable; operational task manipulation is not.

### B8 — Hermes is isolated correctly, but mirrors rather than owns/translates the domain

**Severity: Medium**

The adapter's placement under `integrations/hermes` and HTTP-only dependency are good boundaries (`integrations/hermes/memkit/__init__.py:1-40`). It also has valuable safeguards: only primary-context content is persisted (`integrations/hermes/memkit/__init__.py:168-183`), prefetch is isolated (`integrations/hermes/memkit/__init__.py:213-244`), tool-result handling and scrubbing are explicit (`integrations/hermes/memkit/__init__.py:271-355`), and the client has circuit-breaker behavior (`integrations/hermes/memkit/client.py:20-98`).

However, the adapter copies memkit's closed type/scope taxonomy instead of translating a Hermes/Life OS domain model (`integrations/hermes/memkit/__init__.py:60-111`). It cannot express the core's full task context, as described in B6. Direct remember writes are mapped to fixed `preference`/`fact` memory types (`integrations/hermes/memkit/__init__.py:336-353`), while task state remains authoritative in memkit.

**Required boundary:** keep the adapter's transport/resilience pattern, but invert authority. Hermes/Life OS owns tasks and its vocabulary, invokes memkit only for memories/evidence/search, and maps domain context into generic memkit filters/policies.

### B9 — Normative documentation canonizes the violations and omits the governing boundary

**Severity: Medium**

The docs correctly describe memkit as one memory service for every agent (`README.md:1-9`, `docs/README.md:3-8`, `docs/01-architecture.md:3-6`), but the documented invariants do not state domain agnosticism or prohibit workflow ownership (`docs/README.md:10-43`).

Instead, the normative documents define the task subsystem as architecture:

- `task_board` is a core table and migration concern: `docs/02-data-model.md:14-28`, `docs/02-data-model.md:60-63`, `docs/02-data-model.md:122-140`;
- task/project types, scopes, and statuses are closed vocabulary: `docs/02-data-model.md:92-109`;
- Qdrant contains task status: `docs/02-data-model.md:142-166`;
- task routes and dual-lock mutation are core API contracts: `docs/03-api.md:11-46`, `docs/03-api.md:115-132`;
- prompt output and parsing specify task scope/status: `docs/04-judge.md:54-105`;
- retrieval specifies task decay and scope policy: `docs/05-retrieval.md:55-106`;
- the roadmap calls the task board completed memkit work: `docs/06-roadmap.md:58-67`.

The ADR index contains no decision recording why a memory service should own a task board, despite the repository's rule to create an ADR when rationale or alternatives matter (`docs/decisions/README.md:5-10`, `docs/decisions/README.md:39-68`). The prompt incident ADR discusses duplicated task-status text without questioning ownership (`docs/decisions/0016-one-home-for-prompt-text.md:11-34`).

Prompt experiments provide further warning: active v6 extracted zero task facts in the reported comparison (`docs/experiments/extractor-prompts.md:160-175`), yet the production schema and domain machinery remain. Archived documents are explicitly non-normative and were not used as evidence for current ownership (`docs/README.md:67-69`).

**Required boundary:** add the primary invariant to the normative architecture document and an ADR defining dependency direction. Rewrite the data/API/judge/retrieval docs after extraction. Document Life OS links rather than task behavior inside memkit.

### B10 — Tests and generated contracts harden the wrong ownership boundary

**Severity: Medium**

The test suite gives the task subsystem broad regression protection:

- table migration, grouping, ordering, status, and Qdrant behavior: `tests/test_taskboard.py:1-90`, `tests/test_taskboard.py:87-233`;
- HTTP create/patch/board contracts: `tests/test_taskboard_routes.py:1-225`;
- frontend task moves and filtering: `web/src/routes/Tasks.test.ts:1-67`;
- extraction parser/status/provider schemas: `tests/test_extract.py:59-89`, `tests/test_extract.py:203-247`;
- task scope and automatic board writes: `tests/test_extract.py:556-607`;
- task decay, scope policy, and vector filters: `tests/test_retrieval.py:60-73`, `tests/test_retrieval.py:82-130`, `tests/test_retrieval.py:180-188`, `tests/test_retrieval.py:285-314`;
- task-board preservation and hard-delete cleanup: `tests/test_provenance.py:345-379`, `tests/test_invariants.py:182-199`;
- generic source output includes task-board data: `tests/test_api.py:24-33`.

The documentation contract explicitly acknowledges that the closed vocabulary is duplicated across four or five locations and then asserts that duplication (`tests/test_docs_contract.py:1-16`, `tests/test_docs_contract.py:64-104`). The generator emits task decay, workflow vocabulary, and task routes (`tools/docblocks.py:89-122`, `tools/docblocks.py:170-198`). This prevents drift but also makes the wrong boundary harder to change.

Evaluation is coding/project-centric: cases carry a project field (`eval/golden.py:46-70`), the conversation corpus emphasizes repository context (`eval/golden/conversations.yaml:20-56`), and query evaluation reports user/project/task scopes (`eval/experiment.py:218-243`). Ticket/task queries are treated mostly as raw retrieval in `eval/queries.yaml:1-23`; there is no golden evaluation proving that task-state inference is correct enough to control workflow.

The missing tests are architectural fitness tests:

- core must not import or mount task/workflow modules;
- core OpenAPI must not expose task CRUD/board routes;
- core schema must not contain task workflow columns/tables;
- generic types and context must accept extensions without editing core literals;
- adapters may depend on memkit, but memkit must not depend on adapters/domains;
- replay/re-extraction must not mutate domain state.

**Required boundary:** move task tests with the task implementation to Life OS. Replace memkit tests with generic extension/policy/context contracts and explicit forbidden-dependency assertions.

### B11 — Claude/project assumptions create an inverted dependency in generic storage

**Severity: Medium**

The generic store imports `MIN_INDEX_CHARS` from the Claude Code importer (`src/memkit/store.py:13-23`). This reverses the dependency direction: infrastructure depends on one source adapter for a generic indexing threshold.

The raw-store/index path also reads a named `project` from session metadata as a built-in indexing concept (`src/memkit/store.py:71-131`, `src/memkit/store.py:134-159`). Session metadata is nominally JSON, but the core CLI and importer define coding-specific `project` and `git_branch` fields (`src/memkit/cli.py:60-130`, `src/memkit/importers/claude_code.py:81-93`, `src/memkit/importers/claude_code.py:179-190`). The main CLI directly exposes Claude Code import and Hermes installation commands (`src/memkit/cli.py:426-480`).

Source integrations are legitimate, but source-specific names must remain at the edge. A generic store should not import from `importers.claude_code`, nor should its index schema assume repositories are the universal context dimension.

**Required boundary:** define a source-adapter protocol and a normalized envelope in core: source identity, message identity, role/content, timestamps, and an opaque context map. Put generic thresholds in core configuration. Let each importer translate cwd/repository/branch into caller-defined context keys.

### B12 — Domain coupling causes stale and asymmetric state during generic type mutation

**Severity: Medium**

Generic mutation contains `_ensure_task_board`, which creates board state when a memory becomes type `task` (`src/memkit/mutate.py:106-145`). `update_memory` invokes it after changes (`src/memkit/mutate.py:225-246`). There is no symmetric removal when a task changes to a non-task type. The generic update's Qdrant payload update changes the `type` field but does not remove the pre-existing `task_status` payload (`src/memkit/mutate.py:241-251`).

The result can be a non-task memory with a hidden/orphaned task-board row and stale vector `task_status`. The same ownership entanglement appears in extraction updates (`src/memkit/extract.py:357-405`). This is not just a missing cleanup branch; it is a consequence of trying to coordinate two aggregates through a generic memory-type edit.

**Required boundary:** eliminate the implicit aggregate creation. A memory type edit changes only memory metadata. Life OS creates/deletes/transitions tasks explicitly and owns referential cleanup. If cross-system references exist, use idempotent domain commands/events and reconciliation rather than a hidden side effect in `update_memory`.

## Cross-layer occurrence inventory

This inventory lists the versioned, current-source locations in which the boundary is encoded. It is intended as a removal/migration checklist.

### Core service

| Path | Boundary-bearing content |
|---|---|
| `src/memkit/db.py:120-133` | Task aggregate schema. |
| `src/memkit/db.py:165-176`, `src/memkit/db.py:239-316` | Task-aware migration and backfill. |
| `src/memkit/taskboard.py:1-484` | Full task domain module and routes. |
| `src/memkit/api.py:36-95` | Closed type/scope and task/project search fields. |
| `src/memkit/api.py:158-160`, `src/memkit/api.py:363-424` | Router mounting, task provenance, task-aware search. |
| `src/memkit/providers.py:39-47`, `src/memkit/providers.py:83-198` | Closed taxonomy and task-state output schemas. |
| `src/memkit/prompts.py:40-80`, `src/memkit/prompts.py:454-530`, `src/memkit/prompts.py:616-670` | Task workflow inference and project/task scope instructions. |
| `src/memkit/judge.py:99-100`, `src/memkit/judge.py:113-223`, `src/memkit/judge.py:331-358` | Taxonomy, repository context, task parsing, coding-agent rendering. |
| `src/memkit/extract.py:205-267`, `src/memkit/extract.py:309-405`, `src/memkit/extract.py:496-563` | Task-state application and project context. |
| `src/memkit/retrieval.py:33-52`, `src/memkit/retrieval.py:66-102`, `src/memkit/retrieval.py:160-248`, `src/memkit/retrieval.py:384-444` | Task decay/status/result, scope boosts/filters, named context. |
| `src/memkit/vectors.py:32-42` | Project/task-status vector indexes. |
| `src/memkit/store.py:13-23`, `src/memkit/store.py:71-159`, `src/memkit/store.py:250-420` | Importer inversion, project assumptions, implicit board writes/reindex. |
| `src/memkit/mutate.py:106-145`, `src/memkit/mutate.py:148-253`, `src/memkit/mutate.py:382-408` | Implicit task aggregate lifecycle from generic memory edits. |
| `src/memkit/consolidate.py:111-126`, `src/memkit/consolidate.py:320-337` | Generic expiry that conflicts with task due semantics. |
| `src/memkit/admin.py:23-25`, `src/memkit/admin.py:176-188`, `src/memkit/admin.py:788-925` | Closed taxonomy and task/project-aware admin queries/stats. |
| `src/memkit/reextract.py:195-268` | Replay of domain-mutating extraction. |
| `src/memkit/cli.py:60-130`, `src/memkit/cli.py:426-480` | Coding-specific import metadata and edge integrations in core CLI. |
| `src/memkit/importers/claude_code.py:81-93`, `src/memkit/importers/claude_code.py:179-190` | Repository/project-specific source model. |

### Hermes adapter

| Path | Boundary-bearing content |
|---|---|
| `integrations/hermes/memkit/__init__.py:60-111` | Mirrors core's closed type/scope vocabulary. |
| `integrations/hermes/memkit/__init__.py:213-244`, `integrations/hermes/memkit/__init__.py:381-421` | Search context cannot express keyed task scope. |
| `integrations/hermes/memkit/client.py:105-127` | Client search omits `task_key`. |

### Web application

| Path | Boundary-bearing content |
|---|---|
| `web/src/api/types.ts:1-54` | Closed memory/scope types and task-board DTOs. |
| `web/src/lib/constants.ts:1-19` | Closed types and task decay. |
| `web/src/router.tsx:46-72` | First-class task route. |
| `web/src/components/AppShell.tsx:38-46` | First-class task navigation. |
| `web/src/routes/Tasks.tsx:78-876` | Task board, workflow, project grouping, actions, forms, due semantics. |
| `web/src/routes/Memories.tsx:147-190`, `web/src/routes/Memories.tsx:239-320` | Task/project type and scope in generic memory UI. |
| `web/src/routes/SearchPlayground.tsx:50-100` | Named project/task retrieval context. |
| `web/src/routes/Sessions.tsx:25-44` | Project/branch as fixed domain context. |
| `web/src/components/AnalyticsCharts.tsx:15-30`, `web/src/components/AnalyticsCharts.tsx:176-254` | Closed domain taxonomy in analytics. |
| `web/src/styles/globals.css:1237-1484` | Dedicated task-product styling. |
| `web/package.json:14-17` | Task-board drag/drop product dependencies. |

### Documentation, tooling, tests, and evaluation

| Path | Boundary-bearing content |
|---|---|
| `docs/README.md:10-43` | Missing domain-ownership invariant. |
| `docs/01-architecture.md:49-62`, `docs/01-architecture.md:77-88` | Named task/project scopes and durable-memory contradiction. |
| `docs/02-data-model.md:14-28`, `docs/02-data-model.md:92-166` | Task schema, vocabulary, migration, vector payload. |
| `docs/03-api.md:11-46`, `docs/03-api.md:82-132` | Task routes and task-aware search/mutation. |
| `docs/04-judge.md:54-105` | Task/project extraction contract. |
| `docs/05-retrieval.md:55-106` | Task decay and scope policy. |
| `docs/06-roadmap.md:58-67` | Task board recorded as memkit feature. |
| `docs/08-testing.md:38-51`, `docs/08-testing.md:132-157`, `docs/08-testing.md:209-224` | Tests preserve task migration/scope but omit the ownership boundary. |
| `docs/experiments/extractor-prompts.md:27-50`, `docs/experiments/extractor-prompts.md:160-175` | Task-status prompt duplication and weak task extraction evidence. |
| `docs/decisions/0016-one-home-for-prompt-text.md:11-34` | Optimizes task prompt ownership inside core rather than questioning it. |
| `tools/docblocks.py:89-122`, `tools/docblocks.py:170-198` | Generates task vocabulary/decay/routes into normative docs. |
| `tests/test_taskboard.py:1-233` | Core task persistence/retrieval contract. |
| `tests/test_taskboard_routes.py:1-225` | Core task HTTP contract. |
| `tests/test_extract.py:59-89`, `tests/test_extract.py:182-247`, `tests/test_extract.py:556-607` | Task schema, scope, and workflow writes. |
| `tests/test_retrieval.py:60-130`, `tests/test_retrieval.py:180-188`, `tests/test_retrieval.py:285-314` | Task decay/visibility/filter policy. |
| `tests/test_consolidate.py:61-90` | Task deadline/memory-validity collision. |
| `tests/test_docs_contract.py:1-16`, `tests/test_docs_contract.py:64-104` | Pins duplicated closed domain vocabulary. |
| `tests/test_provenance.py:345-379`, `tests/test_invariants.py:182-199` | Task-board migration and deletion coupling. |
| `tests/test_api.py:24-33` | Task board in generic source response. |
| `web/src/routes/Tasks.test.ts:1-67` | Frontend workflow behavior. |
| `eval/golden.py:46-70`, `eval/golden/conversations.yaml:20-56` | Project/coding-specific evaluation model. |
| `eval/experiment.py:218-243`, `eval/queries.yaml:1-23` | Reports hard-coded scopes without validating task workflow authority. |

## Architectural strengths worth preserving

The boundary failure should not obscure several sound infrastructure choices.

1. **Clear source of truth versus derived index.** SQLite is authoritative and Qdrant is rebuildable; the architecture explicitly describes that separation (`docs/01-architecture.md:10-19`). Reindexing derives active points from SQLite (`src/memkit/store.py:381-420`). This is the right model for repairability.

2. **Strong provenance and evidence.** Provenance resolution is centralized, and write eligibility is guarded by source role (`src/memkit/provenance.py:1-30`, `src/memkit/provenance.py:58-134`). The database schema does not silently default provenance-sensitive fields (`src/memkit/db.py:104-115`). This is particularly valuable when memories drive downstream agents.

3. **Idempotent ingestion.** Sessions/messages have stable uniqueness constraints (`src/memkit/db.py:48-66`), and the store uses those identities during ingestion (`src/memkit/store.py:26-68`).

4. **Transaction/index sequencing.** Mutation separates durable SQLite commit from derived-index application and exposes the indexing result (`src/memkit/mutate.py:1-50`). This is a good basis for an outbox/reconciliation design.

5. **Versioned and replayable extraction.** Judge runs retain model/prompt/usage metadata (`src/memkit/judge.py:59-65`), and re-extraction is a first-class operation (`src/memkit/reextract.py:1-25`). Once domain mutation is removed, this is excellent memory-infrastructure behavior.

6. **Explainable retrieval.** Scoring is decomposed into explicit factors, results retain the breakdown, and search enforces deduplication/context budgets (`src/memkit/retrieval.py:105-134`, `src/memkit/retrieval.py:417-520`). The mechanism is reusable if its policy inputs become caller-controlled.

7. **Well-defended adapter edge.** Hermes uses HTTP isolation, primary-context checks, scrubbing, and failure containment (`integrations/hermes/memkit/__init__.py:1-40`, `integrations/hermes/memkit/__init__.py:168-183`, `integrations/hermes/memkit/__init__.py:271-355`, `integrations/hermes/memkit/client.py:20-98`). This is the correct physical dependency direction.

8. **Executable documentation discipline.** Generated blocks and contract tests keep documented values aligned with code (`tools/docblocks.py:1-37`, `tests/test_docs_contract.py:36-104`). After the boundary is corrected, this mechanism should enforce generic contracts rather than domain vocabulary.

9. **The task code is internally modular enough to extract.** A separate table avoids overloading memory timestamps, and optimistic workflow versioning/order logic is localized (`docs/02-data-model.md:60-63`, `src/memkit/taskboard.py:201-335`). Preserve those implementation qualities in Life OS rather than deleting the functionality outright.

## Missing generic abstractions

### 1. Opaque context dimensions and a generic filter algebra

Replace the `user/project/task` enum plus `project`, `task_key`, and `scope_key` special cases with caller-owned dimensions and generic predicates. A minimal query model could support equality, membership, absence, and conjunction over an indexed context map. Memkit should not know which dimension is a repository, task, conversation, customer, patient, or case.

### 2. Extensible memory classification

The current closed `fact/preference/decision/task/project/...` vocabulary is duplicated across layers (`tests/test_docs_contract.py:1-16`). Use opaque kinds/tags, optionally backed by a registry that declares display labels and default infrastructure behavior. Domain types must be storable and searchable without provider-schema, SQL, UI, or core-release changes.

### 3. Caller-owned retrieval profiles

Separate the scoring engine from the current hard-coded policy. A versioned profile should supply type/tag half-lives, context boosts, filters, importance weights, and result budgets. Store the chosen policy identifier in explanations for reproducibility. Memkit can ship a neutral default, while Life OS supplies its task/project activation policy.

### 4. Extraction policy/plugin boundary

Separate generic evidence/claim extraction from domain commands. The core should accept a versioned prompt/schema/operator plugin or publish immutable extraction observations. A Life OS component can interpret observations into proposed task/reminder/goal commands, validate them, and apply them under domain rules. Replays should be safe because they reproduce observations, not live state transitions.

### 5. Explicit cross-system references/events

Life OS needs a task entity with its own ID and optional `memory_id`, source-message IDs, or evidence links. Memkit needs no task foreign key. If automatic suggestions are desired, use an idempotent event/outbox contract such as `memory.observation.created`; Life OS consumes it and records the source event ID.

### 6. Separate temporal truth from scheduling

Keep `valid_from`/`valid_until` for claim validity. Put `due_at`, `remind_at`, recurrence, snooze, and overdue/completion semantics exclusively in Life OS. The API and UI should make the distinction impossible to confuse.

### 7. Normalized source-adapter envelope

Define a generic core interface for source/message identity, author/role, content, time, and opaque context. Move cwd-to-project and git-branch extraction entirely into the Claude adapter. Generic indexing thresholds must live in core configuration, not an importer module.

### 8. Architecture fitness tests

Add automated dependency and contract checks: no `taskboard` import under core, no domain route/schema literals, no adapter-to-core reverse import, extension types accepted without core edits, and re-extraction prohibited from calling domain mutations. Treat the primary invariant as a testable property, not only prose.

## Recommended target architecture

| Concern | Memkit | Life OS/Hermes |
|---|---|---|
| Source messages, evidence, provenance | Authoritative | References/consumes |
| Memory claims and validity | Authoritative | References/queries |
| Embeddings and generic search execution | Authoritative | Supplies context and policy |
| Task identity/status/order/due date | No ownership | Authoritative |
| Goals/reminders/habits/workflows | No ownership | Authoritative |
| Domain extraction and transitions | Executes only explicitly supplied generic plugin, or emits observations | Defines, validates, applies |
| Memory diagnostics UI | Owns | May link to it |
| Task/workflow UI | Does not own | Owns |

Desired dependency flow:

```text
Hermes / Life OS domain
  ├─ owns tasks, goals, reminders, projects, policies, UI
  ├─ stores references to memkit memory/evidence IDs
  └─ calls generic memkit APIs with opaque context + retrieval profile
                         ↓
Memkit infrastructure
  ├─ ingest → evidence → claims → provenance
  ├─ SQLite truth → derived vector index
  └─ generic filter/rank/explain
```

There must be no reverse dependency from memkit into Life OS/Hermes vocabulary or state.

## Migration sequence

A read-only check of the current SQLite database found schema version 3, 100 memories, five task memories, and five matching `task_board` rows. All five tasks are `done`; there are no orphan rows and no task currently has `valid_until`. The migration set is therefore small and internally consistent, and all IDs can be preserved.

1. **Codify the invariant first.** Add an ADR and an architecture fitness test that forbids new task/workflow ownership in core.
2. **Stop authority leakage.** Disable LLM-driven task-board mutation and ensure replay/re-extraction can only create memory observations.
3. **Create the Life OS aggregate.** Add Life OS-owned task IDs, status, project, position/version, `due_at`, and evidence/memory references.
4. **Migrate data deliberately.** Move `task_board` rows and interpret historical task `valid_until` as candidate `due_at`; preserve source/evidence links. Do not expire unfinished tasks during migration.
5. **Introduce generic contracts.** Add opaque context filters, extensible kinds/tags, and caller-supplied retrieval profiles before removing compatibility fields.
6. **Move product surfaces.** Transfer task routes, DTOs, UI, CSS, tests, and documentation to Life OS/Hermes.
7. **Remove core residues.** Drop task schema/backfills/indexes, task prompt/provider fields, implicit mutation hooks, fixed task decay/scope logic, and generated-doc vocabulary.
8. **Rebuild derived indexes and verify.** Reindex from SQLite, assert no `task_status` payloads remain, and run both generic memkit fitness tests and Life OS workflow tests.

## Final assessment

Memkit has a solid infrastructure nucleus: evidence-aware storage, provenance, replayable extraction, derived indexes, explainable retrieval, and a well-contained Hermes adapter. The repository's central architectural mistake is that a task product was built through that entire nucleus instead of above it.

The corrective direction is unambiguous: **extract task authority and all workflow semantics to Life OS/Hermes; make memkit's context, classification, extraction, and retrieval policy genuinely generic.** The task module's existing separation and the derived-index design make a staged migration feasible without discarding the strongest parts of the system.
