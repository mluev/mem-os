import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Plus, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, queryString } from "../api/client";
import type { CursorPage, Memory } from "../api/types";
import { Badge, Button, Card, EmptyState, ErrorState, Input, Loading, Textarea } from "../components/ui";
import { relativeTime } from "../lib/format";

export function Memories() {
  const search = useSearch({ from: "/memories" });
  const navigate = useNavigate({ from: "/memories" });
  const client = useQueryClient();
  const [text, setText] = useState("");
  const [kind, setKind] = useState("observation");
  const page = useQuery({
    queryKey: ["memories", search.kind, search.cursor],
    queryFn: () => api<CursorPage<Memory>>(`/v1/memories${queryString({ limit: 50, kind: search.kind, cursor: search.cursor })}`),
  });
  const create = useMutation({
    mutationFn: () => api("/v1/memories", { method: "POST", body: JSON.stringify({ text, kind, context: {}, tags: [], importance: 0.6, confidence: 1, source_role: "manual" }) }),
    onSuccess: async () => { setText(""); toast.success("Memory stored"); await client.invalidateQueries({ queryKey: ["memories"] }); },
    onError: (error) => toast.error(error.message),
  });
  function submit(event: FormEvent) { event.preventDefault(); if (text.trim() && kind.trim()) create.mutate(); }
  return <>
    <div className="page-header"><div><span className="eyebrow">NEUTRAL MEMORY STORE</span><h1>Memories</h1><p>Free-form kinds, tags, context, trust, and validity.</p></div><Button variant="secondary" aria-label="Refresh memories" onClick={() => void page.refetch()}><RefreshCw size={14} /> Refresh</Button></div>
    <Card>
      <form className="card-body" onSubmit={submit}>
        <label>Kind<Input value={kind} onChange={(event) => setKind(event.target.value)} maxLength={64} /></label>
        <label>Memory<Textarea value={text} onChange={(event) => setText(event.target.value)} maxLength={2000} rows={3} /></label>
        <Button type="submit" disabled={create.isPending || !text.trim()}><Plus size={14} /> Store memory</Button>
      </form>
    </Card>
    <Card style={{ marginTop: 16 }}>
      {page.isLoading ? <Loading /> : page.error ? <ErrorState error={page.error} /> : !page.data?.items.length ? <EmptyState title="No memories" body="Store an observation or ingest evidence first." /> : page.data.items.map((memory) => <article className="list-row" key={memory.id}>
        <span className="list-primary"><strong>{memory.text}</strong><span>{relativeTime(memory.updated_at)} · {memory.id.slice(0, 8)}</span></span>
        <Badge>{memory.kind}</Badge><Badge>{memory.source_role}</Badge>
      </article>)}
      {page.data?.next_cursor ? <div className="pagination"><Button variant="secondary" onClick={() => void navigate({ search: { ...search, cursor: page.data?.next_cursor ?? undefined } })}>Next page</Button></div> : null}
    </Card>
  </>;
}
