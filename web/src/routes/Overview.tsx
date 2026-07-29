import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  Brain,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Coins,
  Database,
  EyeOff,
  Layers3,
  MessagesSquare,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api } from "../api/client";
import type { ActivityDay, DashboardStats, JudgeRun, Memory, MemoryList, Page } from "../api/types";
import { money, relativeTime } from "../lib/format";
import {
  ActivityChart,
  ActivityHeatmap,
  ConfidenceChart,
  MemoryTypeActivityChart,
} from "../components/AnalyticsCharts";
import {
  Badge,
  Card,
  ErrorState,
  Loading,
  Tabs,
  TabsList,
  TabsTrigger,
  TypeBadge,
} from "../components/ui";

export function Overview() {
  const [days, setDays] = useState(30);
  const stats = useQuery({
    queryKey: ["stats", days],
    queryFn: () => api<DashboardStats>(`/v1/admin/stats?days=${days}`),
  });
  const recent = useQuery({
    queryKey: ["memories", "recent"],
    queryFn: () => api<MemoryList>("/v1/memories?limit=5"),
  });
  const runs = useQuery({
    queryKey: ["judge-runs", "recent"],
    queryFn: () => api<Page<JudgeRun>>("/v1/admin/judge-runs?limit=5"),
  });
  const activity = useQuery({
    queryKey: ["activity", 365],
    queryFn: () => api<{ days: number; items: ActivityDay[] }>("/v1/admin/activity?days=365"),
    staleTime: 60_000,
  });
  if (stats.isLoading) return <Loading label="Reading the memory system…" />;
  if (stats.error || !stats.data) return <ErrorState error={stats.error} retry={() => void stats.refetch()} />;

  const data = stats.data;
  const active = data.memories.by_status.active ?? 0;
  const processed = data.corpus.messages - data.corpus.unprocessed;
  const processedRatio = data.corpus.messages ? processed / data.corpus.messages : 1;
  const retrievalRatio = active ? (active - data.memories.never_retrieved) / active : 1;
  const monthRatio = data.cost.monthly_limit_usd
    ? data.cost.month_spend_usd / data.cost.monthly_limit_usd
    : 0;
  const healthy = data.health.index_drift === 0 && data.health.raw_drift === 0 && !data.health.index_dirty;
  const periodMemories = data.analytics.daily.reduce((sum, item) => sum + item.memories, 0);
  const periodMessages = data.analytics.daily.reduce((sum, item) => sum + item.messages, 0);
  const triage = [
    { label: "Never retrieved", detail: "Potentially noisy or too specific", count: data.memories.never_retrieved, to: "/ui/memories?never_retrieved=true", icon: EyeOff },
    { label: "Low confidence", detail: "Below the 0.60 review threshold", count: data.memories.low_confidence, to: "/ui/memories?sort=confidence&order=asc", icon: AlertTriangle },
    { label: "Expiring soon", detail: "Validity ends within seven days", count: data.memories.expiring_7d, to: "/ui/memories?expired_validity=true", icon: Clock3 },
    { label: "Superseded", detail: "Replaced by newer knowledge", count: data.memories.superseded, to: "/ui/memories?status=superseded", icon: Layers3 },
  ];

  return (
    <div className="overview-page">
      <div className="page-header overview-heading">
        <div>
          <div className="heading-kicker"><span className={healthy ? "health-dot ok" : "health-dot bad"} /> Live memory system</div>
          <h1>Memory overview</h1>
          <p>Corpus growth, retrieval quality, spend, and the signals that deserve your attention.</p>
        </div>
        <div className="page-actions">
          <Tabs value={String(days)} onValueChange={(value) => setDays(Number(value))}>
            <TabsList aria-label="Analytics range">
              {[7, 30, 90].map((value) => <TabsTrigger key={value} value={String(value)}>{value} days</TabsTrigger>)}
            </TabsList>
          </Tabs>
          <Link to="/memories" className="button button-secondary">Browse memories <ArrowRight size={14} /></Link>
        </div>
      </div>

      <div className="metric-grid dashboard-stagger">
        <Link to="/memories" className="metric-card metric-primary">
          <span className="metric-icon"><Brain size={19} /></span>
          <span className="metric-label">Active memories</span>
          <strong>{active.toLocaleString()}</strong>
          <small><Sparkles size={12} /> {periodMemories.toLocaleString()} added in {days} days</small>
        </Link>
        <Link to="/sessions" className="metric-card">
          <span className="metric-icon"><MessagesSquare size={18} /></span>
          <span className="metric-label">Corpus processed</span>
          <strong>{Math.round(processedRatio * 100)}%</strong>
          <small>{processed.toLocaleString()} of {data.corpus.messages.toLocaleString()} messages</small>
        </Link>
        <Link to="/memories" search={{ never_retrieved: true } as never} className="metric-card">
          <span className="metric-icon"><Activity size={18} /></span>
          <span className="metric-label">Retrieval coverage</span>
          <strong>{Math.round(retrievalRatio * 100)}%</strong>
          <small>{data.memories.never_retrieved.toLocaleString()} memories never surfaced</small>
        </Link>
        <Link to="/ops" className="metric-card">
          <span className="metric-icon"><Coins size={18} /></span>
          <span className="metric-label">Month spend</span>
          <strong>{money(data.cost.month_spend_usd)}</strong>
          <small>{Math.round(monthRatio * 100)}% of ${data.cost.monthly_limit_usd.toFixed(0)} limit</small>
        </Link>
      </div>

      <div className="analytics-grid dashboard-stagger">
        <Card className="activity-panel">
          <div className="card-header">
            <div><h2>Corpus activity</h2><p>{periodMessages.toLocaleString()} messages observed during this period.</p></div>
            <div className="chart-legend"><span><i className="legend-blue" />Messages</span><span><i className="legend-green" />Memories</span></div>
          </div>
          <div className="card-body chart-body"><ActivityChart data={data.analytics.daily} /></div>
        </Card>
        <Card className="agent-panel">
          <div className="card-header"><div><h2>Agent activity</h2><p>Top sources across this corpus.</p></div><Bot size={17} className="subtle" /></div>
          <div className="agent-list">
            {data.analytics.agents.length ? data.analytics.agents.map((agent) => (
              <div className="agent-row" key={agent.agent_id}>
                <span className="agent-avatar">{agent.agent_id.slice(0, 1).toUpperCase()}</span>
                <span className="agent-copy"><strong>{agent.agent_id}</strong><small>{agent.sessions} sessions · {agent.messages} messages</small></span>
                <span className="agent-memory"><strong>{agent.memories}</strong><small>memories</small></span>
              </div>
            )) : <div className="quiet-empty">Agent activity appears after sessions are ingested.</div>}
          </div>
        </Card>
      </div>

      <div className="activity-overview-grid dashboard-stagger">
        <Card className="quality-panel">
          <div className="card-header"><div><h2>Confidence profile</h2><p>Active memories by judge confidence.</p></div></div>
          <div className="card-body quality-body">
            <ConfidenceChart confidence={data.analytics.confidence} total={active} />
            <div className="quality-legend">
              {(["high", "medium", "low"] as const).map((bucket) => (
                <div key={bucket}><span className={`quality-dot quality-${bucket}`} /><span>{bucket}</span><strong>{data.analytics.confidence[bucket] ?? 0}</strong></div>
              ))}
            </div>
          </div>
        </Card>

        <Card className="activity-calendar-panel">
          <div className="card-header">
            <div><h2>Activity history</h2><p>A year of messages and memories.</p></div>
            <span className="activity-calendar-range"><CalendarDays size={16} /> 365 days</span>
          </div>
          <div className="card-body">
            {activity.isLoading ? <Loading label="Reading yearly activity…" /> : activity.data ? <ActivityHeatmap data={activity.data.items} /> : <div className="quiet-empty">Yearly activity is unavailable.</div>}
          </div>
        </Card>
      </div>

      <div className="insight-grid dashboard-stagger">
        <Card className="type-activity-panel">
          <div className="card-header">
            <div><h2>Memory type activity</h2><p>New memories over time. Select types to compare their creation patterns.</p></div>
          </div>
          <div className="card-body">
            {activity.isLoading ? <Loading label="Reading memory activity…" /> : activity.data ? <MemoryTypeActivityChart data={activity.data.items} /> : <div className="quiet-empty">Memory activity is unavailable.</div>}
          </div>
        </Card>
        <Card className="triage-panel">
          <div className="card-header"><div><h2>Needs attention</h2><p>Review signals ordered by impact.</p></div><Badge className={healthy ? "status-good" : "status-warn"}>{healthy ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}{healthy ? "Indexes in sync" : "Index drift"}</Badge></div>
          <div className="triage-list">
            {triage.map(({ label, detail, count, to, icon: Icon }) => (
              <a className="triage-row" href={to} key={label}>
                <span className="triage-icon"><Icon size={15} /></span>
                <span className="triage-copy"><strong>{label}</strong><span>{detail}</span></span>
                <span className="triage-count">{count}</span>
                <ArrowRight size={15} className="subtle" />
              </a>
            ))}
          </div>
        </Card>
      </div>

      <div className="overview-grid dashboard-stagger">
        <Card>
          <div className="card-header"><div><h2>Recent memories</h2><p>Newly added or recently confirmed facts.</p></div><Link to="/memories" className="header-link">View all <ArrowRight size={13} /></Link></div>
          {recent.isLoading ? <Loading /> : (
            <div className="triage-list">
              {(recent.data?.memories ?? []).map((memory: Memory) => (
                <Link className="triage-row" to="/memories" search={{ sel: memory.id } as never} key={memory.id}>
                  <TypeBadge type={memory.type} />
                  <span className="triage-copy"><strong>{memory.text}</strong><span>{relativeTime(memory.updated_at)} · {memory.scope}</span></span>
                </Link>
              ))}
            </div>
          )}
        </Card>
        <Card>
          <div className="card-header"><div><h2>Recent judge runs</h2><p>The latest extraction decisions and cost.</p></div><Link to="/judge-runs" className="header-link">View all <ArrowRight size={13} /></Link></div>
          {runs.isLoading ? <Loading /> : (
            <div className="triage-list">
              {(runs.data?.items ?? []).map((run) => (
                <Link className="triage-row" to="/judge-runs/$runId" params={{ runId: String(run.id) }} key={run.id}>
                  <span className="triage-icon"><Database size={14} /></span>
                  <span className="triage-copy"><strong>{run.kind} · {run.model}</strong><span>{run.ops.length} operations · {relativeTime(run.created_at)}</span></span>
                  <span className="triage-count">{money(run.cost_usd)}</span>
                </Link>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="system-note">
        <ShieldCheck size={15} />
        <span>SQLite is the source of truth. Charts are computed from live local data and never leave this machine.</span>
      </div>
    </div>
  );
}
