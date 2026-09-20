import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { RetrievalRuns } from "../api/types";
import { Badge, Button, Card, ErrorState, Loading } from "../components/ui";
import { relativeTime } from "../lib/format";

export function Feedback() {
  const client = useQueryClient();
  const runs = useQuery({ queryKey: ["retrieval-runs"], queryFn: () => api<RetrievalRuns>("/v1/retrieval-runs?limit=30") });
  const feedback = useMutation({
    mutationFn: ({ runId, memoryId, useful, correct }: { runId: string; memoryId: string; useful: boolean; correct: boolean }) => api(`/v1/retrieval-runs/${runId}/feedback`, { method: "POST", body: JSON.stringify({ memory_id: memoryId, useful, correct }) }),
    onSuccess: async () => { toast.success("Feedback recorded"); await client.invalidateQueries({ queryKey: ["retrieval-runs"] }); },
    onError: (error) => toast.error(error.message),
  });
  if (runs.isLoading) return <Loading />;
  if (runs.error || !runs.data) return <ErrorState error={runs.error} />;
  return <><div className="page-header"><div><span className="eyebrow">PRIVACY-SAFE TELEMETRY</span><h1>Recent retrievals</h1><p>Queries are not stored. Review returned memories and label only what you explicitly judge.</p></div></div>
    {!runs.data.items.length ? <Card><p className="quiet-empty">No retrieval runs yet.</p></Card> : runs.data.items.map((run) => <Card key={run.id} style={{ marginBottom: 14 }}><div className="card-header"><div><h2>{relativeTime(run.created_at)}</h2><p>{run.policy_id} · {run.used_tokens} tokens · {run.timings.total_ms?.toFixed(1) ?? "—"} ms</p></div><Badge>{run.abstained ? "abstained" : `${run.results.length} results`}</Badge></div>{run.results.map((result) => <div className="list-row" key={result.memory_id}><span className="list-primary"><strong>{result.text ?? result.memory_id}</strong><span>rank {result.rank} · {result.kind} · {result.source_role}</span></span>{result.feedback ? <Badge>{result.feedback.correct ? "correct" : "wrong"}</Badge> : <span className="page-actions"><Button variant="secondary" size="sm" onClick={() => feedback.mutate({ runId: run.id, memoryId: result.memory_id, useful: true, correct: true })}><Check size={13} /> Useful</Button><Button variant="secondary" size="sm" onClick={() => feedback.mutate({ runId: run.id, memoryId: result.memory_id, useful: false, correct: false })}><X size={13} /> Wrong</Button></span>}</div>)}</Card>)}
  </>;
}
