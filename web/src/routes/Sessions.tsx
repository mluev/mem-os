import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearch } from "@tanstack/react-router";
import { ArrowLeft, ChevronRight, Copy, GitBranch } from "lucide-react";
import { toast } from "sonner";
import { api, queryString } from "../api/client";
import type { Message, Page, Session } from "../api/types";
import { guessLang, relativeTime, shortId } from "../lib/format";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Loading,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui";

export function Sessions() {
  const [agent, setAgent] = useState("");
  const [project, setProject] = useState("");
  const [state, setState] = useState("all");
  const sessions = useQuery({
    queryKey: ["sessions", agent, project, state],
    queryFn: () => api<Page<Session>>(`/v1/admin/sessions${queryString({ agent_id: agent, project, state, limit: 100 })}`),
  });
  return <>
    <div className="page-header"><div><span className="eyebrow">RAW CORPUS</span><h1>Sessions and messages</h1><p>Immutable conversation history for replaying extraction and tracing memories back to source.</p></div></div>
    <div className="filter-bar">
      <Input className="filter-input" value={agent} onChange={(event) => setAgent(event.target.value)} placeholder="Agent id" />
      <Input className="filter-input" value={project} onChange={(event) => setProject(event.target.value)} placeholder="Project" />
      <Select value={state} onValueChange={setState}><SelectTrigger className="filter-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All states</SelectItem><SelectItem value="open">Open</SelectItem><SelectItem value="closed">Closed</SelectItem></SelectContent></Select>
    </div>
    <Card className="session-list">
      {sessions.isLoading ? <Loading /> : sessions.error ? <ErrorState error={sessions.error} /> : !sessions.data?.items.length ? <EmptyState title="No sessions match" body="Sessions appear after messages are ingested or a transcript is imported." /> : sessions.data.items.map((session) => {
        const meta = session.meta;
        const projectName = typeof meta.project === "string" ? meta.project : "no project";
        const branch = typeof meta.git_branch === "string" ? meta.git_branch : null;
        return <Link className="list-row" key={session.id} to="/sessions/$sessionId" params={{ sessionId: session.id }}>
          <span className="list-primary"><strong className="mono">{shortId(session.id)}</strong><span>{session.agent_id} · {projectName}{branch ? <> · <GitBranch size={9} style={{ display: "inline" }} /> {branch}</> : null}</span></span>
          <span className="list-metric"><strong>{session.message_count}</strong>messages</span>
          <span className={session.unprocessed_count ? "list-metric low-confidence" : "list-metric"}><strong>{session.unprocessed_count}</strong>unprocessed</span>
          <span className="list-metric"><strong>{session.memory_count}</strong>memories</span>
          <span className="list-metric"><strong>{relativeTime(session.started_at)}</strong>started</span>
          <ChevronRight size={15} className="subtle" />
        </Link>;
      })}
      {sessions.data ? <div className="pagination"><span>{sessions.data.total} sessions</span><span>Messages are append-only and cannot be deleted.</span></div> : null}
    </Card>
  </>;
}

interface MessagePage {
  session: Session;
  items: Message[];
  total: number;
  limit: number;
  offset: number;
}

export function SessionDetail() {
  const { sessionId } = useParams({ strict: false }) as { sessionId: string };
  const search = useSearch({ strict: false }) as { highlight?: number };
  const [limit, setLimit] = useState(100);
  const messages = useQuery({
    queryKey: ["session-messages", sessionId, limit],
    queryFn: () => api<MessagePage>(`/v1/admin/sessions/${sessionId}/messages?limit=${limit}`),
  });
  useEffect(() => {
    if (messages.data && search.highlight) {
      document.getElementById(`message-${search.highlight}`)?.scrollIntoView({ block: "center" });
    }
  }, [messages.data, search.highlight]);
  if (messages.isLoading) return <Loading label="Loading conversation…" />;
  if (messages.error || !messages.data) return <ErrorState error={messages.error} />;
  const data = messages.data;
  return <>
    <div className="page-header">
      <div><Link to="/sessions" className="eyebrow"><ArrowLeft size={11} style={{ display: "inline" }} /> SESSIONS</Link><h1 className="mono">{shortId(sessionId)}</h1><p>{data.session.agent_id} · {data.total} messages · started {relativeTime(data.session.started_at)}</p></div>
      <Button variant="secondary" onClick={() => { void navigator.clipboard.writeText(sessionId); toast.success("Session id copied"); }}><Copy size={13} /> Copy id</Button>
    </div>
    <Card>
      <div>{data.items.map((message) => <article id={`message-${message.id}`} className={search.highlight === message.id ? "message-row highlight" : "message-row"} key={message.id}>
        <span className="message-meta"><strong>{message.role}</strong><br />#{message.id}<br />{message.processed ? "processed" : "pending"}</span>
        <div><div className="message-content" lang={guessLang(message.content)}>{message.content}</div>{message.memory_ids.length ? <div className="message-memory-links">{message.memory_ids.map((id) => <a className="badge" href={`/ui/memories?sel=${id}`} key={id}>→ {shortId(id)}</a>)}</div> : null}</div>
      </article>)}</div>
      {data.items.length < data.total ? <div className="pagination"><span>{data.items.length} of {data.total}</span><Button variant="secondary" size="sm" onClick={() => setLimit((value) => value + 100)}>Load more</Button></div> : null}
    </Card>
    <p className="subtle" style={{ textAlign: "center", fontSize: 10, marginTop: 16 }}>Messages are never edited or deleted. Every extractor prompt must remain replayable.</p>
  </>;
}
