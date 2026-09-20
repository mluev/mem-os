/**
 * Fetch hooks for `/v1/admin/stats/*`, the review queue, and the numbers the
 * dashboard's cards report.
 *
 * Every statistics endpoint answers with one envelope, so this file is mostly
 * naming: a hook per endpoint, a totals type per endpoint, and one polling
 * policy. The aggregation is already done on the server -- these hooks fetch a
 * few dozen numbers, not a month of rows -- which is why they can be polled.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { ApiError, api, queryString } from "./client";
import type {
  EntityUsage,
  Me,
  DashboardMetrics,
  MemoryTotals,
  PipelineTotals,
  RetrievalTotals,
  ReviewTotals,
  ReviewQueue,
  MemoryPage,
  PersonUsage,
  ReviewKind,
  Stats,
} from "./types";

/** The ranges the overview offers. Bound to the `days` search param. */
export const RANGES = [7, 30, 90] as const;
export type Range = (typeof RANGES)[number];
export const DEFAULT_RANGE: Range = 30;

export function resolveRange(days: number | undefined): Range {
  return RANGES.includes(days as Range) ? (days as Range) : DEFAULT_RANGE;
}

/** What `group_by` the memories endpoint accepts. Anything else is a 422. */
export const MEMORY_GROUPS = ["scope", "kind", "source_role", "review_status"] as const;
export type MemoryGroup = (typeof MEMORY_GROUPS)[number];

export type { DashboardMetrics, MemoryTotals, PipelineTotals, RetrievalTotals, ReviewTotals } from "./types";

/** Statistics are cheap to serve but not free; a minute of staleness is fine. */
const POLICY = { staleTime: 60_000, refetchOnWindowFocus: false } as const;

function useStats<T>(
  name: string,
  path: string,
  params: Record<string, string | number | undefined>,
  options: { enabled?: boolean } = {},
): UseQueryResult<Stats<T>, unknown> {
  return useQuery({
    queryKey: ["stats", name, params],
    queryFn: () => api<Stats<T>>(`/v1/admin/stats/${path}${queryString(params)}`),
    ...POLICY,
    enabled: options.enabled ?? true,
    retry: false,
  });
}

export function useMemoryStats(days: Range, groupBy: MemoryGroup) {
  return useStats<MemoryTotals>("memories", "memories", { days, group_by: groupBy });
}

export function usePipelineStats(days: Range) {
  return useStats<PipelineTotals>("pipeline", "pipeline", { days });
}

export function useRetrievalStats(days: Range) {
  return useStats<RetrievalTotals>("retrieval", "retrieval", { days });
}

export function useReviewStats(days: Range) {
  return useStats<ReviewTotals>("review", "review", { days });
}

export function useEntityStats(limit = 8) {
  return useStats<{ entities: EntityUsage[] }>("entities", "entities", { limit });
}

/**
 * Per-person activity. Administrators only -- the service answers 403 for
 * anyone else, so the query is gated on the caller's role and the 403 is
 * reported as a plain flag rather than an error state. A member should see the
 * panel absent, not broken, and nothing about a colleague either way.
 */
export function usePeopleStats(days: Range, isAdmin: boolean) {
  const query = useStats<{ people: PersonUsage[] }>("users", "users", { days }, {
    enabled: isAdmin,
  });
  const forbidden = query.error instanceof ApiError && query.error.status === 403;
  return { ...query, forbidden, people: query.data?.totals.people ?? [] };
}

export function useDashboardMetrics() {
  return useQuery({
    queryKey: ["metrics"],
    queryFn: () => api<DashboardMetrics>("/v1/admin/metrics"),
    staleTime: 30_000,
    retry: false,
  });
}

/** Shares its key with the shell so the identity is fetched once. */
export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/v1/auth/me"), staleTime: 60_000 });
}

/**
 * Genuinely recent: the listing orders by `updated_at`, so a fact that was
 * rewritten today appears above one merely created before it.
 */
export function useRecentMemories(limit = 6) {
  return useQuery({
    queryKey: ["memories", "recent", limit],
    queryFn: () => api<MemoryPage>(`/v1/memories${queryString({ limit, sort: "updated_at", order: "desc" })}`),
    staleTime: 30_000,
  });
}

export function reviewQueueKey(kind: ReviewKind | undefined) {
  return ["review", "queue", kind ?? "all"] as const;
}

export type { ReviewQueue } from "./types";

/**
 * The queue itself. `limit` is applied per source by the server, so one
 * generous request returns every kind rather than a page of the first one.
 */
export function useReviewQueue(kind: ReviewKind | undefined, limit = 100) {
  return useQuery({
    queryKey: reviewQueueKey(kind),
    queryFn: () => api<ReviewQueue>(`/v1/review${queryString({ kind, limit })}`),
    staleTime: 10_000,
  });
}
