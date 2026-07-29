import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Copy,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api, queryString } from "../api/client";
import type { JudgeOp, Memory, MemoryList, Message } from "../api/types";
import { MEMORY_TYPES } from "../lib/constants";
import { guessLang, relativeTime, shortId } from "../lib/format";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Badge,
  Button,
  Checkbox,
  DatePicker,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  ErrorState,
  Importance,
  Input,
  Label,
  Loading,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  Slider,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  TypeBadge,
} from "../components/ui";

type MemorySearch = {
  q?: string;
  type?: string;
  status?: string;
  scope?: string;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  sel?: string;
  never_retrieved?: boolean;
  expired_validity?: boolean;
  min_importance?: number;
  max_importance?: number;
};

const LIMIT = 50;

export function Memories() {
  const search = useSearch({ strict: false }) as MemorySearch;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [typedQuery, setTypedQuery] = useState(search.q ?? "");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [adding, setAdding] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (typedQuery !== (search.q ?? "")) {
        void navigate({ to: "/memories", search: (old: MemorySearch) => ({ ...old, q: typedQuery || undefined, page: undefined }) });
      }
    }, 280);
    return () => window.clearTimeout(timer);
  }, [typedQuery, search.q, navigate]);

  const page = search.page ?? 1;
  const params = {
    limit: LIMIT,
    offset: (page - 1) * LIMIT,
    q: search.q,
    type: search.type,
    status: search.status ?? "active",
    scope: search.scope,
    sort: search.sort ?? "updated_at",
    order: search.order ?? "desc",
    never_retrieved: search.never_retrieved,
    expired_validity: search.expired_validity,
    min_importance: search.min_importance,
    max_importance: search.max_importance,
  };
  const memories = useQuery({
    queryKey: ["memories", params],
    queryFn: () => api<MemoryList>(`/v1/memories${queryString(params)}`),
    placeholderData: (previous) => previous,
  });
  const totalPages = Math.max(1, Math.ceil((memories.data?.total ?? 0) / LIMIT));
  const updateSearch = (patch: Partial<MemorySearch>) =>
    navigate({ to: "/memories", search: (old: MemorySearch) => ({ ...old, ...patch, page: patch.page ?? undefined }) });
  const setSort = (sort: string) => {
    const nextOrder = search.sort === sort && search.order === "desc" ? "asc" : "desc";
    void updateSearch({ sort, order: nextOrder, page: undefined });
  };
  const toggleAll = () => {
    const pageIds = memories.data?.memories.map((memory) => memory.id) ?? [];
    setSelected(selected.size === pageIds.length ? new Set() : new Set(pageIds));
  };
  const bulk = useMutation({
    mutationFn: (body: object) => api("/v1/admin/memories/bulk", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: async () => {
      toast.success("Memory selection updated");
      setSelected(new Set());
      await queryClient.invalidateQueries({ queryKey: ["memories"] });
      await queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (error) => toast.error(error.message),
  });

  return (
    <>
      <div className="page-header">
        <div>
          <span className="eyebrow">MEMORY CORPUS</span>
          <h1>Browse and triage facts</h1>
          <p>Substring search across SQLite. For semantic ranking and score analysis, use the Search playground.</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" onClick={() => void memories.refetch()}><RefreshCw size={15} /> Refresh</Button>
          <Button onClick={() => setAdding(true)}><Plus size={13} /> Add memory</Button>
        </div>
      </div>
      <div className="filter-bar">
        <label className="search-field">
          <Search size={14} />
          <Input className="search-input" value={typedQuery} onChange={(event) => setTypedQuery(event.target.value)} placeholder="Find exact text…" aria-label="Search memory text" />
          {typedQuery ? <Button variant="ghost" size="icon" onClick={() => setTypedQuery("")}><X size={13} /></Button> : null}
        </label>
        <Select value={search.type ?? "all"} onValueChange={(value) => void updateSearch({ type: value === "all" ? undefined : value })}><SelectTrigger className="filter-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All types</SelectItem>{MEMORY_TYPES.map((type) => <SelectItem key={type} value={type}>{type}</SelectItem>)}</SelectContent></Select>
        <Select value={search.scope ?? "all"} onValueChange={(value) => void updateSearch({ scope: value === "all" ? undefined : value })}><SelectTrigger className="filter-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All scopes</SelectItem><SelectItem value="user">user</SelectItem><SelectItem value="project">project</SelectItem><SelectItem value="task">task</SelectItem></SelectContent></Select>
        <Select value={search.status ?? "active"} onValueChange={(value) => void updateSearch({ status: value === "active" ? undefined : value })}><SelectTrigger className="filter-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">Active</SelectItem><SelectItem value="expired">Expired</SelectItem><SelectItem value="superseded">Superseded</SelectItem><SelectItem value="all">All states</SelectItem></SelectContent></Select>
        {Object.values(search).some((value) => value !== undefined) ? (
          <Button variant="ghost" size="sm" onClick={() => void navigate({ to: "/memories", search: {} })}>Reset</Button>
        ) : null}
      </div>
      <div className="table-shell">
        {memories.isLoading ? <Loading label="Loading memories…" /> : memories.error ? (
          <ErrorState error={memories.error} retry={() => void memories.refetch()} />
        ) : !memories.data?.memories.length ? (
          <EmptyState
            title={memories.data?.total === 0 && !search.q ? "No memories yet" : search.q ? "No exact text match" : "No memories match these filters"}
            body={search.q ? "This is substring search, not semantic search. Try the playground for meaning-based retrieval." : "Reset the filters, or backfill conversations after configuring the judge key."}
          />
        ) : (
          <>
            <table className="data-table">
              <thead><tr>
                <th className="col-check"><Checkbox checked={selected.size === memories.data.memories.length && selected.size > 0} onCheckedChange={toggleAll} aria-label="Select page" /></th>
                <th className="col-type"><SortHead label="Type" field="type" current={search} action={setSort} /></th>
                <th>Memory</th>
                <th className="col-scope">Scope</th>
                <th className="col-number"><SortHead label="Importance" field="importance" current={search} action={setSort} /></th>
                <th className="col-number"><SortHead label="Confidence" field="confidence" current={search} action={setSort} /></th>
                <th className="col-number"><SortHead label="Retrieved" field="retrieval_count" current={search} action={setSort} /></th>
                <th className="col-updated"><SortHead label="Updated" field="updated_at" current={search} action={setSort} /></th>
                <th className="col-actions" />
              </tr></thead>
              <tbody>
                {memories.data.memories.map((memory) => (
                  <tr key={memory.id} className={`row-${memory.status}`} onClick={() => void updateSearch({ sel: memory.id })}>
                    <td onClick={(event) => event.stopPropagation()}><Checkbox checked={selected.has(memory.id)} onCheckedChange={() => setSelected((current) => { const next = new Set(current); next.has(memory.id) ? next.delete(memory.id) : next.add(memory.id); return next; })} aria-label={`Select ${memory.text}`} /></td>
                    <td><TypeBadge type={memory.type} />{memory.status !== "active" ? <Badge style={{ marginTop: 4 }}>{memory.status}</Badge> : null}</td>
                    <td><div className="memory-text" lang={guessLang(memory.text)}>{memory.text}</div>{memory.superseded_by ? <span className="subtle mono">→ {shortId(memory.superseded_by)}</span> : null}</td>
                    <td><div className="scope-cell"><strong>{memory.scope}</strong><small>{memory.scope_key ?? "global"}</small></div></td>
                    <td><Importance value={memory.importance} /></td>
                    <td className={memory.confidence < .6 ? "mono low-confidence" : "mono"}>{memory.confidence.toFixed(2)}</td>
                    <td><span className="mono">{memory.retrieval_count}</span><br /><span className="subtle">{relativeTime(memory.last_retrieved_at)}</span></td>
                    <td className="subtle">{relativeTime(memory.updated_at)}</td>
                    <td onClick={(event) => event.stopPropagation()}><DropdownMenu><DropdownMenuTrigger asChild><Button variant="ghost" size="icon" className="table-action-button" aria-label={`Actions for ${memory.text}`}><MoreHorizontal size={22} strokeWidth={2.5} /></Button></DropdownMenuTrigger><DropdownMenuContent align="end"><DropdownMenuLabel>Memory actions</DropdownMenuLabel><DropdownMenuItem onSelect={() => void updateSearch({ sel: memory.id })}>Open details</DropdownMenuItem><DropdownMenuSeparator /><DropdownMenuItem onSelect={() => bulk.mutate({ ids: [memory.id], op: memory.status === "active" ? "expire" : "restore" })}>{memory.status === "active" ? "Expire" : "Restore"}</DropdownMenuItem><DropdownMenuItem className="low-confidence" onSelect={() => void updateSearch({ sel: memory.id })}>Delete permanently…</DropdownMenuItem></DropdownMenuContent></DropdownMenu></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="pagination">
              <span>{memories.data.total.toLocaleString()} memories · page {page} of {totalPages}</span>
              <div className="pagination-actions">
                <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => void updateSearch({ page: page - 1 })}><ChevronLeft size={13} /> Previous</Button>
                <Button variant="secondary" size="sm" disabled={page >= totalPages} onClick={() => void updateSearch({ page: page + 1 })}>Next <ChevronRight size={13} /></Button>
              </div>
            </div>
          </>
        )}
      </div>
      {selected.size ? (
        <div className="floating-actions">
          <strong>{selected.size} selected</strong>
          <Button variant="secondary" size="sm" onClick={() => bulk.mutate({ ids: [...selected], op: "expire" })}>Expire</Button>
          <Button variant="secondary" size="sm" onClick={() => bulk.mutate({ ids: [...selected], op: "restore" })}>Restore</Button>
          <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>Clear</Button>
        </div>
      ) : null}
      {search.sel ? <MemorySheet id={search.sel} close={() => void updateSearch({ sel: undefined })} /> : null}
      {adding ? <AddMemory close={() => setAdding(false)} /> : null}
    </>
  );
}

function SortHead({ label, field, current, action }: { label: string; field: string; current: MemorySearch; action: (field: string) => void }) {
  return <Button variant="ghost" size="sm" onClick={() => action(field)}>{label}{current.sort === field ? current.order === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} /> : null}</Button>;
}

const memorySchema = z.object({
  text: z.string().min(1),
  type: z.enum(MEMORY_TYPES),
  scope: z.enum(["user", "project", "task"]),
  scope_key: z.string(),
  agent_id: z.string(),
  importance: z.number().min(0).max(1),
  confidence: z.number().min(0).max(1),
  valid_until: z.string(),
});
type MemoryForm = z.infer<typeof memorySchema>;

interface Provenance {
  memory: Memory;
  messages: Message[];
  judge_run: { id: number; model: string; created_at: string } | null;
  judge_ops: JudgeOp[];
  superseded_by: Memory | null;
  supersedes: Memory[];
}

function MemorySheet({ id, close }: { id: string; close: () => void }) {
  const client = useQueryClient();
  const [tab, setTab] = useState<"details" | "provenance" | "danger">("details");
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [discardOpen, setDiscardOpen] = useState(false);
  const data = useQuery({
    queryKey: ["memory", id],
    queryFn: () => api<Provenance>(`/v1/memories/${id}/sources`),
  });
  const memory = data.data?.memory;
  const form = useForm<MemoryForm>({
    resolver: zodResolver(memorySchema),
    values: memory ? {
      text: memory.text, type: memory.type, scope: memory.scope,
      scope_key: memory.scope_key ?? "", agent_id: memory.agent_id ?? "",
      importance: memory.importance, confidence: memory.confidence,
      valid_until: memory.valid_until ?? "",
    } : undefined,
  });
  const patch = useMutation({
    mutationFn: (body: object) => api(`/v1/memories/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: async () => {
      toast.success("Memory saved");
      form.reset(form.getValues());
      await client.invalidateQueries({ queryKey: ["memories"] });
      await client.invalidateQueries({ queryKey: ["memory", id] });
      await client.invalidateQueries({ queryKey: ["stats"] });
    },
    onError: (error) => toast.error(error.message),
  });
  const submit = form.handleSubmit((values) => patch.mutate({
    ...values,
    scope_key: values.scope === "user" ? null : values.scope_key || null,
    agent_id: values.agent_id || null,
    valid_until: values.valid_until || null,
    expected_updated_at: memory?.updated_at,
  }));
  const safeClose = () => {
    if (form.formState.isDirty) setDiscardOpen(true);
    else close();
  };
  return (
    <>
    <Sheet open onOpenChange={(open) => { if (!open) safeClose(); }}>
      <SheetContent className="sheet">
        <div className="sheet-head">
          <div className="sheet-head-row"><div><span className="eyebrow">MEMORY {shortId(id)}</span><h2>{memory?.text ?? "Loading…"}</h2></div></div>
          <Tabs value={tab} onValueChange={(value) => setTab(value as typeof tab)}><TabsList><TabsTrigger value="details">Details</TabsTrigger><TabsTrigger value="provenance">Provenance</TabsTrigger><TabsTrigger value="danger">Danger zone</TabsTrigger></TabsList></Tabs>
        </div>
        <div className="sheet-body">
          {data.isLoading ? <Loading /> : data.error || !memory ? <ErrorState error={data.error} /> : tab === "details" ? (
            <form id="memory-form" onSubmit={submit}>
              <div className="form-grid">
                <Label className="field field-full"><span>Memory text</span><Textarea {...form.register("text")} lang={guessLang(form.watch("text") ?? "")} /></Label>
                <div className="field"><Label>Type</Label><Controller control={form.control} name="type" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{MEMORY_TYPES.map((type) => <SelectItem key={type} value={type}>{type}</SelectItem>)}</SelectContent></Select>} /></div>
                <div className="field"><Label>Scope</Label><Controller control={form.control} name="scope" render={({ field }) => <Select value={field.value} onValueChange={field.onChange}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="user">user</SelectItem><SelectItem value="project">project</SelectItem><SelectItem value="task">task</SelectItem></SelectContent></Select>} /></div>
                <Label className="field"><span>Scope key</span><Input {...form.register("scope_key")} disabled={form.watch("scope") === "user"} placeholder="Project or task id" /></Label>
                <Label className="field"><span>Agent</span><Input {...form.register("agent_id")} placeholder="chat" /></Label>
                <div className="field"><span className="field-inline-value"><Label>Importance</Label><b className="mono">{Number(form.watch("importance")).toFixed(2)}</b></span><Controller control={form.control} name="importance" render={({ field }) => <Slider min={0} max={1} step={.05} value={[field.value]} onValueChange={([value]) => field.onChange(value)} />} /></div>
                <div className="field"><span className="field-inline-value"><Label>Confidence</Label><b className="mono">{Number(form.watch("confidence")).toFixed(2)}</b></span><Controller control={form.control} name="confidence" render={({ field }) => <Slider min={0} max={1} step={.05} value={[field.value]} onValueChange={([value]) => field.onChange(value)} />} /></div>
                <div className="field field-full"><Label>Valid until</Label><Controller control={form.control} name="valid_until" render={({ field }) => <DatePicker value={field.value} onChange={field.onChange} />} /></div>
              </div>
              <dl className="metadata-grid">
                <div><dt>ID</dt><dd className="mono">{memory.id} <Button type="button" variant="ghost" size="icon" onClick={() => void navigator.clipboard.writeText(memory.id)}><Copy size={11} /></Button></dd></div>
                <div><dt>Status</dt><dd><Badge>{memory.status}</Badge></dd></div>
                <div><dt>Created</dt><dd>{new Date(memory.created_at).toLocaleString()}</dd></div>
                <div><dt>Updated</dt><dd>{new Date(memory.updated_at).toLocaleString()}</dd></div>
                <div><dt>Retrieved</dt><dd>{memory.retrieval_count} · {relativeTime(memory.last_retrieved_at)}</dd></div>
                <div><dt>Extraction</dt><dd><Badge>{memory.extraction_version}</Badge>{memory.judge_run_id ? ` · run ${memory.judge_run_id}` : ""}</dd></div>
              </dl>
            </form>
          ) : tab === "provenance" ? <ProvenancePanel data={data.data!} /> : (
            <div className="danger-zone">
              <h3>{memory.status === "active" ? "Delete memory" : "Restore or delete"}</h3>
              <p>Messages and judge-run audit records are always kept. A normal delete expires the fact and can be undone.</p>
              <div className="page-actions">
                {memory.status !== "active" ? <RestoreButton memory={memory} close={close} /> : null}
                <Button variant="destructive" onClick={() => setDeleteOpen(true)}><Trash2 size={13} /> Delete</Button>
              </div>
            </div>
          )}
        </div>
        {tab === "details" && memory ? <div className="sheet-footer"><Button variant="secondary" onClick={safeClose}>Cancel</Button><Button form="memory-form" type="submit" disabled={!form.formState.isDirty || patch.isPending}>{patch.isPending ? "Saving…" : "Save changes"}</Button></div> : null}
      </SheetContent>
    </Sheet>
    {deleteOpen && memory ? <DeleteDialog memory={memory} close={() => setDeleteOpen(false)} done={close} /> : null}
    <AlertDialog open={discardOpen} onOpenChange={setDiscardOpen}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle><AlertDialogDescription>Your edits to this memory have not been saved.</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Keep editing</AlertDialogCancel><AlertDialogAction onClick={close}>Discard changes</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog>
    </>
  );
}

function ProvenancePanel({ data }: { data: Provenance }) {
  if (data.memory.extraction_version === "manual") return <EmptyState title="Added by hand" body="No judge was involved, so this memory has no source window or reasoning." />;
  const matching = data.judge_ops.find((op) => op.matches_this_memory);
  return <>
    <span className="eyebrow">JUDGE DECISION</span>
    <p className="subtle">Run {data.judge_run?.id ?? "unavailable"} · {data.judge_run?.model ?? "unknown model"}</p>
    <div className="provenance-reason"><strong>WHY THE JUDGE STORED THIS</strong><p>{matching?.reason || "No reason was recorded in the operation."}</p></div>
    <span className="eyebrow">SOURCE MESSAGES</span>
    <div className="message-list">
      {data.messages.map((message) => <a key={message.id} className="message" href={`/ui/sessions/${message.session_id}?highlight=${message.id}`}><span className="message-role">{message.role}<br />#{message.id}</span><span className="message-content" lang={guessLang(message.content)}>{message.content}</span></a>)}
    </div>
  </>;
}

function DeleteDialog({ memory, close, done }: { memory: Memory; close: () => void; done: () => void }) {
  const client = useQueryClient();
  const [hard, setHard] = useState(false);
  const deletion = useMutation({
    mutationFn: () => api(`/v1/memories/${memory.id}?hard=${hard}`, { method: "DELETE" }),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["memories"] });
      await client.invalidateQueries({ queryKey: ["stats"] });
      toast.success(hard ? "Memory permanently deleted" : "Memory expired", !hard ? {
        action: { label: "Undo", onClick: () => void api(`/v1/memories/${memory.id}`, { method: "PATCH", body: JSON.stringify({ status: "active" }) }).then(() => client.invalidateQueries({ queryKey: ["memories"] })) },
        duration: 8000,
      } : undefined);
      done();
    },
    onError: (error) => toast.error(error.message),
  });
  return <AlertDialog open onOpenChange={(open) => { if (!open) close(); }}><AlertDialogContent>
    <AlertDialogHeader><AlertDialogTitle>{hard ? "Delete permanently?" : "Delete this memory?"}</AlertDialogTitle><AlertDialogDescription>“{memory.text}”</AlertDialogDescription></AlertDialogHeader>
    <Label className="checkbox-row"><Checkbox checked={hard} onCheckedChange={(checked) => setHard(checked === true)} /><span><strong>Delete permanently (cannot be undone)</strong><br /><span className="subtle">Source messages and judge audit records are kept.</span></span></Label>
    <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><Button variant={hard ? "destructive" : "default"} disabled={deletion.isPending} onClick={() => deletion.mutate()}>{hard ? "Delete permanently" : "Delete"}</Button></AlertDialogFooter>
  </AlertDialogContent></AlertDialog>;
}

function RestoreButton({ memory, close }: { memory: Memory; close: () => void }) {
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api(`/v1/memories/${memory.id}`, { method: "PATCH", body: JSON.stringify({ status: "active", expected_updated_at: memory.updated_at }) }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ["memories"] }); toast.success("Memory restored and reindexed"); close(); },
    onError: (error) => toast.error(error.message),
  });
  return <Button variant="secondary" onClick={() => mutation.mutate()} disabled={mutation.isPending}>Restore</Button>;
}

function AddMemory({ close }: { close: () => void }) {
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [type, setType] = useState("fact");
  const mutation = useMutation({
    mutationFn: () => api("/v1/memories", { method: "POST", body: JSON.stringify({ text, type }) }),
    onSuccess: async () => { await client.invalidateQueries({ queryKey: ["memories"] }); toast.success("Memory added"); close(); },
    onError: (error) => toast.error(error.message),
  });
  return <Dialog open onOpenChange={(open) => { if (!open) close(); }}><DialogContent>
    <DialogHeader><DialogTitle>Add a memory</DialogTitle><DialogDescription>Manual facts have no judge provenance. Keep the statement atomic and durable.</DialogDescription></DialogHeader>
    <div className="form-grid"><Label className="field field-full"><span>Memory text</span><Textarea autoFocus value={text} onChange={(event) => setText(event.target.value)} /></Label><div className="field field-full"><Label>Type</Label><Select value={type} onValueChange={setType}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{MEMORY_TYPES.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent></Select></div></div>
    <DialogFooter><Button variant="secondary" onClick={close}>Cancel</Button><Button disabled={!text.trim() || mutation.isPending} onClick={() => mutation.mutate()}>Add memory</Button></DialogFooter>
  </DialogContent></Dialog>;
}
