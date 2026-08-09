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
  qdrant: { memories: number; raw: number };
  embedder: { ready: boolean; device: string | null; revision: string };
  outbox: { pending: number };
  jobs: Record<string, number>;
}
export interface Metrics {
  outbox_pending: number; oldest_unprocessed_message: string | null;
  provider_errors: number; month_spend_usd: number; month_reserved_usd: number;
}
