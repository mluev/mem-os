import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download, Pencil, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { CursorPage, ReplayBatch, ReplayItem } from "../api/types";
import { Badge, Button, Card, ErrorState, Input, Loading } from "../components/ui";
import { relativeTime } from "../lib/format";

export function Replay() {
  const client = useQueryClient();
  const batches = useQuery({ queryKey: ["replay-batches"], queryFn: () => api<CursorPage<ReplayBatch>>("/v1/replay-batches") });
  const [selected, setSelected] = useState("");
  const [promotionConfirm, setPromotionConfirm] = useState("");
  const batchId = selected || batches.data?.items[0]?.id || "";
  const items = useQuery({ queryKey: ["replay-items", batchId], enabled: Boolean(batchId), queryFn: () => api<CursorPage<ReplayItem>>(`/v1/replay-batches/${batchId}/items`) });
  const mutate = useMutation({
    mutationFn: ({ path, method = "POST", body }: { path: string; method?: string; body?: object }) => api(path, { method, body: body ? JSON.stringify(body) : undefined }),
    onSuccess: async () => { toast.success("Replay review updated"); await client.invalidateQueries({ queryKey: ["replay-batches"] }); await client.invalidateQueries({ queryKey: ["replay-items", batchId] }); },
    onError: (error) => toast.error(error.message),
  });
  if (batches.isLoading) return <Loading />;
  if (batches.error || !batches.data) return <ErrorState error={batches.error} />;
  const batch = batches.data.items.find((value) => value.id === batchId);
  return <><div className="page-header"><div><span className="eyebrow">V7 SHADOW REPLAY</span><h1>Review queue</h1><p>Every change needs an accept, reject, or edit decision. Evidence, trust, target, and provenance cannot be edited.</p></div>{batch ? <Button variant="secondary" onClick={() => mutate.mutate({ path: `/v1/replay-batches/${batch.id}/export` })}><Download size={14} /> Export audit</Button> : null}</div>
    <Card style={{ marginBottom: 16 }}><div className="card-header"><div><h2>Replay batches</h2><p>Applying re-extraction creates a shadow batch; it never changes live data.</p></div></div>{!batches.data.items.length ? <p className="quiet-empty">No replay batches yet. Start one from Operations.</p> : batches.data.items.map((value) => <button className="list-row replay-batch-button" type="button" key={value.id} onClick={() => setSelected(value.id)}><span className="list-primary"><strong>{value.model} · {value.id.slice(0, 8)}</strong><span>{relativeTime(value.created_at)} · {value.prompt_version}</span></span><Badge>{value.status}</Badge></button>)}</Card>
    {batch ? <Card><div className="card-header"><div><h2>Decisions</h2><p>{batch.id} · approval is bound to a checksum.</p></div><span className="page-actions"><Button variant="secondary" onClick={() => mutate.mutate({ path: `/v1/replay-batches/${batch.id}/validate` })}><ShieldCheck size={14} /> Validate gates</Button>{batch.approval_checksum && batch.status === "validated" ? <Button onClick={() => mutate.mutate({ path: `/v1/replay-batches/${batch.id}/approve`, body: { checksum: batch.approval_checksum } })}>Approve manifest</Button> : null}</span></div>{items.isLoading ? <Loading /> : items.data?.items.map((item) => <ReplayRow key={item.id} item={item} review={(decision, edits) => mutate.mutate({ path: `/v1/replay-batches/${batch.id}/items/${item.id}/review`, method: "PATCH", body: { decision, edits } })} />)}{batch.status === "approved" && batch.approval_checksum ? <div className="danger-zone"><h3>Promote reviewed manifest</h3><p>This opens a maintenance window, applies only reviewed decisions, validates a new exact-ID index, and rolls back automatically on failure.</p><label>Type PROMOTE<Input value={promotionConfirm} onChange={(event) => setPromotionConfirm(event.target.value)} /></label><Button variant="destructive" disabled={promotionConfirm !== "PROMOTE"} onClick={() => mutate.mutate({ path: `/v1/replay-batches/${batch.id}/promote`, body: { checksum: batch.approval_checksum, confirm: "PROMOTE" } })}>Promote with rollback protection</Button></div> : null}</Card> : null}
  </>;
}

function ReplayRow({ item, review }: { item: ReplayItem; review: (decision: string, edits?: object) => void }) {
  const data = item.reviewed ?? item.proposed ?? item.before;
  const [text, setText] = useState(data?.text ?? "");
  const [editing, setEditing] = useState(false);
  return <article className="replay-item"><div className="score-head"><span><Badge>{item.action}</Badge> <Badge>{item.source_role}</Badge> <Badge>{item.decision}</Badge></span><span className="page-actions"><Button size="sm" variant="secondary" onClick={() => review("accepted")}><Check size={13} /> Accept</Button><Button size="sm" variant="secondary" onClick={() => review("rejected")}><X size={13} /> Reject</Button>{item.action !== "DELETE" ? <Button size="sm" variant="secondary" onClick={() => setEditing((value) => !value)}><Pencil size={13} /> Edit</Button> : null}</span></div>{editing ? <div className="card-body"><textarea className="input replay-textarea" value={text} maxLength={200} onChange={(event) => setText(event.target.value)} /><Button onClick={() => { review("edited", { text }); setEditing(false); }}>Save edit</Button></div> : <p>{data?.text ?? "Archive this memory"}</p>}<details><summary>Exact evidence ({item.evidence.length})</summary>{item.evidence.map((evidence) => <blockquote key={`${evidence.message_id}-${evidence.start_char}`}>{evidence.excerpt}</blockquote>)}</details></article>;
}
