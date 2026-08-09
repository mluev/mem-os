import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, ChevronRight } from "lucide-react";
import { api } from "../api/client";
import type { JudgeRun, OffsetPage } from "../api/types";
import { Badge, Card, EmptyState, ErrorState, Loading } from "../components/ui";
import { duration, money, relativeTime } from "../lib/format";

export function JudgeRuns() {
  const query = useQuery({ queryKey: ["judge-runs"], queryFn: () => api<OffsetPage<JudgeRun>>("/v1/admin/judge-runs?limit=100") });
  return <><div className="page-header"><div><span className="eyebrow">MODEL AUDIT</span><h1>Judge runs</h1><p>Exact inputs, structured outputs, cost, latency, and errors.</p></div></div><Card>{query.isLoading ? <Loading /> : query.error ? <ErrorState error={query.error} /> : !query.data?.items.length ? <EmptyState title="No model calls" body="Empty history is normal before evidence extraction runs." /> : query.data.items.map((run) => <Link className="list-row" key={run.id} to="/judge-runs/$runId" params={{ runId: String(run.id) }}><span className="list-primary"><strong>#{run.id} · {run.kind}</strong><span>{relativeTime(run.created_at)} · {run.model}</span></span><Badge>{money(run.cost_usd)}</Badge><Badge>{duration(run.latency_ms)}</Badge>{run.error ? <Badge>error</Badge> : null}<ChevronRight size={15} /></Link>)}</Card></>;
}

export function JudgeRunDetail() {
  const { runId } = useParams({ strict: false }) as { runId: string };
  const query = useQuery({ queryKey: ["judge-run", runId], queryFn: () => api<JudgeRun>(`/v1/admin/judge-runs/${runId}`) });
  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorState error={query.error} />;
  const run = query.data;
  return <><div className="page-header"><div><Link to="/judge-runs" className="eyebrow"><ArrowLeft size={11} /> JUDGE RUNS</Link><h1>Run #{run.id}</h1><p>{run.prompt_version} · {run.model}</p></div></div>{run.error ? <div className="health-banner"><strong>{run.error}</strong></div> : null}<div className="detail-grid"><Card><div className="card-header"><h2>Redacted input</h2></div><pre className="raw-json">{pretty(run.input_json)}</pre></Card><Card><div className="card-header"><h2>Structured output</h2></div><pre className="raw-json">{pretty(run.output_json)}</pre></Card></div></>;
}

function pretty(value: string | null): string {
  if (!value) return "(none)";
  try { return JSON.stringify(JSON.parse(value), null, 2); } catch { return value; }
}
