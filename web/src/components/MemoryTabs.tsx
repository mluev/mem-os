/**
 * The three read-only tabs of the memory drawer, and the word-diff they share
 * with its conflict banner.
 *
 * They sit beside the drawer rather than inside it because each one is a
 * separate read with its own failure mode — a span that will not verify, a
 * history with no revisions, a fact with no sessions — and none of them touch
 * the edit form the drawer is built around.
 */

import { useMemo, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import { api } from "../api/client";
import type { MemoryEvidence, MemoryRevision, TeamMemory } from "../api/types";
import { dateTime, integer, relativeTime } from "../lib/format";
import { isUnchanged, wordDiff } from "./MemoryDiff";
import { verifySpans, type VerifiedSpan } from "./MemoryEvidence";
import { ErrorState, Loading } from "./ui";

interface SourcesPayload {
  memory: TeamMemory;
  source_role: string;
  evidence: MemoryEvidence[];
}

interface HistoryPayload {
  memory: TeamMemory;
  revisions: MemoryRevision[];
  predecessors: TeamMemory[];
  successor: TeamMemory | null;
}

const DIFF_STYLE: Record<string, CSSProperties> = {
  added: {
    background: "var(--green-bg)",
    color: "var(--green)",
    textDecoration: "none",
    borderRadius: 4,
    padding: "1px 2px",
  },
  removed: {
    background: "var(--danger-bg)",
    color: "var(--danger)",
    borderRadius: 4,
    padding: "1px 2px",
    marginRight: 2,
  },
};

/** Site style strips underlines, so a link inside prose needs one back. */
const LINKED: CSSProperties = {
  textDecoration: "underline",
  textDecorationColor: "var(--line-strong)",
  textUnderlineOffset: 3,
};

/** The diff sets its own size: it is the sentence, not a caption about it. */
const DIFF_TEXT: CSSProperties = { margin: 0, fontSize: "var(--text-body)", lineHeight: 1.7 };

export function DiffText({ before, after }: { before: string; after: string }) {
  const parts = useMemo(() => wordDiff(before, after), [before, after]);
  if (isUnchanged(parts)) return <p className="subtle">Text unchanged.</p>;
  return (
    <p className="message-content" style={DIFF_TEXT}>
      {parts.map((part, index) =>
        part.op === "same" ? (
          <span key={index}>{part.text}</span>
        ) : part.op === "added" ? (
          <ins key={index} style={DIFF_STYLE.added}>
            {part.text}
          </ins>
        ) : (
          <del key={index} style={DIFF_STYLE.removed}>
            {part.text}
          </del>
        ),
      )}
    </p>
  );
}

export function EvidenceTab({ memoryId, active }: { memoryId: string; active: boolean }) {
  const sources = useQuery({
    queryKey: ["memory", memoryId, "sources"],
    enabled: active,
    queryFn: async () => {
      const payload = await api<SourcesPayload>(
        `/v1/memories/${encodeURIComponent(memoryId)}/sources`,
      );
      return { sourceRole: payload.source_role, spans: await verifySpans(payload.evidence) };
    },
  });
  if (sources.isLoading) return <Loading label="Checking spans" />;
  if (sources.error) return <ErrorState error={sources.error} retry={() => void sources.refetch()} />;
  const spans = sources.data?.spans ?? [];
  const failed = spans.filter((span) => span.state !== "verified").length;
  return (
    <>
      <p className="subtle" style={{ marginTop: 0 }}>
        Authority for this fact: <strong>{sources.data?.sourceRole ?? "unknown"}</strong>. Each span
        below is re-sliced from the retained message and checked against the hash recorded when it
        was extracted.
      </p>
      {!spans.length ? (
        <p className="quiet-empty">
          No spans are recorded. A fact written straight through the API — by a person or by a
          model — has no transcript to cite, which is exactly why it starts pending.
        </p>
      ) : (
        <>
          <p className="subtle">
            {spans.length} span{spans.length === 1 ? "" : "s"}
            {failed ? ` · ${failed} could not be verified` : " · all verified"}
          </p>
          <div className="message-list">
            {spans.map((span) => (
              <EvidenceSpan key={span.key} span={span} />
            ))}
          </div>
        </>
      )}
    </>
  );
}

function EvidenceSpan({ span }: { span: VerifiedSpan }) {
  return (
    <article className="message">
      <span className="message-role">
        {span.role}
        <br />#{span.messageId}
        <br />
        {span.createdAt ? dateTime(span.createdAt) : "—"}
      </span>
      <div>
        {span.state === "unverified" ? (
          <p className="form-error" role="alert" style={{ margin: 0 }}>
            This span no longer matches the stored message, so it is not quoted here. The message
            was edited or the offsets drifted; the fact itself is unaffected.
          </p>
        ) : (
          <p className="message-content">
            <span className="subtle">{span.context?.before}</span>
            <mark style={{ background: "var(--amber-bg)", color: "var(--ink)" }}>
              {span.context?.excerpt}
            </mark>
            <span className="subtle">{span.context?.after}</span>
          </p>
        )}
        {span.state === "unchecked" ? (
          <small className="subtle">
            Shown without verification: this browser has no SHA-256 available, or no hash was
            recorded for the span.
          </small>
        ) : null}
      </div>
    </article>
  );
}

export function HistoryTab({
  memory,
  active,
  onOpen,
}: {
  memory: TeamMemory;
  active: boolean;
  onOpen: (id: string) => void;
}) {
  const history = useQuery({
    queryKey: ["memory", memory.id, "history"],
    enabled: active,
    queryFn: () => api<HistoryPayload>(`/v1/memories/${encodeURIComponent(memory.id)}/history`),
  });
  if (history.isLoading) return <Loading label="Loading history" />;
  if (history.error) return <ErrorState error={history.error} retry={() => void history.refetch()} />;
  const revisions = history.data?.revisions ?? [];
  const predecessors = history.data?.predecessors ?? [];
  const successor = history.data?.successor ?? null;
  // Every revision row currently carries the memory's creation time rather
  // than the moment of the change, so a per-revision date is only shown when
  // the values actually differ.
  const datesAreReal = new Set(revisions.map((item) => item.created_at)).size > 1;
  return (
    <>
      {memory.judge_run_id ? (
        <div className="provenance-reason">
          <strong>WHY THIS WAS EXTRACTED</strong>
          <p>
            A model proposed this fact in judge run #{memory.judge_run_id}
            {memory.extraction_version ? ` (${memory.extraction_version})` : ""}. The run holds the
            exact input it saw and the structured output it returned.
          </p>
          <Link
            className="header-link"
            to="/judge-runs/$runId"
            params={{ runId: String(memory.judge_run_id) }}
          >
            Open the run <ExternalLink size={12} />
          </Link>
        </div>
      ) : null}

      {successor ? (
        <p className="subtle">
          Replaced by a newer fact:{" "}
          <button
            type="button"
            className="header-link"
            style={{ border: 0, background: "none", cursor: "pointer", padding: 0 }}
            onClick={() => onOpen(successor.id)}
          >
            <strong>{successor.text}</strong>
          </button>
        </p>
      ) : null}

      {!revisions.length ? (
        <p className="quiet-empty">No revisions recorded yet.</p>
      ) : (
        revisions.map((revision, index) => {
          const older = revisions[index + 1];
          return (
            <div className="op-card" key={revision.revision}>
              <div className="score-head">
                <strong className="mono">revision {revision.revision}</strong>
                <span className="subtle">
                  {revision.kind} · {revision.review_status} · {revision.status}
                  {datesAreReal ? ` · ${dateTime(revision.created_at)}` : ""}
                </span>
              </div>
              {older ? (
                <DiffText before={older.text} after={revision.text} />
              ) : (
                <p className="message-content">{revision.text}</p>
              )}
              <span className="score-parts">
                <span>importance {revision.importance.toFixed(2)}</span>
                <span>confidence {revision.confidence.toFixed(2)}</span>
                <span>{revision.source_role}</span>
                {revision.tags.length ? <span>{revision.tags.join(", ")}</span> : null}
              </span>
            </div>
          );
        })
      )}

      {predecessors.length ? (
        <>
          <h3 className="section-title" style={{ marginTop: 20 }}>
            Facts this one replaced
          </h3>
          <div className="message-list">
            {predecessors.map((item) => (
              <button
                className="list-row"
                type="button"
                key={item.id}
                style={{ border: 0, background: "none", textAlign: "left", cursor: "pointer" }}
                onClick={() => onOpen(item.id)}
              >
                <span className="list-primary">
                  <strong>{item.text}</strong>
                  <span>
                    {item.kind} · revision {item.revision} · {relativeTime(item.updated_at)}
                  </span>
                </span>
              </button>
            ))}
          </div>
        </>
      ) : null}
    </>
  );
}

export function RelationsTab({ memory }: { memory: TeamMemory }) {
  const context = Object.entries(memory.context ?? {});
  return (
    <>
      <dl className="metadata-grid" style={{ marginTop: 0, paddingTop: 0, border: 0 }}>
        <div>
          <dt>Scope — the space that holds it</dt>
          <dd>
            {memory.scope_slug ? (
              <Link to="/entities/$slug" params={{ slug: memory.scope_slug }} style={LINKED}>
                {memory.scope ?? memory.scope_slug}
              </Link>
            ) : (
              (memory.scope ?? "—")
            )}
          </dd>
        </div>
        <div>
          <dt>Subject — who it is about</dt>
          <dd>
            {memory.subject_slug ? (
              <Link to="/entities/$slug" params={{ slug: memory.subject_slug }} style={LINKED}>
                {memory.subject ?? memory.subject_slug}
              </Link>
            ) : (
              "Nobody in particular"
            )}
          </dd>
        </div>
        <div>
          <dt>Author</dt>
          <dd>{memory.author ?? "—"}</dd>
        </div>
        <div>
          <dt>Source authority</dt>
          <dd>{memory.source_role}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{dateTime(memory.created_at)}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{dateTime(memory.updated_at)}</dd>
        </div>
        <div>
          <dt>Valid until</dt>
          <dd>{memory.valid_until ? dateTime(memory.valid_until) : "No expiry"}</dd>
        </div>
        <div>
          <dt>Retrieved</dt>
          <dd className="mono">
            {integer(memory.retrieval_count ?? 0)}
            {memory.last_retrieved_at ? ` · last ${relativeTime(memory.last_retrieved_at)}` : ""}
          </dd>
        </div>
      </dl>

      <h3 className="section-title" style={{ marginTop: 20 }}>
        Sessions this fact came from
      </h3>
      {!memory.sessions?.length ? (
        <p className="quiet-empty">None — it was written directly rather than extracted.</p>
      ) : (
        <div className="message-memory-links">
          {memory.sessions.map((session) => (
            <Link
              className="button button-secondary button-sm"
              key={session}
              to="/sessions/$sessionId"
              params={{ sessionId: session }}
            >
              <span className="mono">{session}</span>
            </Link>
          ))}
        </div>
      )}

      {context.length ? (
        <>
          <h3 className="section-title" style={{ marginTop: 20 }}>
            Context — where this fact applies
          </h3>
          <dl className="config-table">
            {context.map(([key, value]) => (
              <div key={key} style={{ display: "contents" }}>
                <dt>{key}</dt>
                <dd>{typeof value === "string" ? value : JSON.stringify(value)}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
    </>
  );
}
