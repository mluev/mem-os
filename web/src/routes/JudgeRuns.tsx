import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { AlertCircle, ArrowLeft, ChevronRight, Copy } from "lucide-react";
import { toast } from "sonner";
import { api, queryString } from "../api/client";
import type { JudgeOp, JudgeRun, Memory, Message, Page } from "../api/types";
import { duration, guessLang, money, relativeTime } from "../lib/format";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Tabs,
  TabsList,
  TabsTrigger,
  TypeBadge,
} from "../components/ui";

export function JudgeRuns() {
  const [errors, setErrors] = useState(false);
  const [hasOps, setHasOps] = useState<string>("");
  const runs = useQuery({
    queryKey: ["judge-runs", errors, hasOps],
    queryFn: () => api<Page<JudgeRun>>(`/v1/admin/judge-runs${queryString({ limit: 100, errors_only: errors || undefined, has_ops: hasOps || undefined })}`),
  });
  return <>
    <div className="page-header"><div><span className="eyebrow">EXTRACTION AUDIT</span><h1>Judge runs</h1><p>Every extraction call, including empty decisions and errors. Reasoning is kept for human review.</p></div></div>
    <div className="filter-bar">
      <Tabs value={errors ? "errors" : "all"} onValueChange={(value) => setErrors(value === "errors")}>
        <TabsList aria-label="Judge run status"><TabsTrigger value="all">All runs</TabsTrigger><TabsTrigger value="errors">Errors only</TabsTrigger></TabsList>
      </Tabs>
      <Select value={hasOps || "all"} onValueChange={(value) => setHasOps(value === "all" ? "" : value)}><SelectTrigger className="filter-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All outputs</SelectItem><SelectItem value="true">Has operations</SelectItem><SelectItem value="false">No operations</SelectItem></SelectContent></Select>
    </div>
    <Card className="run-list">
      {runs.isLoading ? <Loading /> : runs.error ? <ErrorState error={runs.error} retry={() => void runs.refetch()} /> : !runs.data?.items.length ? <EmptyState title="No judge runs match" body="Clear the filters to return to the full append-only audit log." /> : runs.data.items.map((run) => <Link className={run.error ? "list-row error-row" : "list-row"} key={run.id} to="/judge-runs/$runId" params={{ runId: String(run.id) }}>
        <span className="list-primary"><strong>Run #{run.id} · {run.kind}</strong><span>{relativeTime(run.created_at)} · {run.model}</span></span>
        <span className="list-metric"><strong>{opSummary(run.ops)}</strong>operations</span>
        <span className="list-metric"><strong>{(run.input_tokens ?? 0) + (run.output_tokens ?? 0)}</strong>tokens</span>
        <span className="list-metric"><strong>{money(run.cost_usd)}</strong>cost</span>
        <span className={run.latency_ms && run.latency_ms > 8000 ? "list-metric low-confidence" : "list-metric"}><strong>{duration(run.latency_ms)}</strong>latency</span>
        {run.error ? <AlertCircle size={15} color="var(--danger)" /> : <ChevronRight size={15} className="subtle" />}
      </Link>)}
      {runs.data ? <div className="pagination"><span>{runs.data.total} total runs</span></div> : null}
    </Card>
  </>;
}

function opSummary(ops: JudgeOp[]): string {
  const count = (op: string) => ops.filter((item) => item.op === op).length;
  return `A${count("ADD")} U${count("UPDATE")} D${count("DELETE")}`;
}

interface RunDetail {
  run: JudgeRun;
  input: Record<string, unknown>;
  output: unknown;
  ops: JudgeOp[];
  memories: Memory[];
  messages: Message[];
  window_recoverable: boolean;
}

export function JudgeRunDetail() {
  const { runId } = useParams({ strict: false }) as { runId: string };
  const detail = useQuery({
    queryKey: ["judge-run", runId],
    queryFn: () => api<RunDetail>(`/v1/admin/judge-runs/${runId}`),
  });
  if (detail.isLoading) return <Loading label="Recovering judge window…" />;
  if (detail.error || !detail.data) return <ErrorState error={detail.error} retry={() => void detail.refetch()} />;
  const data = detail.data;
  return <>
    <div className="page-header">
      <div><Link to="/judge-runs" className="eyebrow"><ArrowLeft size={11} style={{ display: "inline" }} /> JUDGE RUNS</Link><h1>Run #{data.run.id}</h1><p>{data.run.model} · {data.run.prompt_version} · {relativeTime(data.run.created_at)}</p></div>
      <Button variant="secondary" onClick={() => { void navigator.clipboard.writeText(JSON.stringify(data.output, null, 2)); toast.success("Raw output copied"); }}><Copy size={13} /> Copy JSON</Button>
    </div>
    {data.run.error ? <div className="health-banner" style={{ marginBottom: 16 }}><span><strong>Judge error:</strong> {data.run.error}</span></div> : null}
    <div className="detail-grid">
      <div>
        <Card>
          <div className="card-header"><div><h2>Conversation window</h2><p>{data.messages.length} messages supplied to the judge.</p></div></div>
          {!data.window_recoverable ? <div className="error-state"><strong>Input window not recorded for this run</strong><span>This legacy run emitted no operations, so its source messages cannot be recovered. New runs record message_ids.</span></div> : <div>{data.messages.map((message) => <div className="message-row" key={message.id}><span className="message-meta">{message.role}<br />#{message.id}</span><span className="message-content" lang={guessLang(message.content)}>{message.content}</span></div>)}</div>}
        </Card>
        <Card style={{ marginTop: 16 }}>
          <div className="card-header"><div><h2>Raw output</h2><p>The exact structured response kept in SQLite.</p></div></div>
          <pre className="raw-json">{JSON.stringify(data.output, null, 2)}</pre>
        </Card>
      </div>
      <Card>
        <div className="card-header"><div><h2>Operations</h2><p>{data.ops.length} durable-memory decisions.</p></div></div>
        {!data.ops.length ? <EmptyState title="No operations" body="An empty decision is correct and common; this window contained nothing worth keeping." /> : data.ops.map((op, index) => <OperationCard key={`${op.op}-${index}`} op={op} memories={data.memories} />)}
      </Card>
    </div>
  </>;
}

function OperationCard({ op, memories }: { op: JudgeOp; memories: Memory[] }) {
  const target = memories.find((memory) => memory.id === op.id || memory.text === op.text);
  return <div className="op-card">
    <div className="page-actions"><Badge className={op.op === "DELETE" ? "low-confidence" : ""}>{op.op}</Badge>{op.type ? <TypeBadge type={op.type} /> : null}</div>
    <p className="op-reason">{op.reason || "No reason emitted."}</p>
    {op.text ? <p className="subtle" lang={guessLang(op.text)}>{op.text}</p> : null}
    {target ? <a href={`/ui/memories?sel=${target.id}`} className="mono subtle">memory {target.id.slice(0, 8)} →</a> : op.id ? <span className="mono low-confidence">target {op.id.slice(0, 8)} was hard-deleted</span> : null}
  </div>;
}
