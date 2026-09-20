import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, ChevronRight } from "lucide-react";
import { api } from "../api/client";
import type { SessionsPage, SessionMessages } from "../api/types";
import { Badge, Card, EmptyState, ErrorState, Loading } from "../components/ui";
import { relativeTime } from "../lib/format";

export function Sessions() {
  const query = useQuery({ queryKey: ["sessions"], queryFn: () => api<SessionsPage>("/v1/admin/sessions?limit=100") });
  return <><div className="page-header"><div><span className="eyebrow">SOURCE EVIDENCE</span><h1>Sessions</h1><p>Normalized, redacted evidence retained for replay and provenance.</p></div></div><Card>{query.isLoading ? <Loading /> : query.error ? <ErrorState error={query.error} /> : !query.data?.items.length ? <EmptyState title="No sessions" body="Evidence events create sessions automatically." /> : query.data.items.map((session) => <Link className="list-row" key={session.id} to="/sessions/$sessionId" params={{ sessionId: session.id }}><span className="list-primary"><strong>{session.id}</strong><span>{session.agent_id} · {relativeTime(session.started_at)}</span></span><Badge>{session.messages} messages</Badge><Badge>{session.extracted} extracted memories</Badge><ChevronRight size={15} /></Link>)}</Card></>;
}

export function SessionDetail() {
  const { sessionId } = useParams({ strict: false }) as { sessionId: string };
  const query = useQuery({ queryKey: ["session", sessionId], queryFn: () => api<SessionMessages>(`/v1/admin/sessions/${encodeURIComponent(sessionId)}/messages?limit=500`) });
  if (query.isLoading) return <Loading />;
  if (query.error || !query.data) return <ErrorState error={query.error} />;
  return <><div className="page-header"><div><Link to="/sessions" className="eyebrow"><ArrowLeft size={11} /> SESSIONS</Link><h1 className="mono">{sessionId}</h1><p>{query.data.total} immutable evidence events</p></div></div><Card>{query.data.items.map((message) => <article className="message-row" key={message.id}><span className="message-meta"><strong>{message.role}</strong><br />#{message.id}<br />{message.processed ? "processed" : "pending"}</span><div><p className="message-content">{message.content}</p>{message.redacted ? <Badge>redacted</Badge> : null}</div></article>)}</Card></>;
}
