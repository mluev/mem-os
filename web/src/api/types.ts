export interface Memory {
  id: string;
  agent_id: string | null;
  kind: string;
  text: string;
  importance: number;
  confidence: number;
  status: "active" | "archived" | "expired" | "superseded";
  source_role: "user" | "assistant" | "agent" | "tool" | "manual";
  context: Record<string, unknown>;
  tags: string[];
  valid_from: string;
  valid_until: string | null;
  created_at: string;
  updated_at: string;
  redacted: number;
}

export interface CursorPage<T> { items: T[]; next_cursor: string | null }
export interface OffsetPage<T> { items: T[]; total: number; limit: number; offset: number }

export interface SearchResult {
  memories: Array<Pick<Memory, "id" | "text" | "kind" | "context" | "tags" | "source_role"> & {
    score: number; similarity: number; lexical: number;
  }>;
  raw: Array<Record<string, unknown>>;
  used_tokens: number;
  policy_id: string;
  retrieval_id: string | null;
  timings: Record<string, number>;
  took_ms: number;
}

export interface Session {
  id: string; agent_id: string; started_at: string; ended_at: string | null;
  message_count: number; unprocessed_count: number; context: Record<string, unknown>;
}
export interface Message {
  id: number; role: "user" | "assistant" | "tool"; content: string;
  created_at: string; processed: number; redacted: number;
}
export interface JudgeRun {
  id: number; kind: string; model: string; prompt_version: string;
  input_json: string; output_json: string | null; error: string | null;
  input_tokens: number | null; output_tokens: number | null;
  cost_usd: number | null; latency_ms: number | null; created_at: string;
}
export interface Job {
  id: string; kind: string; status: "queued" | "running" | "complete" | "failed" | "cancelled";
  result_json: string | null; error: string | null; created_at: string; updated_at: string;
  cancel_requested: number;
}
export interface Health {
  database: { path: string; schema_version: number };
  qdrant: { available: boolean; memories: number | null; raw: number | null; error?: string | null };
  embedder: { ready: boolean; device: string | null; revision: string };
  outbox: { pending: number };
  jobs: Record<string, number>;
}
export interface Metrics {
  outbox_pending: number; oldest_unprocessed_message: string | null;
  provider_errors: number; month_spend_usd: number; month_reserved_usd: number;
  search_latency_ms?: { p50: number | null; p95: number | null; p99: number | null };
  abstention_rate?: number | null; feedback_labels?: number;
  outbox_oldest_age_seconds?: number | null; outbox_retries?: number;
  index_parity?: { sqlite_active: number; qdrant_active: number | null; matches: boolean | null };
  backup_freshness_seconds?: number | null;
}

export interface RetrievalRun {
  id: string; policy_id: string; created_at: string; used_tokens: number; abstained: boolean;
  timings: Record<string, number>;
  results: Array<{ memory_id: string; text?: string; kind?: string; source_role?: string; rank: number; feedback: { useful: number | null; correct: number | null } | null }>;
}

export interface ReplayBatch {
  id: string; status: string; model: string; prompt_version: string; approval_checksum: string | null;
  stats: Record<string, unknown>; created_at: string; decisions?: Record<string, number>;
}
export interface ReplayItem {
  id: string; sequence: number; action: "ADD" | "UPDATE" | "DELETE"; decision: "pending" | "accepted" | "rejected" | "edited";
  source_role: string; before: Memory | null; proposed: Memory | null; reviewed: Memory | null;
  evidence: Array<{ message_id: number; excerpt: string; start_char: number; end_char: number }>;
}
export interface EvaluationCase {
  id: string; case_key: string; prompt: string; arms: Record<"A" | "B" | "C" | "D", string>;
  review: { ranking: Array<"A" | "B" | "C" | "D">; harmful: string[]; notes: string; current_vs_v7: "v7_win" | "current_win" | "tie" } | null;
  mapping?: Record<string, string>;
}
