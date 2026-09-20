/**
 * The queue of everything waiting on a person.
 *
 * Five different things share one list because they share one question -- "is
 * this right?" -- and a reviewer who has to visit five screens visits none. The
 * screen is built around the keyboard for the same reason: a queue that costs a
 * mouse round trip per item does not get emptied, and this one grows on its own
 * every time the extractor runs.
 *
 * Decisions are applied optimistically. The write is small and the common case
 * is a person moving through twenty items in twenty seconds; waiting for each
 * round trip would make the shortcut keys pointless. A failure puts the item
 * back where it was and says so.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import {
  AlertTriangle,
  Brain,
  CircleDollarSign,
  Keyboard,
  Link2,
  ServerCrash,
  UserSearch,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { Entity, ReviewItem, ReviewKind } from "../api/types";
import { reviewQueueKey, useReviewQueue, type ReviewQueue } from "../api/stats";
import {
  Badge,
  Button,
  Card,
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Loading,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "../components/ui";
import { relativeTime } from "../lib/format";

/** Read order: the things a person decides, then the things they acknowledge. */
const ORDER: ReviewKind[] = ["memory", "unresolved_mention", "conflict", "failed_job", "budget"];

const META: Record<ReviewKind, { label: string; blurb: string; icon: typeof Brain }> = {
  memory: {
    label: "Unconfirmed memories",
    blurb: "Written automatically and live already. Confirm what is true, decline what is not.",
    icon: Brain,
  },
  unresolved_mention: {
    label: "Unplaced names",
    blurb: "A name nobody could resolve. Linking it teaches the alias, so it resolves by itself next time.",
    icon: UserSearch,
  },
  conflict: {
    label: "Conflicts",
    blurb: "Two facts that cannot both be true.",
    icon: AlertTriangle,
  },
  failed_job: {
    label: "Failed work",
    blurb: "Background work that did not finish. Nothing was lost; it was not applied.",
    icon: ServerCrash,
  },
  budget: { label: "Budget", blurb: "Model spend against the monthly limit.", icon: CircleDollarSign },
};

const SHORTCUTS: [string, string][] = [
  ["j / k", "Move down and up the queue"],
  ["a", "Confirm the memory"],
  ["d", "Decline it, which deletes it"],
  ["u", "Undo the last decision"],
  ["l", "Link an unplaced name to an entity"],
  ["x", "Dismiss the item"],
  ["Enter", "Open the memory"],
  ["?", "Show this panel"],
];

const KEY_STYLE = {
  border: "1px solid var(--line-strong)",
  borderRadius: 4,
  padding: "1px 5px",
  font: "10px var(--font-mono)",
  color: "var(--muted)",
} as const;

function Key({ children }: { children: string }) {
  return <kbd style={KEY_STYLE}>{children}</kbd>;
}

/** The memory a row refers to, if it refers to one. */
function memoryIdOf(item: ReviewItem): string | null {
  if (item.kind === "memory") return item.memory?.id ?? item.id;
  return item.memory_id ?? null;
}

export function Review() {
  const client = useQueryClient();
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { kind?: string };
  const kind = ORDER.includes(search.kind as ReviewKind) ? (search.kind as ReviewKind) : undefined;
  const queueKey = reviewQueueKey(kind);
  const queue = useReviewQueue(kind);

  const [cursor, setCursor] = useState(0);
  const [last, setLast] = useState<{ item: ReviewItem; decision: "confirm" | "decline" } | null>(null);
  const [help, setHelp] = useState(false);
  const [linking, setLinking] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());
  const focused = useRef(false);

  /** Grouped for reading, flat for the keyboard. Both from one ordering. */
  const groups = useMemo(() => {
    const items = queue.data?.items ?? [];
    return ORDER.map((group) => ({ kind: group, items: items.filter((item) => item.kind === group) })).filter(
      (group) => group.items.length > 0,
    );
  }, [queue.data]);
  const flat = useMemo(() => groups.flatMap((group) => group.items), [groups]);
  const active = flat[Math.min(cursor, flat.length - 1)];

  useEffect(() => {
    // The cursor is an index into a list that shrinks under it. Staying at the
    // same index means the next item slides under the cursor, which is what a
    // person burning through a queue expects.
    if (cursor > 0 && cursor >= flat.length) setCursor(Math.max(0, flat.length - 1));
  }, [cursor, flat.length]);

  useEffect(() => {
    if (!active) return;
    rowRefs.current.get(active.id)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  useEffect(() => {
    // Put focus on the list once, so the highlighted row is announced and the
    // ARIA active-descendant pattern is real rather than decorative. Only
    // while focus is still nowhere: a reader who has already clicked something
    // keeps it.
    if (!flat.length || focused.current) return;
    if (document.activeElement && document.activeElement !== document.body) return;
    focused.current = true;
    listRef.current?.focus({ preventScroll: true });
  }, [flat.length]);

  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: ["review"] });
    void client.invalidateQueries({ queryKey: ["stats"] });
    void client.invalidateQueries({ queryKey: ["metrics"] });
    void client.invalidateQueries({ queryKey: ["memories"] });
  }, [client]);

  /** Take the row out of the cached list, returning the list as it was. */
  const removeOptimistically = useCallback(
    async (id: string) => {
      await client.cancelQueries({ queryKey: queueKey });
      const snapshot = client.getQueryData<ReviewQueue>(queueKey);
      client.setQueryData<ReviewQueue>(queueKey, (old) =>
        old ? { items: old.items.filter((item) => item.id !== id) } : old,
      );
      return snapshot;
    },
    [client, queueKey],
  );

  const restore = useCallback(
    (snapshot: ReviewQueue | undefined, error: unknown) => {
      if (snapshot) client.setQueryData(queueKey, snapshot);
      toast.error(error instanceof Error ? error.message : "Could not record that");
    },
    [client, queueKey],
  );

  const undo = useMutation({
    mutationFn: (item: ReviewItem) =>
      api(`/v1/memories/${memoryIdOf(item)}/review`, {
        method: "POST",
        // No `expected_revision`: the decision being undone moved the
        // revision on, and an undo is a deliberate override, not a race.
        body: JSON.stringify({ decision: "undo" }),
      }),
    onSuccess: () => {
      setLast(null);
      toast.success("Back in the queue");
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : "Could not undo"),
    onSettled: refresh,
  });

  const decide = useMutation({
    mutationFn: ({ item, decision }: { item: ReviewItem; decision: "confirm" | "decline" }) =>
      api(`/v1/memories/${memoryIdOf(item)}/review`, {
        method: "POST",
        // The revision the reviewer actually read. If the extractor rewrote
        // the fact in the meantime the service answers 409 rather than
        // confirming wording nobody approved.
        body: JSON.stringify({ decision, expected_revision: item.memory?.revision }),
      }),
    onMutate: ({ item }) => removeOptimistically(item.id).then((snapshot) => ({ snapshot })),
    onError: (error, _variables, context) => restore(context?.snapshot, error),
    onSuccess: (_data, { item, decision }) => {
      setLast({ item, decision });
      toast.success(decision === "confirm" ? "Confirmed" : "Declined", {
        description: item.title.slice(0, 90),
        action: { label: "Undo", onClick: () => undo.mutate(item) },
      });
    },
    onSettled: refresh,
  });

  const resolve = useMutation({
    mutationFn: ({ item, action, entity }: { item: ReviewItem; action: "link_entity" | "dismiss"; entity?: string }) =>
      api(`/v1/attention/${item.id}/resolve`, {
        method: "POST",
        body: JSON.stringify({ action, entity }),
      }),
    onMutate: ({ item }) => removeOptimistically(item.id).then((snapshot) => ({ snapshot })),
    onError: (error, _variables, context) => restore(context?.snapshot, error),
    onSuccess: (_data, { action, entity }) => {
      // There is no inverse endpoint for either action, so this toast makes no
      // Undo offer it cannot keep.
      toast.success(action === "link_entity" ? `Linked to ${entity}` : "Dismissed", {
        description:
          action === "link_entity"
            ? "The fact moved to the team scope and the alias is learned."
            : undefined,
      });
    },
    onSettled: refresh,
  });

  const openMemory = useCallback(
    (item: ReviewItem) => {
      const id = memoryIdOf(item);
      if (!id) {
        toast.message("Nothing to open", { description: "This item is not about one memory." });
        return;
      }
      void navigate({ to: ".", search: (old: Record<string, unknown>) => ({ ...old, memory: id }) });
    },
    [navigate],
  );

  const dismiss = useCallback(
    (item: ReviewItem) => {
      if (item.kind === "unresolved_mention" || item.kind === "conflict") {
        resolve.mutate({ item, action: "dismiss" });
        return;
      }
      if (item.kind === "memory") {
        toast.message("A memory is confirmed or declined, not dismissed", {
          description: "Press a to confirm this wording, or d to delete it.",
        });
        return;
      }
      // Honest about the gap rather than hiding the row and pretending: the
      // service has no per-item dismissal for a failed job or for the budget
      // warning. A failed job ages out of the queue after seven days; the
      // budget line clears when spend falls back under 80% of the limit.
      toast.message("Nothing to dismiss here", {
        description:
          item.kind === "failed_job"
            ? "A failed job leaves the queue on its own after seven days."
            : "The budget line clears when spend falls back below the limit.",
        action: { label: "Operations", onClick: () => void navigate({ to: "/ops" }) },
      });
    },
    [navigate, resolve],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      // Never steal a key from a text field, a dialog or the command palette.
      // `instanceof` rather than a cast: the target of a key event is not
      // always an element, and `window.closest` is not a function.
      const target = event.target instanceof HTMLElement ? event.target : null;
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) return;
      if (event.key === "?") {
        event.preventDefault();
        setHelp((open) => !open);
        return;
      }
      if (event.key === "Escape") {
        setHelp(false);
        setLinking(null);
        return;
      }
      if (!flat.length) return;
      const item = flat[Math.min(cursor, flat.length - 1)];
      switch (event.key) {
        case "j":
        case "ArrowDown":
          event.preventDefault();
          setCursor((index) => Math.min(index + 1, flat.length - 1));
          return;
        case "k":
        case "ArrowUp":
          event.preventDefault();
          setCursor((index) => Math.max(index - 1, 0));
          return;
        case "u":
          event.preventDefault();
          if (last) undo.mutate(last.item);
          else toast.message("No decision to undo yet");
          return;
        default:
          break;
      }
      if (!item) return;
      switch (event.key) {
        case "a":
          event.preventDefault();
          if (item.kind === "memory") decide.mutate({ item, decision: "confirm" });
          else toast.message("Only an unconfirmed memory can be confirmed");
          return;
        case "d":
          event.preventDefault();
          if (item.kind === "memory") decide.mutate({ item, decision: "decline" });
          else toast.message("Only an unconfirmed memory can be declined");
          return;
        case "x":
          event.preventDefault();
          dismiss(item);
          return;
        case "l":
          if (item.kind === "unresolved_mention") {
            event.preventDefault();
            setLinking(item.id);
          }
          return;
        case "Enter":
          event.preventDefault();
          openMemory(item);
          return;
        default:
          return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cursor, decide, dismiss, flat, last, openMemory, undo]);

  const total = flat.length;
  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">NEEDS ATTENTION</span>
          <h1>{total ? `${total} waiting on you` : "Nothing waiting"}</h1>
          <p>
            Every automatic write is live immediately and unconfirmed. Confirming says it is true;
            declining deletes it. Nothing here is a draft.
          </p>
        </div>
        <Button variant="secondary" onClick={() => setHelp(true)}>
          <Keyboard size={14} /> Shortcuts
        </Button>
      </div>

      <div className="filter-bar">
        <FilterChip label="Everything" count={total} active={!kind} onClick={() => void navigate({ to: ".", search: (old: Record<string, unknown>) => ({ ...old, kind: undefined }) })} />
        {ORDER.map((group) => (
          <FilterChip
            key={group}
            label={META[group].label}
            count={queue.data?.items.filter((item) => item.kind === group).length ?? 0}
            active={kind === group}
            onClick={() => void navigate({ to: ".", search: (old: Record<string, unknown>) => ({ ...old, kind: group }) })}
          />
        ))}
        <div className="chart-legend" style={{ marginLeft: "auto", gap: 12, flexWrap: "wrap" }}>
          <span><Key>j</Key><Key>k</Key> move</span>
          <span><Key>a</Key> confirm</span>
          <span><Key>d</Key> decline</span>
          <span><Key>u</Key> undo</span>
          <span><Key>?</Key> all shortcuts</span>
        </div>
      </div>

      {queue.isLoading ? (
        <Loading label="Reading the queue…" />
      ) : queue.error ? (
        <ErrorState error={queue.error} retry={() => void queue.refetch()} />
      ) : !groups.length ? (
        <EmptyState
          title="The queue is empty"
          body={
            kind
              ? "Nothing of this kind is waiting. Clear the filter to see the rest."
              : "Every memory has been reviewed and no name is unplaced. New extractions will appear here."
          }
          action={<Link className="button button-secondary" to="/memories">Browse memories</Link>}
        />
      ) : (
        <div
          className="triage-list"
          role="listbox"
          aria-label="Review queue"
          aria-activedescendant={active ? `review-${active.id}` : undefined}
          tabIndex={0}
          ref={listRef}
          style={{ gap: 16, outline: "none" }}
        >
          {groups.map((group) => {
            const Icon = META[group.kind].icon;
            return (
              <Card key={group.kind} role="group" aria-label={META[group.kind].label}>
                <div className="card-header">
                  <div>
                    <h2>{META[group.kind].label}</h2>
                    <p>{META[group.kind].blurb}</p>
                  </div>
                  <span className="triage-count">{group.items.length}</span>
                </div>
                {group.items.map((item) => (
                  <Row
                    key={item.id}
                    item={item}
                    icon={<Icon size={16} />}
                    selected={active?.id === item.id}
                    busy={decide.isPending || resolve.isPending}
                    linking={linking === item.id}
                    onSelect={() => setCursor(flat.findIndex((candidate) => candidate.id === item.id))}
                    onOpen={() => openMemory(item)}
                    onDecide={(decision) => decide.mutate({ item, decision })}
                    onDismiss={() => dismiss(item)}
                    onLinkOpen={(open) => setLinking(open ? item.id : null)}
                    onLink={(entity) => {
                      setLinking(null);
                      resolve.mutate({ item, action: "link_entity", entity });
                    }}
                    register={(node) => {
                      if (node) rowRefs.current.set(item.id, node);
                      else rowRefs.current.delete(item.id);
                    }}
                  />
                ))}
              </Card>
            );
          })}
        </div>
      )}

      <Dialog open={help} onOpenChange={setHelp}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Keyboard</DialogTitle>
            <DialogDescription>
              The queue is meant to be emptied without a mouse. Keys act on the highlighted row.
            </DialogDescription>
          </DialogHeader>
          <dl className="metadata-grid" style={{ gridTemplateColumns: "90px 1fr", gap: "10px 14px" }}>
            {SHORTCUTS.map(([keys, description]) => (
              <div key={keys} style={{ display: "contents" }}>
                <dt><Key>{keys}</Key></dt>
                <dd>{description}</dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
    </>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={active ? "memory-type-chip is-active" : "memory-type-chip"}
      aria-pressed={active}
      onClick={onClick}
    >
      {label}
      <strong>{count}</strong>
    </button>
  );
}

function Row({
  item,
  icon,
  selected,
  busy,
  linking,
  onSelect,
  onOpen,
  onDecide,
  onDismiss,
  onLink,
  onLinkOpen,
  register,
}: {
  item: ReviewItem;
  icon: React.ReactNode;
  selected: boolean;
  busy: boolean;
  linking: boolean;
  onSelect: () => void;
  onOpen: () => void;
  onDecide: (decision: "confirm" | "decline") => void;
  onDismiss: () => void;
  onLink: (entity: string) => void;
  onLinkOpen: (open: boolean) => void;
  register: (node: HTMLDivElement | null) => void;
}) {
  const meta = [
    item.author ? `by ${item.author}` : null,
    item.memory?.scope ? `in ${item.memory.scope}` : null,
    item.subject ?? item.memory?.subject ? `about ${item.subject ?? item.memory?.subject}` : null,
    item.created_at ? relativeTime(item.created_at) : null,
  ].filter(Boolean);
  return (
    <div
      className="triage-row"
      role="option"
      id={`review-${item.id}`}
      aria-selected={selected}
      ref={register}
      onClick={onSelect}
      style={
        selected
          ? { background: "var(--panel-subtle)", boxShadow: "inset 2px 0 0 var(--accent)" }
          : undefined
      }
    >
      <span className="triage-icon" aria-hidden="true">{icon}</span>
      <div className="triage-copy">
        <strong>{item.title || "(no wording)"}</strong>
        <span>{meta.join(" · ")}</span>
        {item.previous_text ? (
          // `del` rather than a struck-through span: it is the wording this
          // fact used to have, which is what the element means -- and
          // `.triage-copy span` is a block, so a nested span would break the
          // sentence across two lines.
          <span title="What this memory said before the extractor rewrote it">
            was: <del>{item.previous_text}</del>
          </span>
        ) : null}
        {item.detail && item.detail !== item.title ? <span>{item.detail}</span> : null}
      </div>
      {item.memory ? <Badge>{item.memory.kind}</Badge> : null}
      {item.error_code ? <Badge>{item.error_code}</Badge> : null}
      <div className="page-actions">
        {item.actions.includes("confirm") ? (
          <Button size="sm" disabled={busy} onClick={() => onDecide("confirm")}>Confirm</Button>
        ) : null}
        {item.actions.includes("decline") ? (
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => onDecide("decline")}>Decline</Button>
        ) : null}
        {item.actions.includes("link_entity") ? (
          <EntityPicker open={linking} onOpenChange={onLinkOpen} onPick={onLink} name={item.title} />
        ) : null}
        {item.actions.includes("dismiss") ? (
          <Button variant="ghost" size="sm" disabled={busy} onClick={onDismiss}>Dismiss</Button>
        ) : null}
        {item.kind === "memory" || item.memory_id ? (
          <Button variant="ghost" size="sm" onClick={onOpen}>Open</Button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * The entity a loose name belongs to.
 *
 * Fetched on open rather than with the queue: the list is only needed once a
 * reviewer decides to place a name, and it shares its cache key with the
 * memories screen so opening this twice costs one request.
 */
function EntityPicker({
  open,
  onOpenChange,
  onPick,
  name,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (slug: string) => void;
  name: string;
}) {
  const entities = useQuery({
    queryKey: ["entities", "all"],
    queryFn: () => api<{ items: Entity[] }>("/v1/entities"),
    staleTime: 60_000,
    enabled: open,
  });
  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button variant="secondary" size="sm">
          <Link2 size={13} /> Link
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" style={{ width: 300, padding: 0 }}>
        <Command>
          <CommandInput placeholder={`Who is “${name}”?`} autoFocus />
          <CommandList>
            {entities.isLoading ? <CommandEmpty>Loading…</CommandEmpty> : <CommandEmpty>No matching entity.</CommandEmpty>}
            <CommandGroup heading="Entities">
              {(entities.data?.items ?? []).map((entity) => (
                <CommandItem
                  key={entity.id}
                  value={`${entity.name} ${entity.slug} ${entity.aliases.join(" ")}`}
                  onSelect={() => onPick(entity.slug)}
                >
                  {entity.name}
                  <span className="subtle" style={{ marginLeft: "auto", fontSize: 10 }}>{entity.kind}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
