import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ActivityDay, DashboardStats, MemoryType } from "../api/types";
import { MEMORY_TYPES } from "../lib/constants";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui";

const MEMORY_TYPE_COLORS: Record<MemoryType, string> = {
  preference: "var(--chart-violet)",
  fact: "var(--chart-blue)",
  skill: "var(--chart-green)",
  relation: "var(--chart-rose)",
  project: "var(--chart-amber)",
  decision: "var(--chart-orange)",
  task: "var(--chart-gray)",
};

const tooltipStyle = {
  background: "var(--floating)",
  border: "1px solid var(--line-strong)",
  borderRadius: 14,
  boxShadow: "var(--shadow-float)",
  color: "var(--ink)",
  fontSize: 12,
};

export function ActivityChart({ data }: { data: DashboardStats["analytics"]["daily"] }) {
  const sparseTicks = data.length > 45 ? 6 : data.length > 14 ? 5 : 4;
  return (
    <div className="activity-chart">
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ top: 12, right: 4, left: -24, bottom: 0 }}>
          <defs>
            <linearGradient id="messageFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-blue)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="var(--chart-blue)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="memoryFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--chart-green)" stopOpacity={0.22} />
              <stop offset="100%" stopColor="var(--chart-green)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--line)" vertical={false} />
          <XAxis
            dataKey="day"
            tick={{ fontSize: 11, fill: "var(--faint)" }}
            tickLine={false}
            axisLine={false}
            minTickGap={sparseTicks * 8}
            tickFormatter={(value: string) => value.slice(5)}
          />
          <YAxis tick={{ fontSize: 11, fill: "var(--faint)" }} tickLine={false} axisLine={false} allowDecimals={false} />
          <RechartsTooltip contentStyle={tooltipStyle} labelFormatter={(label) => new Date(`${label}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })} />
          <Area
            type="monotone"
            dataKey="messages"
            name="Messages"
            stroke="var(--chart-blue)"
            strokeWidth={2}
            fill="url(#messageFill)"
            activeDot={{ r: 4, strokeWidth: 2, fill: "var(--panel)", stroke: "var(--chart-blue)" }}
            animationDuration={520}
          />
          <Area
            type="monotone"
            dataKey="memories"
            name="Memories"
            stroke="var(--chart-green)"
            strokeWidth={2}
            fill="url(#memoryFill)"
            activeDot={{ r: 4, strokeWidth: 2, fill: "var(--panel)", stroke: "var(--chart-green)" }}
            animationDuration={580}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ActivityHeatmap({ data }: { data: ActivityDay[] }) {
  if (!data.length) return <div className="quiet-empty">Activity appears after sessions are ingested.</div>;

  const values = data.map((day) => day.messages + day.memories * 4);
  const max = Math.max(1, ...values);
  const startOffset = new Date(`${data[0]!.day}T12:00:00`).getDay();
  const cells: Array<ActivityDay | null> = [
    ...Array<ActivityDay | null>(startOffset).fill(null),
    ...data,
  ];
  const weeks = Math.ceil(cells.length / 7);
  const monthLabels = data.reduce<Array<{ label: string; week: number }>>((labels, day, index) => {
    const date = new Date(`${day.day}T12:00:00`);
    const previous = index ? new Date(`${data[index - 1]!.day}T12:00:00`) : null;
    if (!previous || previous.getMonth() !== date.getMonth()) {
      const month = {
        label: date.toLocaleDateString(undefined, { month: "short" }),
        week: Math.floor((startOffset + index) / 7),
      };
      if (labels.at(-1)?.week === month.week) labels[labels.length - 1] = month;
      else labels.push(month);
    }
    return labels;
  }, []);
  const totalMemories = data.reduce((sum, day) => sum + day.memories, 0);
  const activeDays = values.filter(Boolean).length;

  return (
    <TooltipProvider delayDuration={90}>
      <div className="activity-heatmap">
        <div className="activity-heatmap-summary">
          <strong>{activeDays.toLocaleString()} active days</strong>
          <span>{totalMemories.toLocaleString()} memories created</span>
        </div>
        <div className="activity-heatmap-scroll">
          <div className="activity-calendar">
            <div className="activity-month-labels" style={{ width: `${weeks * 14 - 3}px` }} aria-hidden="true">
              {monthLabels.map((month) => <span style={{ left: `${month.week * 14}px` }} key={`${month.label}-${month.week}`}>{month.label}</span>)}
            </div>
            <div className="activity-calendar-grid">
              <div className="activity-weekday-labels" aria-hidden="true"><span>Mon</span><span>Wed</span><span>Fri</span></div>
              <div className="activity-heatmap-grid" role="img" aria-label={`Activity over ${data.length} days`}>
                {cells.map((day, index) => {
                  if (!day) return <span className="activity-cell is-placeholder" aria-hidden="true" key={`blank-${index}`} />;
                  const value = day.messages + day.memories * 4;
                  const level = value === 0 ? 0 : Math.max(1, Math.min(4, Math.ceil(Math.sqrt(value / max) * 4)));
                  const date = new Date(`${day.day}T12:00:00`).toLocaleDateString(undefined, {
                    month: "short",
                    day: "numeric",
                    year: "numeric",
                  });
                  const label = `${date}: ${day.messages} messages, ${day.memories} memories, ${day.judge_runs} judge runs`;
                  return (
                    <Tooltip key={day.day}>
                      <TooltipTrigger asChild>
                        <span className={`activity-cell level-${level}`} aria-label={label} tabIndex={0} />
                      </TooltipTrigger>
                      <TooltipContent className="activity-cell-tooltip">
                        <strong>{date}</strong>
                        <span>{day.messages} messages · {day.memories} memories</span>
                        <span>{day.judge_runs} judge runs · ${day.cost_usd.toFixed(4)}</span>
                      </TooltipContent>
                    </Tooltip>
                  );
                })}
              </div>
            </div>
            <div className="activity-heatmap-legend" aria-hidden="true">
              <span>Less</span>
              {[0, 1, 2, 3, 4].map((level) => <i className={`activity-cell level-${level}`} key={level} />)}
              <span>More</span>
            </div>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}

export function MemoryTypeActivityChart({ data }: { data: ActivityDay[] }) {
  const totals = useMemo(() => {
    const result = Object.fromEntries(MEMORY_TYPES.map((type) => [type, 0])) as Record<MemoryType, number>;
    for (const day of data) {
      for (const type of MEMORY_TYPES) result[type] += day.memory_types[type] ?? 0;
    }
    return result;
  }, [data]);
  const initialTypes = useMemo(() => {
    const populated = [...MEMORY_TYPES]
      .filter((type) => totals[type] > 0)
      .sort((left, right) => totals[right] - totals[left])
      .slice(0, 3);
    return populated.length ? populated : [...MEMORY_TYPES].slice(0, 3);
  }, [totals]);
  const [selected, setSelected] = useState<Set<MemoryType>>(
    () => new Set(initialTypes),
  );
  const chartData = useMemo(() => data.map((day) => {
    const row: Record<string, string | number> = { day: day.day };
    for (const type of MEMORY_TYPES) row[type] = day.memory_types[type] ?? 0;
    return row;
  }), [data]);

  const toggle = (type: MemoryType) => {
    setSelected((current) => {
      if (current.has(type) && current.size === 1) return current;
      const next = new Set(current);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  };

  return (
    <div className="memory-type-activity">
      <div className="memory-type-picker" aria-label="Memory types shown in chart">
        {MEMORY_TYPES.map((type) => {
          const active = selected.has(type);
          return (
            <button
              type="button"
              className={active ? "memory-type-chip is-active" : "memory-type-chip"}
              aria-pressed={active}
              onClick={() => toggle(type)}
              style={{ "--type-color": MEMORY_TYPE_COLORS[type] } as React.CSSProperties}
              key={type}
            >
              <span />
              {type}
              <strong>{totals[type]}</strong>
            </button>
          );
        })}
      </div>
      <div className="memory-type-chart">
        <ResponsiveContainer>
          <AreaChart data={chartData} margin={{ top: 14, right: 8, left: -24, bottom: 0 }}>
            <defs>
              {MEMORY_TYPES.map((type) => (
                <linearGradient id={`type-fill-${type}`} x1="0" y1="0" x2="0" y2="1" key={type}>
                  <stop offset="0%" stopColor={MEMORY_TYPE_COLORS[type]} stopOpacity={0.18} />
                  <stop offset="100%" stopColor={MEMORY_TYPE_COLORS[type]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid stroke="var(--line)" vertical={false} />
            <XAxis
              dataKey="day"
              tick={{ fontSize: 11, fill: "var(--faint)" }}
              tickLine={false}
              axisLine={false}
              minTickGap={36}
              tickFormatter={(value: string) => value.slice(5)}
            />
            <YAxis tick={{ fontSize: 11, fill: "var(--faint)" }} tickLine={false} axisLine={false} allowDecimals={false} />
            <RechartsTooltip
              contentStyle={tooltipStyle}
              labelFormatter={(label) => new Date(`${label}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
            />
            {MEMORY_TYPES.filter((type) => selected.has(type)).map((type, index) => (
              <Area
                type="monotone"
                dataKey={type}
                name={type[0]!.toUpperCase() + type.slice(1)}
                stroke={MEMORY_TYPE_COLORS[type]}
                strokeWidth={2}
                fill={`url(#type-fill-${type})`}
                activeDot={{ r: 4, strokeWidth: 2, fill: "var(--panel)", stroke: MEMORY_TYPE_COLORS[type] }}
                animationDuration={480 + index * 60}
                key={type}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

const CONFIDENCE_COLORS = {
  high: "var(--chart-green)",
  medium: "var(--chart-amber)",
  low: "var(--chart-rose)",
};

export function ConfidenceChart({
  confidence,
  total,
}: {
  confidence: DashboardStats["analytics"]["confidence"];
  total: number;
}) {
  const data = (["high", "medium", "low"] as const).map((name) => ({
    name,
    value: confidence[name] ?? 0,
  }));
  const strong = confidence.high ?? 0;
  return (
    <div className="donut-wrap">
      <ResponsiveContainer width="100%" height={190}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            innerRadius={61}
            outerRadius={79}
            paddingAngle={3}
            cornerRadius={5}
            stroke="none"
            animationDuration={540}
          >
            {data.map((entry) => <Cell key={entry.name} fill={CONFIDENCE_COLORS[entry.name]} />)}
          </Pie>
          <RechartsTooltip contentStyle={tooltipStyle} />
        </PieChart>
      </ResponsiveContainer>
      <div className="donut-center" aria-hidden="true">
        <strong>{total ? Math.round((strong / total) * 100) : 0}%</strong>
        <span>high confidence</span>
      </div>
    </div>
  );
}
