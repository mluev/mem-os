import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, RefreshCw, ServerCog, ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import { useMe } from "../api/stats";
import type { Backups, Health, JobQueued, Jobs, Metrics } from "../api/types";
import { Badge, Button, Card, ErrorState, Loading } from "../components/ui";
import { money, relativeTime } from "../lib/format";

export function Ops() {
  const client = useQueryClient();
  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const [eraseConfirm, setEraseConfirm] = useState("");
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/v1/admin/health"), enabled: isAdmin, refetchInterval: 15_000 });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metrics>("/v1/admin/metrics"), refetchInterval: 15_000 });
  const jobList = useQuery({ queryKey: ["jobs"], queryFn: () => api<Jobs>("/v1/jobs?limit=50"), refetchInterval: 3_000 });
  const backups = useQuery({ queryKey: ["backups"], queryFn: () => api<Backups>("/v1/admin/backups"), enabled: isAdmin });
  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: object }) => api<JobQueued>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
    onSuccess: async (value) => {
      toast.success(value.status === "cancel_requested" ? "Cancellation requested" : value.job_id ? `Job ${value.job_id.slice(0, 8)} queued` : value.reason ?? value.status);
      await client.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) => toast.error(error.message),
  });
  if (me.isLoading || metrics.isLoading) return <Loading />;
  if (me.error || metrics.error || !metrics.data) return <ErrorState error={me.error ?? metrics.error} />;
  const counts = metrics.data.index_parity;
  const countComparison = counts.qdrant_active == null ? "Unavailable" : counts.database_active === counts.qdrant_active ? "Counts match" : "Counts differ";
  return <>
    <div className="page-header"><div><span className="eyebrow">OPERATIONS</span><h1>Health and maintenance</h1><p>Jobs, usage, export, and confirmed erasure.</p></div><Button variant="secondary" onClick={() => { if (isAdmin) { void health.refetch(); void backups.refetch(); } void metrics.refetch(); void jobList.refetch(); }}><RefreshCw size={14} /> Refresh</Button></div>
    <div className="ops-grid">
      {isAdmin ? <Card><div className="card-header"><div><h2>Runtime</h2><p>Schema and derived indexes.</p></div><ServerCog size={16} /></div>{health.isLoading ? <Loading /> : health.error || !health.data ? <ErrorState error={health.error} /> : <div className="card-body health-lines"><Line label="Schema" value={String(health.data.database.schema_version ?? "—")} /><Line label="Qdrant" value={health.data.qdrant.available ? "Available" : "Degraded"} /><Line label="Memory points" value={String(health.data.qdrant.memories ?? "—")} /><Line label="Raw points" value={String(health.data.qdrant.raw ?? "—")} /><Line label="Queued index writes" value={String(health.data.outbox.pending)} /><Line label="Embedding revision" value={health.data.embedder.revision.slice(0, 12)} /></div>}</Card> : null}
      <Card><div className="card-header"><div><h2>{isAdmin ? "Usage and diagnostics" : "Your usage"}</h2><p>Spend and retrieval performance.</p></div></div><div className="card-body health-lines"><Line label="Month spend" value={money(metrics.data.month_spend_usd)} /><Line label="Reserved" value={money(metrics.data.month_reserved_usd)} /><Line label="Search p95" value={metrics.data.search_latency_ms.p95 == null ? "—" : `${metrics.data.search_latency_ms.p95} ms`} /><Line label="Feedback labels" value={String(metrics.data.feedback_labels)} />{isAdmin ? <><Line label="Index counts" value={countComparison} /><Line label="Active database / index" value={`${counts.database_active} / ${counts.qdrant_active ?? "—"}`} /><Line label="Backup age" value={metrics.data.backup_freshness_seconds == null ? "No backup" : `${Math.round(metrics.data.backup_freshness_seconds / 3600)} h`} /></> : null}</div></Card>
      <Card style={{ gridColumn: "1 / -1" }}><div className="card-header"><div><h2>Long operations</h2><p>Each action creates a durable, cancellable job with history.</p></div></div><div className="card-body page-actions">{isAdmin ? <Button variant="secondary" onClick={() => action.mutate({ path: "/v1/admin/reindex" })}>Reindex</Button> : null}<Button variant="secondary" onClick={() => action.mutate({ path: "/v1/admin/consolidate", body: { dry_run: true } })}>Consolidation preview</Button>{isAdmin ? <Button variant="secondary" onClick={() => action.mutate({ path: "/v1/admin/reextract" })}>Re-extraction report</Button> : null}<Button variant="secondary" onClick={() => action.mutate({ path: "/v1/export" })}><Download size={14} /> Export</Button></div></Card>
      <Card style={{ gridColumn: "1 / -1" }}><div className="card-header"><div><h2>Recent jobs</h2><p>Newest first; refreshes every three seconds.</p></div></div>{jobList.isLoading ? <Loading /> : jobList.error ? <ErrorState error={jobList.error} /> : !jobList.data?.items.length ? <p className="quiet-empty">No jobs yet.</p> : jobList.data.items.map((job) => <div className="list-row" key={job.id}><span className="list-primary"><strong>{job.kind}</strong><span>{job.id.slice(0, 8)} · {relativeTime(job.created_at)}</span></span><Badge>{job.status}</Badge>{job.error ? <span className="form-error">{job.error}</span> : null}{["queued", "running"].includes(job.status) ? <Button variant="secondary" size="sm" disabled={action.isPending} onClick={() => action.mutate({ path: `/v1/jobs/${job.id}/cancel` })}>Cancel</Button> : null}</div>)}</Card>
      {isAdmin ? <Card style={{ gridColumn: "1 / -1" }}><div className="card-header"><div><h2>Verified backups</h2><p>Daily and weekly recovery points; protected checkpoints are retained separately.</p></div></div>{backups.isLoading ? <Loading /> : backups.error ? <ErrorState error={backups.error} /> : !backups.data?.items.length ? <p className="quiet-empty">No verified backup yet.</p> : backups.data.items.slice(0, 8).map((backup) => <div className="list-row" key={backup.id}><span className="list-primary"><strong>{backup.kind}</strong><span>{backup.verified_at ? `Verified ${relativeTime(backup.verified_at)}` : "Not verified"}</span></span>{backup.protected ? <Badge>protected</Badge> : <Badge>retained</Badge>}</div>)}</Card> : null}
      <Card style={{ gridColumn: "1 / -1" }}><div className="card-header"><div><h2>Permanent erasure</h2><p>Erases your private data and its search index. Shared memories are retained; the service refuses erasure while shared authorship needs resolution.</p></div><ShieldAlert size={16} /></div><div className="card-body"><label>Type ERASE ALL DATA<input className="input" value={eraseConfirm} onChange={(event) => setEraseConfirm(event.target.value)} /></label><Button variant="destructive" disabled={!me.data || eraseConfirm !== "ERASE ALL DATA" || action.isPending} onClick={() => action.mutate({ path: `/v1/users/${encodeURIComponent(me.data!.id)}/erase`, body: { confirm: "ERASE ALL DATA" } })}>Erase my private data</Button></div></Card>
    </div>
  </>;
}

function Line({ label, value }: { label: string; value: string }) { return <div className="health-line"><span>{label}</span><strong>{value}</strong></div>; }
