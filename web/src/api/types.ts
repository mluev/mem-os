/** Names for the generated wire contracts. Keep transport shapes in OpenAPI. */
import type { components } from "./schema";

type Schema = components["schemas"];
export type Memory = Schema["MemoryRecord"];
export type TeamMemory = Memory;
export type MemorySummary = Schema["MemorySummary"];
export type SearchResult = Schema["MemorySearchOut"];
export type SessionMessages = Schema["SessionMessagesOut"];
export type JudgeRun = Schema["JudgeRunOut"];
export type JudgeRuns = Schema["JudgeRunsOut"];
export type Jobs = Schema["JobsOut"];
export type JobQueued = Schema["JobQueuedOut"];
export type Health = Schema["AdminHealthOut"];
export type Metrics = Schema["MetricsOut"];
export type Backups = Schema["BackupsOut"];
export type Scope = Schema["ScopeView"];
export type Me = Schema["PrincipalView"];
export type User = Schema["UserView"];
export type ApiKey = Schema["ApiKeyView"];
export type Entity = Schema["EntityView"];
export type EntityKind = Entity["kind"];
export type EntityProfile = Schema["EntityProfileOut"];
export type ReviewStatus = Memory["review_status"];
export type ReviewItem = Schema["ReviewItem"];
export type ReviewKind = ReviewItem["kind"];
export type ReviewQueue = Schema["ReviewQueueOut"];
export type MemoryEvidence = Schema["EvidenceSpan"];
export type MemorySources = Schema["MemorySourcesOut"];
export type MemoryHistory = Schema["MemoryHistoryOut"];
export type SeriesPoint = Schema["SeriesPoint"];
export type EntityUsage = Schema["EntityUsage"];
export type PersonUsage = Schema["PersonUsage"];
export type MemoryTotals = Schema["MemoryTotals"];
export type PipelineTotals = Schema["PipelineTotals"];
export type RetrievalTotals = Schema["RetrievalTotals"];
export type ReviewTotals = Schema["ReviewTotals"];
export type DashboardMetrics = Metrics;

/** Statistics share the generated envelope across their typed totals. */
export type Stats<T = Record<string, unknown>> = Pick<Schema["MemoryStatsOut"], "from" | "to" | "bucket" | "series"> & { totals: T };

export type Entities = Schema["EntitiesOut"];
export type Users = Schema["UsersOut"];
export type ApiKeys = Schema["ApiKeysOut"];
export type KeyCreated = Schema["KeyCreatedOut"];
export type MemoryCreated = Schema["MemoryCreatedOut"];
export type MemoryDetail = Schema["MemoryOut"];
export type MemoryPage = Schema["MemoryPageOut"];
export type SessionsPage = Schema["SessionsOut"];
export type RetrievalRuns = Schema["RetrievalRunsOut"];
export type ReviewStats = Schema["ReviewStatsOut"];
export type MemoryStats = Schema["MemoryStatsOut"];
export type EntityCreated = Schema["EntityCreatedOut"];
