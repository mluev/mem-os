/**
 * One fact, in full, in a drawer.
 *
 * The drawer is driven by the `memory` search param rather than by component
 * state, which is why a link to a single fact works from the listing, the
 * review queue, an entity page or a session transcript without any of them
 * knowing about this file. A screen either lets the drawer read and clear that
 * param itself, or passes `memoryId`/`onClose` when it wants to do something
 * extra on close — the listing returns focus to the row that opened it.
 *
 * Corrections are optimistic: a PATCH carries the revision the reader was
 * looking at, and a 409 means somebody else got there first. That case is
 * handled as a merge rather than as an error: the reader's wording is kept,
 * the other version is fetched and shown beside it as a word diff, and the
 * next save carries the new revision.
 */

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArchiveRestore,
  Check,
  MoreHorizontal,
  ShieldAlert,
  Trash2,
  Undo2,
} from "lucide-react";
import { toast } from "sonner";
import { z } from "zod";
import { ApiError, api } from "../api/client";
import type { MemoryDetail, TeamMemory } from "../api/types";
import { relativeTime } from "../lib/format";
import { Field, LifecycleBadge, RatioField, ReviewBadge, ValueSelect } from "./MemoryFields";
import { DiffText, EvidenceTab, HistoryTab, RelationsTab } from "./MemoryTabs";
import { entityOptions, scopeOptions, useMemoryOptions } from "./MemoryOptions";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  ErrorState,
  Input,
  Loading,
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
} from "./ui";

const schema = z.object({
  text: z.string().trim().min(1, "A memory needs something to remember").max(2000),
  kind: z.string().trim().min(1, "A memory needs a kind").max(64),
  scope: z.string().min(1),
  subject: z.string(),
  importance: z.number().min(0).max(1),
  confidence: z.number().min(0).max(1),
  tags: z
    .string()
    .refine((value) => parseTags(value).length <= 20, "At most 20 tags")
    .refine(
      (value) => parseTags(value).every((tag) => tag.length <= 64),
      "A tag can hold 64 characters",
    ),
});

type Values = z.infer<typeof schema>;

function parseTags(value: string): string[] {
  return [...new Set(value.split(",").map((tag) => tag.trim()).filter(Boolean))];
}

function formValues(memory: TeamMemory): Values {
  return {
    text: memory.text,
    kind: memory.kind,
    scope: memory.scope_slug ?? "",
    subject: memory.subject_slug ?? "",
    importance: memory.importance,
    confidence: memory.confidence,
    tags: memory.tags.join(", "),
  };
}

export function MemoryDrawer({
  memoryId: controlledId,
  onClose,
}: {
  memoryId?: string | null;
  onClose?: () => void;
} = {}) {
  const search = useSearch({ strict: false }) as { memory?: string };
  const navigate = useNavigate();
  const memoryId = controlledId !== undefined ? controlledId : (search.memory ?? null);

  /** Point the drawer at another fact without leaving the screen behind it. */
  function open(next: string | undefined): void {
    void navigate({
      to: ".",
      search: (prev) => ({ ...(prev as Record<string, unknown>), memory: next }),
      replace: next === undefined,
    });
  }

  function close(): void {
    if (onClose) onClose();
    else open(undefined);
  }

  return (
    <Sheet
      open={memoryId != null}
      onOpenChange={(next) => {
        if (!next) close();
      }}
    >
      <SheetContent className="sheet">
        {memoryId ? <DrawerBody memoryId={memoryId} onClose={close} onOpen={open} /> : null}
      </SheetContent>
    </Sheet>
  );
}

type Tab = "overview" | "evidence" | "history" | "relations";

function DrawerBody({
  memoryId,
  onClose,
  onOpen,
}: {
  memoryId: string;
  onClose: () => void;
  onOpen: (id: string) => void;
}) {
  const client = useQueryClient();
  const options = useMemoryOptions();
  const [tab, setTab] = useState<Tab>("overview");
  const [conflict, setConflict] = useState<string | null>(null);
  const [move, setMove] = useState<{ scope: string; rest: Record<string, unknown> } | null>(null);
  const [declining, setDeclining] = useState(false);

  const detail = useQuery({
    queryKey: ["memory", memoryId],
    queryFn: () => api<MemoryDetail>(`/v1/memories/${encodeURIComponent(memoryId)}`),
  });
  const memory = detail.data?.memory;

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      text: "",
      kind: "",
      scope: "",
      subject: "",
      importance: 0.6,
      confidence: 0.9,
      tags: "",
    },
  });

  // The server is the truth after every load and every successful write. The
  // 409 path deliberately does not go through here: it reseeds the form itself
  // so the reader's unsaved wording survives.
  const loadedRef = useRef<string>("");
  useEffect(() => {
    if (!memory) return;
    const stamp = `${memory.id}:${memory.revision}`;
    if (loadedRef.current === stamp) return;
    loadedRef.current = stamp;
    form.reset(formValues(memory));
  }, [memory, form]);

  useEffect(() => {
    setTab("overview");
    setConflict(null);
  }, [memoryId]);

  async function refresh(): Promise<void> {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["memory", memoryId] }),
      client.invalidateQueries({ queryKey: ["memories"] }),
      client.invalidateQueries({ queryKey: ["stats"] }),
    ]);
  }

  const save = useMutation({
    mutationFn: (patch: Record<string, unknown>) =>
      api(`/v1/memories/${encodeURIComponent(memoryId)}`, {
        method: "PATCH",
        body: JSON.stringify({ ...patch, expected_revision: memory?.revision }),
      }),
    onSuccess: async () => {
      setConflict(null);
      toast.success("Saved");
      await refresh();
    },
    onError: async (error: Error) => {
      if (!(error instanceof ApiError) || error.status !== 409) {
        toast.error(error.message);
        return;
      }
      const mine = form.getValues("text");
      const fresh = await detail.refetch();
      const theirs = fresh.data?.memory;
      if (theirs) {
        loadedRef.current = `${theirs.id}:${theirs.revision}`;
        form.reset({ ...formValues(theirs), text: mine }, { keepDirty: true });
        setConflict(theirs.text);
      }
      toast.error("Someone else changed this memory first", {
        description: "Your wording is kept below, beside theirs.",
      });
    },
  });

  const review = useMutation({
    mutationFn: (decision: "confirm" | "decline" | "undo") =>
      api(`/v1/memories/${encodeURIComponent(memoryId)}/review`, {
        method: "POST",
        body: JSON.stringify({ decision, expected_revision: memory?.revision }),
      }),
    onSuccess: async (_result, decision) => {
      if (decision === "decline") {
        toast.success("Marked wrong", {
          description: "It will not be retrieved again.",
          action: { label: "Undo", onClick: () => review.mutate("undo") },
        });
      } else {
        toast.success(decision === "confirm" ? "Confirmed" : "Review undone");
      }
      setDeclining(false);
      await refresh();
    },
    onError: (error: Error) =>
      toast.error(
        error instanceof ApiError && error.status === 409
          ? "Someone else reviewed this first — reopen it to see where it landed"
          : error.message,
      ),
  });

  const lifecycle = useMutation({
    mutationFn: (next: "archived" | "active") =>
      next === "archived"
        ? api(`/v1/memories/${encodeURIComponent(memoryId)}`, { method: "DELETE" })
        : api(`/v1/memories/${encodeURIComponent(memoryId)}/restore`, { method: "POST" }),
    onSuccess: async (_result, next) => {
      toast.success(next === "archived" ? "Archived" : "Restored", {
        description: next === "archived" ? "Nothing is deleted; you can restore it." : undefined,
        action:
          next === "archived"
            ? { label: "Undo", onClick: () => lifecycle.mutate("active") }
            : undefined,
      });
      await refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (detail.isLoading) return <Loading label="Loading memory" />;
  if (detail.error || !memory) {
    return (
      <div className="sheet-body">
        <ErrorState error={detail.error} retry={() => void detail.refetch()} />
      </div>
    );
  }

  const writable = memory.writable !== false;
  const values = form.watch();
  const scopeChanged = Boolean(values.scope) && values.scope !== memory.scope_slug;

  function submit(input: Values): void {
    const patch: Record<string, unknown> = {};
    if (input.text.trim() !== memory!.text) patch.text = input.text.trim();
    if (input.kind.trim() !== memory!.kind) patch.kind = input.kind.trim();
    if (input.importance !== memory!.importance) patch.importance = input.importance;
    if (input.confidence !== memory!.confidence) patch.confidence = input.confidence;
    const tags = parseTags(input.tags);
    if (tags.join("\u0000") !== memory!.tags.join("\u0000")) patch.tags = tags;
    const subject = input.subject || "";
    if (subject !== (memory!.subject_slug ?? "")) {
      if (subject) patch.subject = subject;
      else patch.clear_subject = true;
    }
    if (input.scope && input.scope !== memory!.scope_slug) {
      // Moving a memory changes who can read it, so it is never a side effect
      // of pressing Save.
      setMove({ scope: input.scope, rest: patch });
      return;
    }
    if (!Object.keys(patch).length) {
      toast.success("Nothing to save");
      return;
    }
    save.mutate(patch);
  }

  return (
    <Tabs value={tab} onValueChange={(next) => setTab(next as Tab)} asChild>
      <form
        style={{ display: "flex", flexDirection: "column", height: "100%" }}
        onSubmit={form.handleSubmit(submit)}
        noValidate
      >
        <div className="sheet-head">
          <div className="sheet-head-row">
            <div style={{ minWidth: 0 }}>
              <span className="eyebrow">
                {memory.kind} · REVISION {memory.revision}
              </span>
              <SheetTitle asChild>
                <h2>{memory.text}</h2>
              </SheetTitle>
              <SheetDescription className="subtle" style={{ display: "block", marginTop: 8 }}>
                In {memory.scope ?? "an unknown space"}
                {memory.subject ? `, about ${memory.subject}` : ""}
                {memory.author ? `, written by ${memory.author}` : ""} · updated{" "}
                {relativeTime(memory.updated_at)}
              </SheetDescription>
            </div>
            <span className="page-actions" style={{ flexWrap: "wrap", justifyContent: "flex-end" }}>
              <ReviewBadge status={memory.review_status} />
              <LifecycleBadge status={memory.status} />
            </span>
          </div>
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="history">History</TabsTrigger>
            <TabsTrigger value="relations">Relations</TabsTrigger>
          </TabsList>
        </div>

        <div className="sheet-body">
          <TabsContent value="overview">
            {!writable ? (
              <p className="subtle" style={{ marginTop: 0 }}>
                This fact lives in a space you can read but not write, so the fields below are
                locked.
              </p>
            ) : null}
            {conflict !== null ? (
              <div className="danger-zone" style={{ marginBottom: 18 }}>
                <h3>Someone else edited this fact</h3>
                <p>
                  Your wording is still in the field. Here is what the store holds now, with your
                  changes marked.
                </p>
                <DiffText before={conflict} after={values.text} />
                <span className="page-actions" style={{ marginTop: 10 }}>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      form.setValue("text", conflict, { shouldDirty: true });
                      setConflict(null);
                    }}
                  >
                    Use theirs
                  </Button>
                  <Button type="button" size="sm" variant="secondary" onClick={() => setConflict(null)}>
                    Keep mine
                  </Button>
                </span>
              </div>
            ) : null}
            <div className="form-grid">
              <Field
                label="Memory"
                htmlFor="memory-text"
                full
                error={form.formState.errors.text?.message}
              >
                <Textarea
                  id="memory-text"
                  rows={4}
                  maxLength={2000}
                  disabled={!writable}
                  {...form.register("text")}
                />
              </Field>
              <Field label="Kind" htmlFor="memory-kind" error={form.formState.errors.kind?.message}>
                <Input
                  id="memory-kind"
                  list="memory-kinds"
                  maxLength={64}
                  disabled={!writable}
                  {...form.register("kind")}
                />
                <datalist id="memory-kinds">
                  {options.kinds.map((kind) => (
                    <option key={kind} value={kind} />
                  ))}
                </datalist>
              </Field>
              <Field label="Subject" hint="Who or what this fact is about.">
                <ValueSelect
                  label="Subject"
                  value={values.subject}
                  noneLabel="No subject"
                  disabled={!writable}
                  options={entityOptions(options.entities)}
                  onChange={(next) => form.setValue("subject", next, { shouldDirty: true })}
                />
              </Field>
              <Field
                label="Scope"
                hint={
                  scopeChanged
                    ? "Saving will ask you to confirm the move."
                    : "Whose space holds this fact, and so who can read it."
                }
              >
                <ValueSelect
                  label="Scope"
                  value={values.scope}
                  disabled={!writable}
                  options={scopeOptions(options.writableScopes)}
                  onChange={(next) => form.setValue("scope", next, { shouldDirty: true })}
                />
              </Field>
              <Field
                label="Tags"
                htmlFor="memory-tags"
                error={form.formState.errors.tags?.message}
                hint="Comma separated."
              >
                <Input id="memory-tags" disabled={!writable} {...form.register("tags")} />
              </Field>
              <RatioField
                label="Importance"
                value={values.importance}
                disabled={!writable}
                onChange={(next) => form.setValue("importance", next, { shouldDirty: true })}
              />
              <RatioField
                label="Confidence"
                value={values.confidence}
                disabled={!writable}
                onChange={(next) => form.setValue("confidence", next, { shouldDirty: true })}
              />
            </div>
          </TabsContent>

          <TabsContent value="evidence">
            <EvidenceTab memoryId={memoryId} active={tab === "evidence"} />
          </TabsContent>

          <TabsContent value="history">
            <HistoryTab memory={memory} active={tab === "history"} onOpen={onOpen} />
          </TabsContent>

          <TabsContent value="relations">
            <RelationsTab memory={memory} />
          </TabsContent>
        </div>

        <div className="sheet-footer" style={{ justifyContent: "space-between" }}>
          <span className="page-actions">
            {memory.review_status === "pending" ? (
              <>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={!writable || review.isPending}
                  onClick={() => review.mutate("confirm")}
                >
                  <Check size={13} /> Confirm
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={!writable || review.isPending}
                  onClick={() => setDeclining(true)}
                >
                  Decline
                </Button>
              </>
            ) : memory.review_status === "declined" ? (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!writable || review.isPending}
                onClick={() => review.mutate("undo")}
              >
                <Undo2 size={13} /> Undo decline
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!writable || review.isPending}
                onClick={() => setDeclining(true)}
              >
                <AlertTriangle size={13} /> This fact is wrong
              </Button>
            )}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" size="sm" variant="ghost" aria-label="More actions">
                  <MoreHorizontal size={15} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                {memory.status === "archived" ? (
                  <DropdownMenuItem
                    disabled={!writable}
                    onSelect={() => lifecycle.mutate("active")}
                  >
                    <ArchiveRestore size={14} /> Restore
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem
                    disabled={!writable}
                    onSelect={() => lifecycle.mutate("archived")}
                  >
                    <Trash2 size={14} /> Archive
                  </DropdownMenuItem>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  disabled={!writable}
                  onSelect={() => setMove({ scope: memory.scope_slug ?? "", rest: {} })}
                >
                  <ShieldAlert size={14} /> Move to another space…
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </span>
          <span className="page-actions">
            <Button type="button" variant="secondary" onClick={onClose}>
              Close
            </Button>
            <Button type="submit" disabled={!writable || save.isPending || !form.formState.isDirty}>
              {save.isPending ? "Saving…" : "Save changes"}
            </Button>
          </span>
        </div>

        <DeclineDialog
          open={declining}
          text={memory.text}
          pending={review.isPending}
          onOpenChange={setDeclining}
          onConfirm={() => review.mutate("decline")}
        />
        <MoveScopeDialog
          move={move}
          memory={memory}
          scopes={scopeOptions(options.writableScopes)}
          pending={save.isPending}
          onOpenChange={(open) => {
            if (!open) setMove(null);
          }}
          onConfirm={(scope, rest) => {
            setMove(null);
            save.mutate({ ...rest, scope, move_scope: true });
          }}
        />
      </form>
    </Tabs>
  );
}

function DeclineDialog({
  open,
  text,
  pending,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  text: string;
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>This fact is wrong</DialogTitle>
          <DialogDescription>
            Declining says the statement itself is false, or that it should never have been
            remembered — the store stops retrieving it anywhere. That is a different claim from
            marking a search result unhelpful, which only says this fact was the wrong answer to
            that one question and adjusts ranking. If the wording is merely off, edit the text
            instead.
          </DialogDescription>
        </DialogHeader>
        <blockquote className="message-content" style={{ margin: 0 }}>
          {text}
        </blockquote>
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" disabled={pending} onClick={onConfirm}>
            Yes, this fact is wrong
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MoveScopeDialog({
  move,
  memory,
  scopes,
  pending,
  onOpenChange,
  onConfirm,
}: {
  move: { scope: string; rest: Record<string, unknown> } | null;
  memory: TeamMemory;
  scopes: { value: string; label: string }[];
  pending: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (scope: string, rest: Record<string, unknown>) => void;
}) {
  const [scope, setScope] = useState(move?.scope ?? "");
  useEffect(() => setScope(move?.scope ?? ""), [move]);
  const target = scopes.find((option) => option.value === scope);
  return (
    <Dialog open={move !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Move this memory to another space</DialogTitle>
          <DialogDescription>
            A memory’s scope decides who can read it. Moving it out of{" "}
            <strong>{memory.scope ?? "its space"}</strong> can expose it to people who cannot see
            it today, or hide it from people who rely on it.
          </DialogDescription>
        </DialogHeader>
        <Field label="New scope">
          <ValueSelect label="New scope" value={scope} options={scopes} onChange={setScope} />
        </Field>
        <DialogFooter>
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={pending || !scope || scope === memory.scope_slug}
            onClick={() => onConfirm(scope, move?.rest ?? {})}
          >
            Move to {target?.label ?? "…"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
