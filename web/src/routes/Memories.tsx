/**
 * The memories table: the screen a reader spends their time in.
 *
 * Everything that narrows or orders the listing lives in the URL, so a view is
 * a link and the back button undoes a filter instead of leaving the screen.
 * The server owns paging, sorting and filtering — it has the real total — and
 * TanStack Table is used in its manual modes, as a layout and selection
 * engine rather than as a client-side data engine.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArchiveRestore,
  ArrowDown,
  ArrowUp,
  Check,
  ChevronsUpDown,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, queryString } from "../api/client";
import type { MemoryPage, TeamMemory } from "../api/types";
import { MemoryAddDialog } from "../components/MemoryAddDialog";
import { MemoryDrawer } from "../components/MemoryDrawer";
import { FilterSelect, LifecycleBadge, ReviewBadge, ValueSelect } from "../components/MemoryFields";
import {
  entityOptions,
  plainOptions,
  scopeOptions,
  useMemoryOptions,
} from "../components/MemoryOptions";
import {
  DEFAULT_LIMIT,
  MEMORY_SORTS,
  PAGE_SIZES,
  REVIEW_STATUSES,
  SOURCE_ROLES,
  STATUSES,
  clearedFilters,
  hasFilters,
  limitOf,
  listParams,
  offsetOf,
  orderOf,
  paginationToSearch,
  rowRange,
  sortOf,
  sortingToSearch,
  statusOf,
  tablePagination,
  tableSorting,
  withFilters,
  type MemorySearch,
} from "../components/MemoryTableState";
import {
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  Importance,
  Input,
  Loading,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
  TypeBadge,
} from "../components/ui";
import { integer, relativeTime } from "../lib/format";

const COLUMN_CLASS: Record<string, string> = {
  select: "col-check",
  kind: "col-type",
  scope: "col-type",
  subject: "col-type",
  author: "col-type",
  importance: "col-number",
  review_status: "col-type",
  updated_at: "col-updated",
};

const SORT_LABEL: Record<string, string> = {
  updated_at: "Recently updated",
  created_at: "Recently created",
  importance: "Importance",
  confidence: "Confidence",
  retrieval_count: "Times retrieved",
};

const HEADER_BUTTON = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  padding: 0,
  border: 0,
  background: "none",
  color: "inherit",
  font: "inherit",
  letterSpacing: "inherit",
  cursor: "pointer",
} as const;

type BulkAction = "confirm" | "decline" | "archive" | "restore";

const BULK_LABEL: Record<BulkAction, string> = {
  confirm: "Confirmed",
  decline: "Marked wrong",
  archive: "Archived",
  restore: "Restored",
};

export function Memories() {
  const search = useSearch({ from: "/memories" }) as MemorySearch;
  const navigate = useNavigate({ from: "/memories" });
  const client = useQueryClient();
  const [selection, setSelection] = useState<RowSelectionState>({});
  const [adding, setAdding] = useState(false);
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>());
  const lastOpened = useRef<string | null>(null);

  const commit = useCallback(
    (next: MemorySearch) => {
      void navigate({ search: next });
    },
    [navigate],
  );

  // Keyed on the query string rather than on the search object: opening the
  // drawer changes the search params without changing the listing, and a new
  // object identity there would refetch and drop the reader's row selection.
  const query = useMemo(() => queryString(listParams(search)), [search]);
  const page = useQuery({
    queryKey: ["memories", "list", query],
    queryFn: () => api<MemoryPage>(`/v1/memories${query}`),
    placeholderData: keepPreviousData,
  });

  const rows = useMemo(() => page.data?.items ?? [], [page.data]);
  const total = page.data?.total ?? 0;
  const offset = offsetOf(search);
  const options = useMemoryOptions(rows.map((row) => row.kind));

  function openMemory(id: string): void {
    lastOpened.current = id;
    commit({ ...search, memory: id });
  }

  function closeDrawer(): void {
    const previous = lastOpened.current;
    commit({ ...search, memory: undefined });
    // Focus belongs back on the row the reader opened, not at the top of the
    // document; the row only exists again after the drawer unmounts.
    requestAnimationFrame(() => previous && rowRefs.current.get(previous)?.focus());
  }

  const columns = useMemo<ColumnDef<TeamMemory>[]>(
    () => [
      {
        id: "select",
        enableSorting: false,
        header: ({ table }) => (
          <Checkbox
            aria-label="Select every memory on this page"
            checked={
              table.getIsAllPageRowsSelected()
                ? true
                : table.getIsSomePageRowsSelected()
                  ? "indeterminate"
                  : false
            }
            onCheckedChange={(value) => table.toggleAllPageRowsSelected(value === true)}
          />
        ),
        cell: ({ row }) => (
          <Checkbox
            aria-label={`Select ${row.original.text.slice(0, 60)}`}
            checked={row.getIsSelected()}
            onClick={(event) => event.stopPropagation()}
            onCheckedChange={(value) => row.toggleSelected(value === true)}
          />
        ),
      },
      {
        id: "text",
        header: "Memory",
        enableSorting: false,
        cell: ({ row }) => (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="memory-text">{row.original.text}</span>
            </TooltipTrigger>
            <TooltipContent side="bottom" align="start" style={{ maxWidth: 460 }}>
              {row.original.text}
            </TooltipContent>
          </Tooltip>
        ),
      },
      {
        id: "kind",
        header: "Kind",
        enableSorting: false,
        cell: ({ row }) => <TypeBadge type={row.original.kind} />,
      },
      {
        id: "scope",
        header: "Scope",
        enableSorting: false,
        cell: ({ row }) => <span className="subtle">{row.original.scope ?? "—"}</span>,
      },
      {
        id: "subject",
        header: "About",
        enableSorting: false,
        cell: ({ row }) => <span className="subtle">{row.original.subject ?? "—"}</span>,
      },
      {
        id: "author",
        header: "Author",
        enableSorting: false,
        cell: ({ row }) => <span className="subtle">{row.original.author ?? "—"}</span>,
      },
      {
        // A sortable column needs an accessor: TanStack Table refuses to sort
        // a pure display column even in manual mode.
        id: "importance",
        accessorFn: (row) => row.importance,
        header: "Importance",
        cell: ({ row }) => <Importance value={row.original.importance} />,
      },
      {
        id: "review_status",
        header: "Review",
        enableSorting: false,
        cell: ({ row }) => (
          <span style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 4 }}>
            <ReviewBadge status={row.original.review_status} />
            <LifecycleBadge status={row.original.status} />
          </span>
        ),
      },
      {
        id: "updated_at",
        accessorFn: (row) => row.updated_at,
        header: "Updated",
        cell: ({ row }) => (
          <span className="subtle mono">{relativeTime(row.original.updated_at)}</span>
        ),
      },
    ],
    [],
  );

  const sorting = useMemo(() => tableSorting(search), [search]);
  const pagination = useMemo(() => tablePagination(search), [search]);

  const table = useReactTable({
    data: rows,
    columns,
    getRowId: (row) => row.id,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    enableSortingRemoval: false,
    rowCount: total,
    state: { sorting, pagination, rowSelection: selection },
    onRowSelectionChange: setSelection,
    onSortingChange: (updater) => {
      const next: SortingState = typeof updater === "function" ? updater(sorting) : updater;
      commit(withFilters(search, sortingToSearch(next)));
    },
    onPaginationChange: (updater) => {
      const next: PaginationState = typeof updater === "function" ? updater(pagination) : updater;
      commit({ ...search, ...paginationToSearch(next) });
    },
  });

  const selectedIds = useMemo(
    () => Object.keys(selection).filter((id) => selection[id]),
    [selection],
  );
  const revisions = useMemo(
    () => new Map(rows.map((row) => [row.id, row.revision])),
    [rows],
  );

  // A page or filter change must not leave invisible rows selected: the action
  // bar would then report on rows the reader can no longer see.
  useEffect(() => setSelection({}), [query]);

  const bulk = useMutation({
    mutationFn: async ({ action, ids }: { action: BulkAction; ids: string[] }) => {
      const results = await Promise.allSettled(
        ids.map((id) => {
          const path = `/v1/memories/${encodeURIComponent(id)}`;
          if (action === "archive") return api(path, { method: "DELETE" });
          if (action === "restore") return api(`${path}/restore`, { method: "POST" });
          return api(`${path}/review`, {
            method: "POST",
            body: JSON.stringify({
              decision: action,
              expected_revision: revisions.get(id),
            }),
          });
        }),
      );
      const failures = results.filter(
        (result): result is PromiseRejectedResult => result.status === "rejected",
      );
      return {
        done: results.length - failures.length,
        stale: failures.filter((item) => item.reason instanceof ApiError && item.reason.status === 409)
          .length,
        failures,
      };
    },
    onSuccess: async (result, { action, ids }) => {
      const reversible: Partial<Record<BulkAction, BulkAction>> = {
        archive: "restore",
        decline: "confirm",
      };
      const inverse = reversible[action];
      if (result.done) {
        toast.success(`${BULK_LABEL[action]} ${result.done} of ${ids.length}`, {
          action:
            inverse && result.done === ids.length
              ? { label: "Undo", onClick: () => bulk.mutate({ action: inverse, ids }) }
              : undefined,
        });
      }
      if (result.failures.length) {
        const first = result.failures[0]?.reason;
        toast.error(
          `${result.failures.length} could not be ${BULK_LABEL[action].toLowerCase()}`,
          {
            description: result.stale
              ? `${result.stale} changed while you were looking at them. Refresh and try again.`
              : first instanceof Error
                ? first.message
                : undefined,
          },
        );
      }
      setSelection({});
      await Promise.all([
        client.invalidateQueries({ queryKey: ["memories"] }),
        client.invalidateQueries({ queryKey: ["stats"] }),
      ]);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const range = rowRange(total, offset, rows.length);
  const filtered = hasFilters(search);

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">TEAM MEMORY</span>
          <h1>Memories</h1>
          <p>
            Every fact the store holds in a space you can read. Automatic writes arrive pending and
            are already usable; confirming one is a person vouching for it.
          </p>
        </div>
        <div className="page-actions">
          <Button
            variant="secondary"
            aria-label="Refresh memories"
            onClick={() => void page.refetch()}
          >
            <RefreshCw size={14} className={page.isFetching ? "spin" : undefined} /> Refresh
          </Button>
          <Button onClick={() => setAdding(true)}>
            <Plus size={14} /> Add memory
          </Button>
        </div>
      </div>

      <div className="filter-bar">
        <SearchField value={search.q ?? ""} onCommit={(q) => commit(withFilters(search, { q }))} />
        <FilterSelect
          label="Kind"
          value={search.kind}
          options={plainOptions(options.kinds)}
          anyLabel="Any kind"
          onChange={(kind) => commit(withFilters(search, { kind }))}
        />
        <FilterSelect
          label="Scope"
          value={search.scope}
          options={scopeOptions(options.scopes)}
          anyLabel="Every space"
          onChange={(scope) => commit(withFilters(search, { scope }))}
        />
        <FilterSelect
          label="About"
          value={search.subject}
          options={entityOptions(options.entities)}
          anyLabel="Anyone"
          onChange={(subject) => commit(withFilters(search, { subject }))}
        />
        <FilterSelect
          label="Source"
          value={search.source_role}
          options={plainOptions(SOURCE_ROLES)}
          anyLabel="Any source"
          onChange={(source_role) => commit(withFilters(search, { source_role }))}
        />
        <FilterSelect
          label="Status"
          value={statusOf(search) === "active" ? undefined : statusOf(search)}
          options={plainOptions(STATUSES.filter((value) => value !== "active"))}
          anyLabel="Active only"
          onChange={(status) => commit(withFilters(search, { status: status || "active" }))}
        />
        <FilterSelect
          label="Review"
          value={search.review_status}
          options={plainOptions(REVIEW_STATUSES)}
          anyLabel="Any review state"
          onChange={(review_status) => commit(withFilters(search, { review_status }))}
        />
        <div style={{ width: 172 }}>
          <ValueSelect
            label="Sort by"
            value={sortOf(search)}
            options={MEMORY_SORTS.map((value) => ({
              value,
              label: SORT_LABEL[value] ?? value,
            }))}
            onChange={(sort) => commit(withFilters(search, { sort }))}
          />
        </div>
        <Button
          variant="secondary"
          size="icon"
          aria-label={orderOf(search) === "desc" ? "Sort ascending" : "Sort descending"}
          onClick={() =>
            commit(withFilters(search, { order: orderOf(search) === "desc" ? "asc" : "desc" }))
          }
        >
          {orderOf(search) === "desc" ? <ArrowDown size={14} /> : <ArrowUp size={14} />}
        </Button>
        {filtered ? (
          <Button variant="ghost" size="sm" onClick={() => commit(clearedFilters(search))}>
            <X size={13} /> Clear filters
          </Button>
        ) : null}
      </div>

      <Card className="table-shell">
        {page.isLoading ? (
          <Loading label="Loading memories" />
        ) : page.error ? (
          <ErrorState error={page.error} retry={() => void page.refetch()} />
        ) : !rows.length ? (
          filtered ? (
            <EmptyState
              title="No memories match these filters"
              body="Widen the search, or clear the filters to see everything in the spaces you can read."
              action={
                <Button variant="secondary" onClick={() => commit(clearedFilters(search))}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              title="Nothing stored yet"
              body="Facts appear here as sessions are processed. You can also write the first one yourself — it will be confirmed straight away in your own space."
              action={<Button onClick={() => setAdding(true)}>Add the first memory</Button>}
            />
          )
        ) : (
          <TooltipProvider delayDuration={350}>
            <table className="data-table" role="grid" aria-rowcount={total}>
              <thead>
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((header) => {
                      const sorted = header.column.getIsSorted();
                      return (
                        <th
                          key={header.id}
                          scope="col"
                          className={COLUMN_CLASS[header.column.id]}
                          aria-sort={
                            sorted === "asc"
                              ? "ascending"
                              : sorted === "desc"
                                ? "descending"
                                : header.column.getCanSort()
                                  ? "none"
                                  : undefined
                          }
                        >
                          {header.column.getCanSort() ? (
                            <button
                              type="button"
                              style={HEADER_BUTTON}
                              onClick={header.column.getToggleSortingHandler()}
                            >
                              {flexRender(header.column.columnDef.header, header.getContext())}
                              {sorted === "asc" ? (
                                <ArrowUp size={11} />
                              ) : sorted === "desc" ? (
                                <ArrowDown size={11} />
                              ) : (
                                <ChevronsUpDown size={11} style={{ opacity: 0.5 }} />
                              )}
                            </button>
                          ) : (
                            flexRender(header.column.columnDef.header, header.getContext())
                          )}
                        </th>
                      );
                    })}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row, index) => {
                  const open = search.memory === row.original.id;
                  return (
                    <tr
                      key={row.id}
                      ref={(element) => {
                        if (element) rowRefs.current.set(row.original.id, element);
                        else rowRefs.current.delete(row.original.id);
                      }}
                      tabIndex={0}
                      aria-rowindex={offset + index + 2}
                      aria-selected={row.getIsSelected()}
                      aria-current={open ? "true" : undefined}
                      className={
                        row.original.status === "expired" || row.original.status === "archived"
                          ? "row-expired"
                          : undefined
                      }
                      style={open ? { background: "var(--panel-subtle)" } : undefined}
                      onClick={() => openMemory(row.original.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          openMemory(row.original.id);
                        }
                      }}
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className={COLUMN_CLASS[cell.column.id]}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TooltipProvider>
        )}
        {rows.length ? (
          <div className="pagination">
            <span className="mono">
              {integer(range.from)}–{integer(range.to)} of {integer(range.total)}
              {page.isFetching ? " · refreshing" : ""}
            </span>
            <span className="pagination-actions">
              <div style={{ width: 128 }}>
                <ValueSelect
                  label="Rows per page"
                  value={String(limitOf(search))}
                  options={PAGE_SIZES.map((size) => ({
                    value: String(size),
                    label: `${size} per page`,
                  }))}
                  onChange={(size) =>
                    commit({
                      ...search,
                      ...paginationToSearch({
                        pageIndex: 0,
                        pageSize: Number(size) || DEFAULT_LIMIT,
                      }),
                    })
                  }
                />
              </div>
              <Button
                variant="secondary"
                size="sm"
                disabled={!table.getCanPreviousPage()}
                onClick={() => table.previousPage()}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!table.getCanNextPage()}
                onClick={() => table.nextPage()}
              >
                Next
              </Button>
            </span>
          </div>
        ) : null}
      </Card>

      {selectedIds.length ? (
        <div className="floating-actions" role="region" aria-label="Actions for selected memories">
          <strong>
            {selectedIds.length} selected
          </strong>
          <Button
            variant="secondary"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate({ action: "confirm", ids: selectedIds })}
          >
            <Check size={13} /> Confirm
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate({ action: "decline", ids: selectedIds })}
          >
            <X size={13} /> Decline
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate({ action: "archive", ids: selectedIds })}
          >
            <Trash2 size={13} /> Archive
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled={bulk.isPending}
            onClick={() => bulk.mutate({ action: "restore", ids: selectedIds })}
          >
            <ArchiveRestore size={13} /> Restore
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setSelection({})}>
            Clear
          </Button>
        </div>
      ) : null}

      <MemoryAddDialog open={adding} onOpenChange={setAdding} onCreated={openMemory} />
      <MemoryDrawer memoryId={search.memory ?? null} onClose={closeDrawer} />
    </>
  );
}

/**
 * The search box writes to the URL, but only after the reader stops typing:
 * one navigation per keystroke would flood the history stack and the server.
 */
function SearchField({ value, onCommit }: { value: string; onCommit: (next: string) => void }) {
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);

  useEffect(() => {
    if (draft === value) return;
    const timer = window.setTimeout(() => onCommit(draft), 300);
    return () => window.clearTimeout(timer);
  }, [draft, value, onCommit]);

  return (
    <div className="search-field">
      <Search size={14} />
      <Input
        type="search"
        aria-label="Search memories"
        placeholder="Search the text of every fact…"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
    </div>
  );
}
