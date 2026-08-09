import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Activity, Brain, Database, Gauge, Search } from "lucide-react";
import { api } from "../api/client";
import type { CursorPage, Health, Memory, Metrics } from "../api/types";
import { Badge, Card, ErrorState, Loading } from "../components/ui";
import { money, relativeTime } from "../lib/format";

export function Overview() {
  const health = useQuery({ queryKey: ["health"], queryFn: () => api<Health>("/v1/admin/health") });
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<Metrics>("/v1/admin/metrics") });
  const memories = useQuery({ queryKey: ["memories", "recent"], queryFn: () => api<CursorPage<Memory>>("/v1/memories?limit=8") });
  if (health.isLoading || metrics.isLoading) return <Loading label="Reading service state…" />;
  if (health.error || metrics.error || !health.data || !metrics.data) return <ErrorState error={health.error ?? metrics.error} />;
  return <>
    <div className="page-header"><div><span className="eyebrow">MEMORY, NOT WORKFLOW</span><h1>Memory overview</h1><p>Authoritative storage, derived indexes, model spend, and recent neutral observations.</p></div><Link to="/search" className="button button-secondary"><Search size={14} /> Search</Link></div>
    <div className="metric-grid">
      <Metric icon={<Brain size={18} />} label="Indexed memories" value={health.data.qdrant.memories.toLocaleString()} />
      <Metric icon={<Database size={18} />} label="Raw evidence" value={health.data.qdrant.raw.toLocaleString()} />
      <Metric icon={<Activity size={18} />} label="Queued index writes" value={health.data.outbox.pending.toLocaleString()} />
      <Metric icon={<Gauge size={18} />} label="Month spend + reserve" value={money(metrics.data.month_spend_usd + metrics.data.month_reserved_usd)} />
    </div>
    <Card style={{ marginTop: 20 }}>
      <div className="card-header"><div><h2>Recent memories</h2><p>Assistant and agent claims remain stored for audit but are excluded from normal retrieval.</p></div><Link to="/memories">Browse all →</Link></div>
      {!memories.data?.items.length ? <p className="quiet-empty">No active memories yet.</p> : memories.data.items.map((memory) => <div className="list-row" key={memory.id}>
        <span className="list-primary"><strong>{memory.text}</strong><span>{relativeTime(memory.updated_at)}</span></span>
        <Badge>{memory.kind}</Badge><Badge>{memory.source_role}</Badge>
      </div>)}
    </Card>
  </>;
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return <div className="metric-card"><span className="metric-icon">{icon}</span><span className="metric-label">{label}</span><strong>{value}</strong></div>;
}
