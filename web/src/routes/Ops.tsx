import { lazy, Suspense, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, PlayCircle, RefreshCw, ServerCog } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import { TAU } from "../lib/constants";
import { money } from "../lib/format";
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
  Card,
  ErrorState,
  Loading,
  Tabs,
  TabsList,
  TabsTrigger,
} from "../components/ui";

const CostChart = lazy(() => import("../components/CostChart"));

interface Health {
  ok: boolean;
  qdrant: boolean;
  embedder: boolean;
  embedder_device: string;
  memories: number;
  raw: number;
  db: string;
  index_dirty: boolean;
  reindex: ReindexJob;
}
interface ReindexJob {
  status: "idle" | "running" | "complete" | "error";
  phase?: string;
  completed?: number;
  total?: number;
  error?: string;
}
interface Stats {
  backlog: { sessions: number; messages: number; windows: number; estimated_cost_usd: number; basis: string };
  cost: { month_spend_usd: number; monthly_limit_usd: number; total_usd: number; by_kind: Record<string, number>; calls: number; errors: number };
  health: { sqlite_active: number; qdrant_memories: number; index_drift: number; sqlite_raw_eligible: number; qdrant_raw: number; raw_drift: number };
}
interface Daily { items: Array<Record<string, string | number>>; days: number }

export function Ops() {
  const [days, setDays] = useState(30);
  const [confirmReindex, setConfirmReindex] = useState(false);
  const client = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/healthz"), refetchInterval: 15_000 });
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/v1/admin/stats") });
  const daily = useQuery({ queryKey: ["costs-daily", days], queryFn: () => api<Daily>(`/v1/admin/costs/daily?days=${days}`) });
  const job = useQuery({ queryKey: ["reindex-status"], queryFn: () => api<ReindexJob>("/v1/admin/reindex/status"), refetchInterval: (query) => query.state.data?.status === "running" ? 1000 : false });
  const start = useMutation({
    mutationFn: () => api<ReindexJob>("/v1/admin/reindex/start", { method: "POST" }),
    onSuccess: async () => {
      setConfirmReindex(false);
      toast.success("Reindex started");
      await client.invalidateQueries({ queryKey: ["reindex-status"] });
    },
    onError: (error) => toast.error(error.message),
  });
  return <>
    <div className="page-header"><div><span className="eyebrow">SERVICE OPERATIONS</span><h1>Health, spend, maintenance</h1><p>Everything that can drift or cost money, with SQLite remaining the source of truth.</p></div><Button variant="secondary" onClick={() => { void health.refetch(); void stats.refetch(); }}><RefreshCw size={13} /> Refresh</Button></div>
    {health.error || stats.error ? <ErrorState error={health.error ?? stats.error} /> : null}
    <div className="ops-grid">
      <Card>
        <div className="card-header"><div><h2>Runtime health</h2><p>Polled every 15 seconds.</p></div>{health.data?.ok ? <Badge><CheckCircle2 size={11} /> healthy</Badge> : <Badge className="low-confidence"><AlertTriangle size={11} /> attention</Badge>}</div>
        <div className="card-body health-lines">
          <HealthLine label="Qdrant" value={health.data?.qdrant ? "connected" : "offline"} />
          <HealthLine label="Embedder" value={health.data?.embedder ? health.data.embedder_device : "not ready"} />
          <HealthLine label="Memory points" value={String(health.data?.memories ?? "—")} />
          <HealthLine label="Raw points" value={String(health.data?.raw ?? "—")} />
          <HealthLine label="Index drift" value={String(stats.data?.health.index_drift ?? "—")} />
          <HealthLine label="Raw drift" value={String(stats.data?.health.raw_drift ?? "—")} />
        </div>
      </Card>
      <Card>
        <div className="card-header"><div><h2>Judge spend</h2><p>Current month against the hard service limit.</p></div><Badge>{stats.data?.cost.calls ?? 0} calls</Badge></div>
        <div className="card-body">
          <strong style={{ fontSize: 26 }}>{money(stats.data?.cost.month_spend_usd)}</strong>
          <span className="subtle"> / ${stats.data?.cost.monthly_limit_usd.toFixed(2) ?? "—"}</span>
          <div className="distribution" style={{ marginTop: 14 }}><span style={{ width: `${Math.min(100, ((stats.data?.cost.month_spend_usd ?? 0) / (stats.data?.cost.monthly_limit_usd ?? 1)) * 100)}%`, background: "var(--amber)" }} /></div>
          <dl className="config-table">{Object.entries(stats.data?.cost.by_kind ?? {}).map(([kind, value]) => <><dt key={`${kind}-k`}>{kind}</dt><dd key={`${kind}-v`}>{money(value)}</dd></>)}</dl>
        </div>
      </Card>
      <Card style={{ gridColumn: "1 / -1" }}>
        <div className="card-header"><div><h2>Daily cost</h2><p>Zero-filled calendar days, stacked by judge-run kind.</p></div><Tabs value={String(days)} onValueChange={(value) => setDays(Number(value))}><TabsList>{[7, 30, 90].map((value) => <TabsTrigger key={value} value={String(value)}>{value}d</TabsTrigger>)}</TabsList></Tabs></div>
        <div className="card-body"><Suspense fallback={<Loading />}><CostChart data={daily.data?.items ?? []} /></Suspense></div>
      </Card>
      <Card>
        <div className="card-header"><div><h2>Extraction backlog</h2><p>Estimate uses live mean token usage when available.</p></div><Database size={16} className="subtle" /></div>
        <div className="card-body">
          <div className="stats-grid" style={{ gridTemplateColumns: "repeat(2,1fr)", margin: 0 }}>
            <div><span className="eyebrow">MESSAGES</span><strong>{stats.data?.backlog.messages.toLocaleString() ?? "—"}</strong></div>
            <div><span className="eyebrow">CALLS</span><strong>{stats.data?.backlog.windows.toLocaleString() ?? "—"}</strong></div>
            <div><span className="eyebrow">EST. COST</span><strong>{money(stats.data?.backlog.estimated_cost_usd)}</strong></div>
            <div><span className="eyebrow">SESSIONS</span><strong>{stats.data?.backlog.sessions ?? "—"}</strong></div>
          </div>
          <p className="subtle" style={{ fontSize: 9 }}>{stats.data?.backlog.basis}</p>
        </div>
      </Card>
      <Card>
        <div className="card-header"><div><h2>Maintenance</h2><p>Rebuild derived indexes from SQLite.</p></div><ServerCog size={16} className="subtle" /></div>
        <div className="card-body">
          {job.data?.status === "running" ? <>
            <p><strong>Reindexing {job.data.phase}</strong></p>
            <div className="distribution"><span style={{ width: `${job.data.total ? (job.data.completed ?? 0) / job.data.total * 100 : 4}%`, background: "var(--blue)" }} /></div>
            <p className="mono subtle">{job.data.completed ?? 0} / {job.data.total ?? 0}</p>
          </> : <Button variant="secondary" onClick={() => setConfirmReindex(true)}><PlayCircle size={13} /> Rebuild vector index</Button>}
          <div className="page-actions" style={{ marginTop: 12 }}><Button variant="secondary" disabled>Reextract</Button><Button variant="secondary" disabled>Consolidate</Button></div>
          <p className="subtle" style={{ fontSize: 9 }}>Reextract and consolidate are not implemented in the service yet.</p>
        </div>
      </Card>
      <Card style={{ gridColumn: "1 / -1" }}>
        <div className="card-header"><div><h2>Retrieval constants</h2><p>The UI curve and production scorer share these documented values.</p></div></div>
        <div className="card-body"><dl className="config-table"><dt>dedup cosine</dt><dd>0.90</dd>{Object.entries(TAU).map(([type, tau]) => <><dt key={`${type}-k`}>τ {type}</dt><dd key={`${type}-v`}>{tau} days</dd></>)}</dl></div>
      </Card>
    </div>
    <AlertDialog open={confirmReindex} onOpenChange={setConfirmReindex}><AlertDialogContent>
      <AlertDialogHeader><AlertDialogTitle>Rebuild the vector index?</AlertDialogTitle><AlertDialogDescription>This drops both Qdrant collections and rebuilds them from SQLite. Only active memories return. Search can return nothing for about two minutes, and memory edits are disabled until completion.</AlertDialogDescription></AlertDialogHeader>
      <AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => start.mutate()} disabled={start.isPending}>Start reindex</AlertDialogAction></AlertDialogFooter>
    </AlertDialogContent></AlertDialog>
  </>;
}

function HealthLine({ label, value }: { label: string; value: string }) {
  return <div className="health-line"><span>{label}</span><strong>{value}</strong></div>;
}
