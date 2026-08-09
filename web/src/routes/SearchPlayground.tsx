import { useState, type FormEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "../api/client";
import type { SearchResult } from "../api/types";
import { Badge, Button, Card, Checkbox, EmptyState, Input, Label } from "../components/ui";

export function SearchPlayground() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [untrusted, setUntrusted] = useState(false);
  const search = useMutation({ mutationFn: () => api<SearchResult>("/v1/memories/search", { method: "POST", body: JSON.stringify({ query, kinds: kind ? [kind] : null, include_untrusted: untrusted, budget_tokens: 800, limit: 30 }) }) });
  function submit(event: FormEvent) { event.preventDefault(); if (query.trim()) search.mutate(); }
  return <>
    <div className="page-header"><div><span className="eyebrow">HYBRID RETRIEVAL</span><h1>Search</h1><p>Dense and BM25 candidates with trust, validity, filters, and a silence threshold.</p></div></div>
    <Card><form className="card-body" onSubmit={submit}><label>Query<Input value={query} onChange={(event) => setQuery(event.target.value)} /></label><label>Kind (optional)<Input value={kind} onChange={(event) => setKind(event.target.value)} /></label><div className="page-actions"><Checkbox id="untrusted" checked={untrusted} onCheckedChange={(value) => setUntrusted(value === true)} /><Label htmlFor="untrusted">Include assistant/agent claims</Label></div><Button type="submit" disabled={!query.trim() || search.isPending}><Search size={14} /> Search</Button></form></Card>
    <Card style={{ marginTop: 16 }}>
      {search.error ? <p className="form-error">{search.error.message}</p> : null}
      {search.data && !search.data.memories.length ? <EmptyState title="No reliable match" body="The policy abstained instead of filling the answer with weak results." /> : search.data?.memories.map((memory) => <article className="list-row" key={memory.id}><span className="list-primary"><strong>{memory.text}</strong><span>score {memory.score.toFixed(3)} · dense {memory.similarity.toFixed(3)} · BM25 {memory.lexical.toFixed(3)}</span></span><Badge>{memory.kind}</Badge><Badge>{memory.source_role}</Badge></article>)}
      {search.data ? <div className="pagination"><span>{search.data.used_tokens} tokens · {search.data.policy_id} · {search.data.took_ms} ms</span></div> : null}
    </Card>
  </>;
}
