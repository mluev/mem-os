export type MemoryStatus = "active" | "expired" | "superseded";
export type TaskWorkflowStatus = "unknown" | "todo" | "doing" | "done";
export type MemoryType =
  | "preference"
  | "fact"
  | "skill"
  | "relation"
  | "project"
  | "decision"
  | "task";

export interface Memory {
  id: string;
  owner_id: string;
  agent_id: string | null;
  scope: "user" | "project" | "task";
  scope_key: string | null;
  type: MemoryType;
  text: string;
  importance: number;
  confidence: number;
  status: MemoryStatus;
  superseded_by: string | null;
  valid_from: string;
  valid_until: string | null;
  created_at: string;
  updated_at: string;
  last_retrieved_at: string | null;
  retrieval_count: number;
  extraction_version: string;
  judge_run_id: number | null;
}

export interface TaskBoardItem extends Memory {
  workflow_status: TaskWorkflowStatus;
  project_key: string | null;
  position: number;
  board_version: number;
  board_updated_at: string;
}

export interface TaskProject {
  key: string | null;
  label: string;
  count: number;
}

export interface TaskBoard {
  items: TaskBoardItem[];
  counts: Record<TaskWorkflowStatus, number>;
  projects: TaskProject[];
  total: number;
  include_archived: boolean;
}

export interface MemoryList {
  memories: Memory[];
  count: number;
  total: number;
  limit: number;
  offset: number;
  sort: string;
  order: string;
}

export interface JudgeOp {
  op: string;
  id?: string | null;
  text?: string | null;
  type?: string | null;
  reason?: string;
  matches_this_memory?: boolean;
}

export interface JudgeRun {
  id: number;
  kind: string;
  model: string;
  prompt_version: string;
  input_json: string;
  output_json: string | null;
  error: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cost_usd: number | null;
  latency_ms: number | null;
  created_at: string;
  ops: JudgeOp[];
}

export interface Session {
  id: string;
  owner_id: string;
  agent_id: string;
  started_at: string;
  ended_at: string | null;
  meta: Record<string, unknown>;
  message_count: number;
  unprocessed_count: number;
  memory_count: number;
}

export interface Message {
  id: number;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  processed: number;
  indexed_raw: boolean;
  memory_ids: string[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface ActivityDay {
  day: string;
  memories: number;
  memory_types: Partial<Record<MemoryType, number>>;
  messages: number;
  judge_runs: number;
  cost_usd: number;
}

export interface DashboardStats {
  memories: {
    total: number;
    by_status: Record<string, number>;
    by_type: Record<string, number>;
    by_scope: Record<string, number>;
    by_scope_key: Record<string, number>;
    importance: Record<string, number>;
    never_retrieved: number;
    low_confidence: number;
    expiring_7d: number;
    superseded: number;
    expired: number;
    stale_90d: number;
  };
  corpus: {
    messages: number;
    unprocessed: number;
    sessions: number;
    judge_runs: number;
  };
  cost: {
    month_spend_usd: number;
    monthly_limit_usd: number;
    total_usd: number;
    calls: number;
    errors: number;
    by_kind: Record<string, number>;
  };
  health: {
    sqlite_active: number;
    qdrant_memories: number;
    index_drift: number;
    sqlite_raw_eligible: number;
    qdrant_raw: number;
    raw_drift: number;
    index_dirty: boolean;
  };
  backlog: {
    sessions: number;
    messages: number;
    windows: number;
    estimated_cost_usd: number;
    basis: string;
  };
  analytics: {
    daily: ActivityDay[];
    confidence: Record<"low" | "medium" | "high", number>;
    retrieval: Record<"never" | "1–4" | "5–19" | "20+", number>;
    agents: Array<{
      agent_id: string;
      sessions: number;
      messages: number;
      memories: number;
    }>;
  };
}
