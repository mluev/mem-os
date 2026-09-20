import { describe, expect, it } from "vitest";
import {
  DEFAULT_LIMIT,
  clearedFilters,
  hasFilters,
  limitOf,
  listParams,
  offsetOf,
  paginationToSearch,
  rowRange,
  sortingToSearch,
  tablePagination,
  tableSorting,
  withFilters,
} from "./MemoryTableState";

describe("memory table state", () => {
  it("falls back to the server's own defaults for absent or invalid params", () => {
    expect(listParams({})).toMatchObject({
      status: "active",
      sort: "updated_at",
      order: "desc",
      limit: DEFAULT_LIMIT,
      offset: 0,
    });
    // A hand-edited URL must not produce a 422.
    expect(listParams({ sort: "text", order: "sideways" })).toMatchObject({
      sort: "updated_at",
      order: "desc",
    });
    expect(limitOf({ limit: 9000 })).toBe(500);
    expect(limitOf({ limit: 0 })).toBe(1);
    expect(limitOf({ limit: Number.NaN })).toBe(DEFAULT_LIMIT);
    expect(offsetOf({ offset: -20 })).toBe(0);
  });

  it("passes every filter through to the listing query", () => {
    expect(
      listParams({
        q: "pnpm",
        kind: "preference",
        scope: "team",
        subject: "maga",
        source_role: "user",
        status: "any",
        review_status: "pending",
        tag: "tooling",
      }),
    ).toMatchObject({
      q: "pnpm",
      kind: "preference",
      scope: "team",
      subject: "maga",
      source_role: "user",
      status: "any",
      review_status: "pending",
      tag: "tooling",
    });
  });

  it("derives header sort state, and leaves it empty for a sort with no column", () => {
    expect(tableSorting({})).toEqual([{ id: "updated_at", desc: true }]);
    expect(tableSorting({ sort: "importance", order: "asc" })).toEqual([
      { id: "importance", desc: false },
    ]);
    expect(tableSorting({ sort: "confidence" })).toEqual([]);
  });

  it("round-trips sorting between the table and the URL", () => {
    expect(sortingToSearch([{ id: "importance", desc: false }])).toEqual({
      sort: "importance",
      order: "asc",
    });
    expect(sortingToSearch(tableSorting({ sort: "updated_at", order: "asc" }))).toEqual({
      sort: "updated_at",
      order: "asc",
    });
    // Removing the sort means the default order, never an unordered listing.
    expect(sortingToSearch([])).toEqual({ sort: "updated_at", order: "desc" });
    expect(sortingToSearch([{ id: "text", desc: true }])).toEqual({
      sort: "updated_at",
      order: "desc",
    });
  });

  it("maps offset and limit to a page index and back", () => {
    expect(tablePagination({ offset: 100, limit: 25 })).toEqual({ pageIndex: 4, pageSize: 25 });
    expect(tablePagination({})).toEqual({ pageIndex: 0, pageSize: DEFAULT_LIMIT });
    expect(paginationToSearch({ pageIndex: 2, pageSize: 25 })).toEqual({ offset: 50, limit: 25 });
    // Defaults stay out of the URL so a plain view has a plain link.
    expect(paginationToSearch({ pageIndex: 0, pageSize: DEFAULT_LIMIT })).toEqual({
      offset: undefined,
      limit: undefined,
    });
  });

  it("returns to the first page whenever a filter changes", () => {
    const search = { q: "pnpm", offset: 150, limit: 25, memory: "m-1" };
    const next = withFilters(search, { kind: "preference" });
    expect(next).toEqual({
      q: "pnpm",
      kind: "preference",
      limit: 25,
      memory: "m-1",
      offset: undefined,
    });
  });

  it("treats an empty selection as no filter at all", () => {
    expect(withFilters({ kind: "preference" }, { kind: "" })).toEqual({
      offset: undefined,
    });
    // The default status is not a filter, so it never lands in the URL.
    expect(withFilters({}, { status: "active" })).toEqual({ offset: undefined });
    expect(withFilters({}, { status: "any" })).toEqual({ status: "any", offset: undefined });
  });

  it("knows whether the reader narrowed anything", () => {
    expect(hasFilters({})).toBe(false);
    expect(hasFilters({ status: "active" })).toBe(false);
    expect(hasFilters({ memory: "m-1", sort: "importance" })).toBe(false);
    expect(hasFilters({ tag: "tooling" })).toBe(true);
    expect(hasFilters({ status: "any" })).toBe(true);
  });

  it("clears filters while keeping the drawer, sort and page size", () => {
    expect(
      clearedFilters({
        q: "pnpm",
        status: "any",
        tag: "tooling",
        sort: "importance",
        limit: 25,
        offset: 50,
        memory: "m-1",
      }),
    ).toEqual({ sort: "importance", limit: 25, offset: undefined, memory: "m-1" });
  });

  it("describes the visible range from the server's total", () => {
    expect(rowRange(214, 50, 50)).toEqual({ from: 51, to: 100, total: 214 });
    expect(rowRange(0, 0, 0)).toEqual({ from: 0, to: 0, total: 0 });
    // A short last page reports what it actually holds.
    expect(rowRange(214, 200, 14)).toEqual({ from: 201, to: 214, total: 214 });
  });
});
