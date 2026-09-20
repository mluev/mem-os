/**
 * The memories table keeps all of its state in the URL.
 *
 * Filters, sort, page size and the open drawer are search params, never
 * component state, because that is what makes a filtered view a link somebody
 * can paste into a thread and what makes the back button undo a filter instead
 * of leaving the screen. This module is the whole translation between that URL
 * and the three shapes the screen needs: TanStack Table's sorting/pagination
 * state, and the query the listing endpoint expects.
 *
 * It is deliberately pure so the mapping is testable without a router.
 */

import type { SortingState } from "@tanstack/react-table";

/** What `GET /v1/memories?sort=` accepts. Anything else is a 422. */
export const MEMORY_SORTS = [
  "updated_at",
  "created_at",
  "importance",
  "confidence",
  "retrieval_count",
] as const;
export type MemorySort = (typeof MEMORY_SORTS)[number];
export type SortOrder = "asc" | "desc";

/**
 * The sorts that also have a column to click. `created_at`, `confidence` and
 * `retrieval_count` have no column of their own, so they are reachable from the
 * sort control instead — but a link carrying them still sorts correctly, which
 * is why the header state is derived rather than owned.
 */
export const HEADER_SORTS: readonly MemorySort[] = ["importance", "updated_at"];

export const DEFAULT_SORT: MemorySort = "updated_at";
export const DEFAULT_ORDER: SortOrder = "desc";
export const DEFAULT_STATUS = "active";
export const DEFAULT_LIMIT = 50;
export const MAX_LIMIT = 500;
export const PAGE_SIZES = [25, 50, 100] as const;

/** `any` is the server's word for "including archived and superseded". */
export const STATUSES = ["active", "archived", "superseded", "expired", "any"] as const;
export const REVIEW_STATUSES = ["pending", "confirmed", "declined"] as const;
export const SOURCE_ROLES = ["user", "assistant", "agent", "tool", "manual"] as const;

/** The shape `/memories` validates in the router. */
export interface MemorySearch {
  q?: string;
  kind?: string;
  scope?: string;
  subject?: string;
  source_role?: string;
  status?: string;
  review_status?: string;
  tag?: string;
  sort?: string;
  order?: string;
  offset?: number;
  limit?: number;
  memory?: string;
}

/** Params that narrow the listing; changing any of them returns to page one. */
export const FILTER_KEYS = [
  "q",
  "kind",
  "scope",
  "subject",
  "source_role",
  "status",
  "review_status",
  "tag",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];

export function sortOf(search: MemorySearch): MemorySort {
  const candidate = search.sort as MemorySort | undefined;
  return candidate && MEMORY_SORTS.includes(candidate) ? candidate : DEFAULT_SORT;
}

export function orderOf(search: MemorySearch): SortOrder {
  return search.order === "asc" ? "asc" : DEFAULT_ORDER;
}

export function statusOf(search: MemorySearch): string {
  return search.status || DEFAULT_STATUS;
}

export function limitOf(search: MemorySearch): number {
  const value = search.limit;
  if (typeof value !== "number" || !Number.isFinite(value)) return DEFAULT_LIMIT;
  return Math.min(MAX_LIMIT, Math.max(1, Math.floor(value)));
}

export function offsetOf(search: MemorySearch): number {
  const value = search.offset;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return 0;
  return Math.floor(value);
}

export function tableSorting(search: MemorySearch): SortingState {
  const sort = sortOf(search);
  if (!HEADER_SORTS.includes(sort)) return [];
  return [{ id: sort, desc: orderOf(search) === "desc" }];
}

/** Clearing the sort falls back to the server's own default, not to no order. */
export function sortingToSearch(sorting: SortingState): { sort: MemorySort; order: SortOrder } {
  const first = sorting[0];
  const id = first?.id as MemorySort | undefined;
  if (!first || !id || !MEMORY_SORTS.includes(id)) {
    return { sort: DEFAULT_SORT, order: DEFAULT_ORDER };
  }
  return { sort: id, order: first.desc ? "desc" : "asc" };
}

export function tablePagination(search: MemorySearch): { pageIndex: number; pageSize: number } {
  const pageSize = limitOf(search);
  return { pageIndex: Math.floor(offsetOf(search) / pageSize), pageSize };
}

/**
 * Defaults are left out of the URL so a plain view has a plain link; the
 * readers above put them back.
 */
export function paginationToSearch(pagination: { pageIndex: number; pageSize: number }): {
  offset: number | undefined;
  limit: number | undefined;
} {
  const offset = Math.max(0, pagination.pageIndex) * pagination.pageSize;
  return {
    offset: offset > 0 ? offset : undefined,
    limit: pagination.pageSize === DEFAULT_LIMIT ? undefined : pagination.pageSize,
  };
}

/** The query for `GET /v1/memories`. `queryString` drops the empty values. */
export function listParams(search: MemorySearch): Record<string, string | number | undefined> {
  return {
    q: search.q,
    kind: search.kind,
    scope: search.scope,
    subject: search.subject,
    source_role: search.source_role,
    status: statusOf(search),
    review_status: search.review_status,
    tag: search.tag,
    sort: sortOf(search),
    order: orderOf(search),
    limit: limitOf(search),
    offset: offsetOf(search),
  };
}

/**
 * Apply a filter change. An empty string means "no filter" rather than
 * "matches the empty string", and any change drops the offset — page 7 of the
 * old result set is meaningless in the new one.
 */
export function withFilters(search: MemorySearch, patch: Partial<MemorySearch>): MemorySearch {
  const next: MemorySearch = { ...search, ...patch, offset: undefined };
  for (const key of FILTER_KEYS) {
    if (next[key] === "") delete next[key];
  }
  if (next.status === DEFAULT_STATUS) delete next.status;
  return next;
}

/** Whether the reader narrowed anything, which decides which empty state to show. */
export function hasFilters(search: MemorySearch): boolean {
  if (statusOf(search) !== DEFAULT_STATUS) return true;
  return FILTER_KEYS.some((key) => key !== "status" && Boolean(search[key]));
}

/** Every filter off, keeping the drawer, sort and page size the reader chose. */
export function clearedFilters(search: MemorySearch): MemorySearch {
  const next: MemorySearch = { ...search, offset: undefined };
  for (const key of FILTER_KEYS) delete next[key];
  return next;
}

/** "Showing 51–100 of 214", using the server's total rather than a guess. */
export function rowRange(
  total: number,
  offset: number,
  rows: number,
): { from: number; to: number; total: number } {
  if (total <= 0 || rows <= 0) return { from: 0, to: 0, total: Math.max(0, total) };
  return { from: offset + 1, to: offset + rows, total };
}
