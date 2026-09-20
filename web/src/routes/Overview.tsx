/**
 * The dashboard: is the memory growing, is it accurate, what does it cost, and
 * what is waiting on a person.
 *
 * Four numbers first, because a dashboard that opens with a chart makes the
 * reader do the summarising. Then one panel per question, each with its own
 * loading and empty state so a single slow or failing endpoint degrades one
 * panel instead of the screen.
 *
 * Every rate here is shown with the count it was computed from. An acceptance
 * rate of 100% over three proposals is not the same claim as 100% over three
 * thousand, and a panel that prints only the percentage invites the wrong one.
 */

import { useMemo, useState } from "react";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { AlertTriangle, Brain, Gauge, Inbox, Search, Wallet } from "lucide-react";
import {
  DEFAULT_RANGE,
  MEMORY_GROUPS,
  RANGES,
  resolveRange,
  useDashboardMetrics,
  useEntityStats,
  useMe,
  useMemoryStats,
  usePeopleStats,
  usePipelineStats,
  useRetrievalStats,
  useReviewStats,
  useReviewQueue,
  useRecentMemories,
  type MemoryGroup,
} from "../api/stats";
import { Donut, HBar, StackedBars, TimeSeries, type Field } from "../components/charts";
import { Badge, Button, Card, Tabs, TabsList, TabsTrigger } from "../components/ui";
import { ChartFrame } from "../components/ui/chart";
import {
  chartRows,
  compact,
  costModels,
  dayLabel,
  dayRange,
  formatRate,
  heatLevel,
  seriesKeys,
  sumColumn,
} from "../lib/series";
import { relativeTime } from "../lib/format";

/**
 * Cost per day is fractions of a cent or several dollars, and both have to
 * read. Deliberately not `money()`, whose four decimals are right for a single
 * model call and wrong for a headline: "$12.0000 limit" is noise.
 */
const usd = (value: number) =>
  value === 0 ? "$0" : value >= 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(3)}`;
const ms = (value: number) => `${Math.round(value)} ms`;

/** The extraction outcomes that add up to what the model proposed. */
const PIPELINE_KEYS = ["added", "updated", "deleted", "rejected", "deduplicated"];

/** One panel, one failure. A dead endpoint says so where its chart would be. */
function panel(query: { isLoading: boolean; error: unknown }, blank: string) {
  return {
    loading: query.isLoading,
    blankLabel: query.error ? "This panel could not be loaded." : blank,
  };
}

export function Overview() {
  const navigate = useNavigate();
  const search = useSearch({ strict: false }) as { days?: number };
  const days = resolveRange(search.days);
  const [group, setGroup] = useState<MemoryGroup>("scope");

  const me = useMe();
  const isAdmin = me.data?.role === "admin";
  const memories = useMemoryStats(days, group);
  const pipeline = usePipelineStats(days);
  const retrieval = useRetrievalStats(days);
  const review = useReviewStats(days);
  const entities = useEntityStats(8);
  const metrics = useDashboardMetrics();
  const people = usePeopleStats(days, isAdmin);
  const recent = useRecentMemories(6);
  const attention = useReviewQueue(undefined, 5);

  // --- memories over time ------------------------------------------------
  const memoryKeys = useMemo(() => seriesKeys(memories.data?.series ?? []), [memories.data]);
  const memoryRows = useMemo(() => chartRows(memories.data, memoryKeys), [memories.data, memoryKeys]);
  const memoryFields: Field[] = memoryKeys.map((key) => ({ key, label: key.replace(/_/g, " ") }));
  const memoryTotal = memoryKeys.reduce((sum, key) => sum + sumColumn(memoryRows, key), 0);

  // --- extraction --------------------------------------------------------
  const pipelineRows = useMemo(
    () => chartRows(pipeline.data, [...PIPELINE_KEYS, "acceptance"]),
    [pipeline.data],
  );
  const pipelineFields: Field[] = [
    { key: "added", label: "added", tone: "green", as: "bar", stack: "one" },
    { key: "updated", label: "updated", tone: "blue", as: "bar", stack: "one" },
    { key: "deleted", label: "deleted", tone: "gray", as: "bar", stack: "one" },
    { key: "rejected", label: "rejected", tone: "rose", as: "bar", stack: "one" },
    { key: "deduplicated", label: "deduplicated", tone: "violet", as: "bar", stack: "one" },
    { key: "acceptance", label: "acceptance", tone: "amber", axis: "right", format: (value) => formatRate(value) },
  ];
  const proposed = PIPELINE_KEYS.reduce((sum, key) => sum + sumColumn(pipelineRows, key), 0);
  const acceptance = pipeline.data?.totals.acceptance_rate ?? null;

  // --- cost --------------------------------------------------------------
  const models = useMemo(() => costModels(pipeline.data?.series ?? []), [pipeline.data]);
  const costKeys = useMemo(() => models.map((model) => `cost:${model}`), [models]);
  const costRows = useMemo(
    () => chartRows(pipeline.data, [...costKeys, "tokens"]),
    [pipeline.data, costKeys],
  );
  const costFields: Field[] = [
    ...models.map((model, index) => ({
      key: `cost:${model}`,
      label: model,
      as: "bar" as const,
      stack: "cost",
      tone: (["blue", "violet", "orange", "rose"] as const)[index % 4],
      format: usd,
    })),
    { key: "tokens", label: "tokens", tone: "gray", axis: "right" as const, format: compact },
  ];
  const limit = metrics.data?.month_limit_usd ?? null;
  const spend = metrics.data?.month_spend_usd ?? pipeline.data?.totals.month_spend_usd ?? 0;
  const reserved = metrics.data?.month_reserved_usd ?? 0;
  const spendShare = limit ? Math.min(100, ((spend + reserved) / limit) * 100) : null;
  // The limit is a monthly ceiling and this chart is a day, so the honest
  // reference is the daily pace that ceiling allows -- drawing the month's
  // number on a daily axis would put the line off the top of every chart.
  const daysThisMonth = new Date(Date.UTC(new Date().getUTCFullYear(), new Date().getUTCMonth() + 1, 0)).getUTCDate();
  const dailyPace = limit ? limit / daysThisMonth : null;

  // --- retrieval ---------------------------------------------------------
  const latencyRows = useMemo(
    () => chartRows(retrieval.data, ["p50", "p95", "abstention"]),
    [retrieval.data],
  );
  const feedbackRows = useMemo(() => chartRows(retrieval.data, ["useful", "not_useful"]), [retrieval.data]);
  const searches = retrieval.data?.totals.searches ?? 0;
  const useful = sumColumn(feedbackRows, "useful");
  const notUseful = sumColumn(feedbackRows, "not_useful");

  // --- review ------------------------------------------------------------
  const backlogRows = useMemo(
    () => chartRows(review.data, ["opened", "confirmed", "declined"]),
    [review.data],
  );
  const pendingBySource = Object.entries(review.data?.totals.pending_by_source ?? {});
  const attentionByKind = Object.entries(review.data?.totals.attention_by_kind ?? {});
  const pending = review.data?.totals.pending ?? 0;
  const waiting = pending + attentionByKind.reduce((sum, [, count]) => sum + count, 0);
  const oldest = review.data?.totals.oldest_pending ?? null;

  // --- people ------------------------------------------------------------
  const peopleDays = useMemo(() => dayRange(people.data?.from, people.data?.to), [people.data]);
  const perPerson = useMemo(() => {
    const byHandle = new Map<string, Map<string, number>>();
    for (const point of people.data?.series ?? []) {
      const day = point.date?.slice(0, 10);
      if (!day) continue;
      const row = byHandle.get(point.key) ?? new Map<string, number>();
      row.set(day, (row.get(day) ?? 0) + Number(point.value || 0));
      byHandle.set(point.key, row);
    }
    let peak = 0;
    for (const row of byHandle.values()) {
      for (const value of row.values()) peak = Math.max(peak, value);
    }
    return { byHandle, peak };
  }, [people.data]);
  /**
   * What one person wrote inside the chosen range.
   *
   * The endpoint's per-person totals (`memories`, `sessions`, `searches`) are
   * all-time and ignore `days` -- only the series is windowed -- so the two
   * numbers are labelled apart rather than presented as one.
   */
  const inRange = (handle: string) => {
    const row = perPerson.byHandle.get(handle);
    return peopleDays.reduce((sum, day) => sum + (row?.get(day) ?? 0), 0);
  };
  const rangeTotal = people.people.reduce((sum, person) => sum + inRange(person.handle), 0);

  const entityRows = entities.data?.totals.entities ?? [];

  return (
    <div className="overview-page">
      <div className="page-header overview-heading">
        <div>
          <span className="eyebrow">MEMORY, NOT WORKFLOW</span>
          <h1>Overview</h1>
          <p>
            What the team remembers, how accurately, at what cost, and what is waiting on a person.
            Everything below covers the last {days} days.
          </p>
        </div>
        <div className="page-actions">
          <Tabs
            value={String(days)}
            onValueChange={(value) =>
              void navigate({
                to: ".",
                search: (old: Record<string, unknown>) => ({
                  ...old,
                  days: Number(value) === DEFAULT_RANGE ? undefined : Number(value),
                }),
              })
            }
          >
            <TabsList aria-label="Range">
              {RANGES.map((range) => (
                <TabsTrigger key={range} value={String(range)}>{range} days</TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <Link to="/search" className="button button-secondary"><Search size={14} /> Search</Link>
        </div>
      </div>

      <div className="stats-grid">
        <Stat
          icon={<Brain size={15} />}
          label="Active memories"
          value={memories.isLoading ? "—" : compact(memories.data?.totals.active ?? 0)}
          note={
            memories.data
              ? `${compact(memories.data.totals.pending)} unconfirmed · ${compact(memories.data.totals.about_someone)} about someone`
              : "Counting…"
          }
        />
        <Stat
          icon={<Inbox size={15} />}
          label="Needs attention"
          value={review.isLoading ? "—" : compact(waiting)}
          note={
            waiting === 0
              ? "Nothing waiting"
              : oldest
                ? `Oldest waiting since ${relativeTime(oldest)}`
                : `${compact(pending)} unconfirmed memories`
          }
          to="/review"
        />
        <Stat
          icon={<Wallet size={15} />}
          label="Month spend"
          value={metrics.isLoading ? "—" : usd(spend)}
          note={
            limit
              ? `of ${usd(limit)} limit · ${usd(reserved)} reserved`
              : "No monthly limit configured"
          }
          bar={spendShare}
        />
        <Stat
          icon={<Gauge size={15} />}
          label="Search p95"
          value={
            retrieval.isLoading
              ? "—"
              : retrieval.data?.totals.p95_ms == null
                ? "—"
                : ms(retrieval.data.totals.p95_ms)
          }
          note={
            searches === 0
              ? "No searches in this range"
              : `p50 ${retrieval.data?.totals.p50_ms == null ? "—" : ms(retrieval.data.totals.p50_ms)} over ${compact(searches)} searches`
          }
        />
      </div>

      <div className="overview-grid">
        <Card>
          <div className="card-header">
            <div>
              <h2>Needs attention</h2>
              <p>Unconfirmed facts, unplaced names, conflicts and failed work.</p>
            </div>
            <Link to="/review" className="header-link">Review all →</Link>
          </div>
          {attention.isLoading ? (
            <p className="quiet-empty">Reading the queue…</p>
          ) : !attention.data?.items.length ? (
            <p className="quiet-empty">Nothing is waiting on a person.</p>
          ) : (
            <div className="triage-list">
              {attention.data.items.slice(0, 5).map((item) => (
                <div className="triage-row" key={item.id}>
                  <span className="triage-icon" aria-hidden="true"><AlertTriangle size={15} /></span>
                  <div className="triage-copy">
                    <strong>{item.title || "(no wording)"}</strong>
                    <span>
                      {[item.kind.replace(/_/g, " "), item.author ? `by ${item.author}` : null, relativeTime(item.created_at)]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                  <Link to="/review" search={{ kind: item.kind }} className="header-link">Open</Link>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="card-header">
            <div>
              <h2>Recently changed</h2>
              <p>Newest first by last change, so a rewritten fact rises to the top.</p>
            </div>
            <Link to="/memories" className="header-link">Browse all →</Link>
          </div>
          {recent.isLoading ? (
            <p className="quiet-empty">Loading…</p>
          ) : !recent.data?.items.length ? (
            <p className="quiet-empty">No memories yet.</p>
          ) : (
            // `.triage-row` rather than `.list-row`: the listing row is a
            // six-column grid built for a full-width table, and inside half a
            // dashboard column it squeezes the text to one word per line.
            <div className="triage-list">
              {recent.data.items.map((memory) => (
                <div className="triage-row" key={memory.id}>
                  <span className="triage-icon" aria-hidden="true"><Brain size={15} /></span>
                  <div className="triage-copy">
                    <strong
                      title={memory.text}
                      style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    >
                      {memory.text}
                    </strong>
                    <span>
                      {[memory.kind, memory.scope, memory.author ? `by ${memory.author}` : null, relativeTime(memory.updated_at)]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                  {memory.review_status === "pending" ? <Badge>unconfirmed</Badge> : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      void navigate({
                        to: ".",
                        search: (old: Record<string, unknown>) => ({ ...old, memory: memory.id }),
                      })
                    }
                  >
                    Open
                  </Button>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div className="analytics-grid">
        <Card>
          <div className="card-header">
            <div>
              <h2>New memories</h2>
              <p>What the store gained each day, stacked by {group.replace(/_/g, " ")}.</p>
            </div>
            <div className="memory-type-picker" style={{ padding: 0 }}>
              {MEMORY_GROUPS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={group === option ? "memory-type-chip is-active" : "memory-type-chip"}
                  aria-pressed={group === option}
                  onClick={() => setGroup(option)}
                >
                  {option.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </div>
          <StackedBars
            rows={memoryRows}
            fields={memoryFields}
            height={260}
            summary={`New memories per day over ${days} days, stacked by ${group.replace(/_/g, " ")}: ${compact(memoryTotal)} in total across ${memoryKeys.length} ${memoryKeys.length === 1 ? "group" : "groups"}.`}
            caption={`New memories per day by ${group.replace(/_/g, " ")}`}
            {...panel(memories, "No memories were written in this range.")}
          />
        </Card>

        <Card>
          <div className="card-header">
            <div>
              <h2>Pending by source</h2>
              <p>Who or what wrote the facts still waiting for a human.</p>
            </div>
          </div>
          <Donut
            slices={pendingBySource.map(([label, value]) => ({ label: label.replace(/_/g, " "), value }))}
            centerLabel="unconfirmed"
            height={215}
            summary={
              pending === 0
                ? "Nothing is pending review."
                : `${compact(pending)} unconfirmed memories: ${pendingBySource.map(([label, value]) => `${value} from ${label.replace(/_/g, " ")}`).join(", ")}.`
            }
            caption="Unconfirmed memories by source role"
            {...panel(review, "Nothing is pending review.")}
          />
        </Card>
      </div>

      <div className="analytics-grid">
        <Card>
          <div className="card-header">
            <div>
              <h2>Extraction</h2>
              <p>
                What the model proposed and what the store kept. Acceptance is the number worth
                watching; it means nothing without the volume beside it.
              </p>
            </div>
            <span className="triage-count">
              {formatRate(acceptance)} of {compact(proposed)}
            </span>
          </div>
          <TimeSeries
            rows={pipelineRows}
            fields={pipelineFields}
            height={260}
            rightDomain={[0, 1]}
            summary={`Extraction over ${days} days: ${compact(proposed)} proposals, ${formatRate(acceptance)} of them applied. Rejections and duplicates are drawn beside the writes so a rising rate on falling volume is visible.`}
            caption="Extraction outcomes and acceptance rate per day"
            {...panel(pipeline, "No extraction ran in this range.")}
          />
        </Card>

        <Card>
          <div className="card-header">
            <div>
              <h2>Where memory accumulates</h2>
              <p>Memories held in a scope plus memories about it.</p>
            </div>
            <Link to="/entities" className="header-link">Entities →</Link>
          </div>
          <HBar
            items={entityRows.map((entity) => ({
              id: entity.slug,
              value: entity.in_scope + entity.about,
              text: `${entity.name} (${entity.kind})`,
              hint: `${entity.in_scope} in scope · ${entity.about} about`,
              label: (
                <Link to="/entities/$slug" params={{ slug: entity.slug }}>
                  {entity.name}
                </Link>
              ),
            }))}
            summary={
              entityRows.length
                ? `Top ${entityRows.length} entities by memory count: ${entityRows.map((entity) => `${entity.name} ${entity.in_scope + entity.about}`).join(", ")}.`
                : "No entity holds a memory yet."
            }
            caption="Entities by memory count"
            {...panel(entities, "No entity holds a memory yet.")}
          />
        </Card>
      </div>

      <div className="analytics-grid">
        <Card>
          <div className="card-header">
            <div>
              <h2>Model cost</h2>
              <p>
                Spend per day by model, with tokens beside it.
                {dailyPace ? ` The dashed line is the daily pace the ${usd(limit ?? 0)} monthly limit allows.` : " No monthly limit is configured."}
              </p>
            </div>
            <span className="triage-count">{usd(spend)}</span>
          </div>
          <TimeSeries
            rows={costRows}
            fields={costFields}
            height={260}
            reference={dailyPace ? { value: dailyPace, label: `${usd(dailyPace)}/day pace` } : undefined}
            summary={`Model spend over ${days} days across ${models.length || "no"} ${models.length === 1 ? "model" : "models"}, ${usd(spend)} so far this month${limit ? ` against a ${usd(limit)} limit` : ""}. Tokens are on the right axis.`}
            caption="Model cost and tokens per day"
            {...panel(pipeline, "No model calls were billed in this range.")}
          />
        </Card>

        <Card>
          <div className="card-header">
            <div>
              <h2>Review backlog</h2>
              <p>Opened against closed, so a growing queue looks different from a large one.</p>
            </div>
          </div>
          <TimeSeries
            rows={backlogRows}
            fields={[
              { key: "opened", label: "opened", tone: "amber", as: "bar" },
              { key: "confirmed", label: "confirmed", tone: "green" },
              { key: "declined", label: "declined", tone: "rose" },
            ]}
            height={215}
            summary={`Review over ${days} days: ${compact(sumColumn(backlogRows, "opened"))} opened, ${compact(sumColumn(backlogRows, "confirmed"))} confirmed, ${compact(sumColumn(backlogRows, "declined"))} declined, ${compact(pending)} still waiting.`}
            caption="Review items opened, confirmed and declined per day"
            {...panel(review, "Nothing was reviewed in this range.")}
          />
        </Card>
      </div>

      <div className="analytics-grid">
        <Card>
          <div className="card-header">
            <div>
              <h2>Retrieval</h2>
              <p>Latency per day, with the share of searches that declined to answer.</p>
            </div>
            <span className="triage-count">
              {formatRate(retrieval.data?.totals.abstention_rate ?? null)} abstained
            </span>
          </div>
          <TimeSeries
            rows={latencyRows}
            fields={[
              { key: "p50", label: "p50", tone: "blue", format: ms },
              { key: "p95", label: "p95", tone: "orange", format: ms },
              { key: "abstention", label: "abstention", tone: "gray", axis: "right", dashed: true, format: (value) => formatRate(value) },
            ]}
            height={260}
            rightDomain={[0, 1]}
            summary={`Retrieval over ${days} days: ${compact(searches)} searches, p50 ${retrieval.data?.totals.p50_ms == null ? "unknown" : ms(retrieval.data.totals.p50_ms)}, p95 ${retrieval.data?.totals.p95_ms == null ? "unknown" : ms(retrieval.data.totals.p95_ms)}, ${formatRate(retrieval.data?.totals.abstention_rate ?? null)} abstained.`}
            caption="Retrieval latency and abstention per day"
            {...panel(retrieval, "No searches ran in this range.")}
          />
        </Card>

        <Card>
          <div className="card-header">
            <div>
              <h2>Was it useful?</h2>
              <p>Feedback on retrieved memories. The only signal that comes from a person.</p>
            </div>
            <Link to="/feedback" className="header-link">Feedback →</Link>
          </div>
          <StackedBars
            rows={feedbackRows}
            fields={[
              { key: "useful", label: "useful", tone: "green" },
              { key: "not_useful", label: "not useful", tone: "rose" },
            ]}
            height={215}
            summary={
              useful + notUseful === 0
                ? "Nobody labelled a retrieved memory in this range."
                : `${compact(useful)} useful and ${compact(notUseful)} not useful out of ${compact(useful + notUseful)} labels — ${formatRate(useful / (useful + notUseful))} positive, over ${compact(searches)} searches.`
            }
            caption="Retrieval feedback per day"
            {...panel(retrieval, "Nobody labelled a retrieved memory in this range.")}
          />
        </Card>
      </div>

      {isAdmin && !people.forbidden ? (
        <Card>
          <div className="card-header">
            <div>
              <h2>People</h2>
              <p>
                Who is writing memory, and what their share of the bill is. Visible to
                administrators only.
              </p>
            </div>
            <Link to="/team" className="header-link">Team →</Link>
          </div>
          <ChartFrame
            plain
            height={120}
            loading={people.isLoading}
            blank={!people.people.length || !peopleDays.length}
            blankLabel="No per-person activity in this range."
            summary={`Memories written per person per day over ${days} days across ${people.people.length} people; the busiest day was ${compact(perPerson.peak)} memories.`}
            table={{
              caption: `Memories written per person in the last ${days} days, with all-time totals`,
              head: ["Person", "In range", "Memories, all time", "Sessions", "Searches", "Spend this month"],
              body: people.people.map((person) => [
                person.handle,
                inRange(person.handle),
                person.memories,
                person.sessions,
                person.searches,
                `$${person.month_spend_usd.toFixed(2)}`,
              ]),
            }}
          >
            <div className="activity-heatmap">
              <div className="activity-heatmap-summary">
                <strong>{compact(rangeTotal)} memories</strong>
                <span>
                  by {people.people.length} people in the last {days} days · peak{" "}
                  {compact(perPerson.peak)} in a day
                </span>
              </div>
              <div className="activity-heatmap-scroll">
                {people.people.map((person) => {
                  const row = perPerson.byHandle.get(person.handle);
                  return (
                    <div
                      key={person.handle}
                      style={{ display: "grid", gridTemplateColumns: "128px 1fr", alignItems: "center", gap: 10, marginBottom: 4 }}
                    >
                      <span className="subtle" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {person.display_name || person.handle}
                      </span>
                      {/* One row of the calendar rather than seven: the axis
                          here is people, not weekdays. The cells are labelled
                          as one image and the numbers repeat in the table
                          below, which is what a screen reader can actually
                          use -- thirty labelled squares per person is noise. */}
                      <div
                        className="activity-heatmap-grid"
                        style={{ gridTemplateRows: "11px" }}
                        role="img"
                        aria-label={`${person.handle}: ${inRange(person.handle)} memories in the last ${peopleDays.length} days`}
                      >
                        {peopleDays.map((day) => {
                          const value = row?.get(day) ?? 0;
                          return (
                            <span
                              key={day}
                              className={`activity-cell level-${heatLevel(value, perPerson.peak)}`}
                              title={`${person.handle} · ${dayLabel(day)} · ${value} ${value === 1 ? "memory" : "memories"}`}
                            />
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
              <div className="activity-heatmap-legend">
                <span>Less</span>
                {[0, 1, 2, 3, 4].map((level) => (
                  <span key={level} className={`activity-cell level-${level}`} aria-hidden="true" />
                ))}
                <span>More</span>
              </div>
            </div>
          </ChartFrame>
          <div className="table-shell" style={{ borderRadius: 9, borderTop: "1px solid var(--line)" }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Person</th>
                  <th scope="col">Role</th>
                  <th scope="col">Last {days} days</th>
                  {/* The remaining counts are all-time: the endpoint does not
                      window them, and labelling them as if it did would be a
                      lie a reader cannot check. */}
                  <th scope="col">Memories, all time</th>
                  <th scope="col">Sessions</th>
                  <th scope="col">Searches</th>
                  <th scope="col">Spend this month</th>
                  <th scope="col">Last active</th>
                </tr>
              </thead>
              <tbody>
                {people.people.map((person) => (
                  <tr key={person.handle}>
                    <td>
                      <strong>{person.display_name || person.handle}</strong>
                      <span className="subtle"> {person.handle}</span>
                    </td>
                    <td>
                      <Badge>{person.role}</Badge>
                      {person.disabled ? <Badge>disabled</Badge> : null}
                    </td>
                    <td className="mono">{compact(inRange(person.handle))}</td>
                    <td className="mono">{compact(person.memories)}</td>
                    <td className="mono">{compact(person.sessions)}</td>
                    <td className="mono">{compact(person.searches)}</td>
                    <td className="mono">${person.month_spend_usd.toFixed(2)}</td>
                    <td className="subtle">{relativeTime(person.key_last_used_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      <p className="system-note">
        Statistics are aggregated by the service and cached for a minute. Percentages are shown with
        the count they were computed from.
      </p>
    </div>
  );
}

function Stat({
  icon,
  label,
  value,
  note,
  to,
  bar,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  note: string;
  to?: "/review";
  bar?: number | null;
}) {
  const body = (
    <>
      <span className="stat-icon" aria-hidden="true">{icon}</span>
      <span>{label}</span>
      <strong style={{ fontVariantNumeric: "tabular-nums" }}>{value}</strong>
      {bar == null ? null : (
        <span
          className="importance-track"
          // `display: block` because the shared track is normally a flex item
          // and inherits its box that way; on a card it is an inline span,
          // where width and height would be ignored.
          style={{ display: "block", width: "100%", height: 5, marginTop: 10 }}
          aria-hidden="true"
        >
          <span
            style={{
              width: `${Math.max(1, bar)}%`,
              background: bar >= 90 ? "var(--danger)" : bar >= 70 ? "var(--amber)" : "var(--green)",
            }}
          />
        </span>
      )}
      <small>{note}</small>
    </>
  );
  return to ? (
    <Link to={to} className="card stat-card" style={{ display: "block" }}>{body}</Link>
  ) : (
    <Card className="stat-card">{body}</Card>
  );
}
