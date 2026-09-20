/**
 * Four charts, and the colours they draw with.
 *
 * Deliberately four, and deliberately thin: a dashboard whose panels each
 * configure recharts by hand ends up with eleven different grid strokes and no
 * two axes formatted alike. Everything on the overview goes through these.
 *
 * Colour comes from the CSS custom properties the rest of the app uses, read
 * back at runtime and re-read when the theme attribute changes. Recharts writes
 * `fill` and `stroke` as SVG presentation attributes, where `var(--chart-blue)`
 * is not substituted, so the value has to be resolved before it is handed over.
 * There is not a hex literal in this file, and both themes follow the tokens.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Label,
  Line,
  Pie,
  PieChart,
  ReferenceLine,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ChartFrame, ChartLegend, ChartTooltip, type ChartTable } from "./ui/chart";
import { compact, dayLabel, isBlank, type Row } from "../lib/series";

export type Tone = "blue" | "green" | "amber" | "violet" | "orange" | "rose" | "gray";

const TONES: Tone[] = ["blue", "green", "amber", "violet", "orange", "rose", "gray"];

const TOKENS = {
  blue: "--chart-blue",
  green: "--chart-green",
  amber: "--chart-amber",
  violet: "--chart-violet",
  orange: "--chart-orange",
  rose: "--chart-rose",
  gray: "--chart-gray",
  ink: "--ink",
  muted: "--muted",
  faint: "--faint",
  line: "--line",
  panel: "--panel-subtle",
  danger: "--danger",
} as const;

type Palette = Record<keyof typeof TOKENS, string>;

function readPalette(): Palette {
  const style = getComputedStyle(document.documentElement);
  const palette = {} as Palette;
  for (const [name, token] of Object.entries(TOKENS) as [keyof Palette, string][]) {
    // The `var()` reference is the fallback, not a copy of the token's value:
    // a colour defined twice is a colour that will disagree with itself.
    palette[name] = style.getPropertyValue(token).trim() || `var(${token})`;
  }
  return palette;
}

/** The resolved tokens, refreshed when the theme toggle rewrites `data-theme`. */
function usePalette(): Palette {
  const [palette, setPalette] = useState(readPalette);
  useEffect(() => {
    const root = document.documentElement;
    const observer = new MutationObserver(() => setPalette(readPalette()));
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return palette;
}

/** One drawn series. `tone` defaults to the field's position in the list. */
export interface Field {
  key: string;
  label: string;
  tone?: Tone;
  as?: "line" | "bar";
  axis?: "left" | "right";
  stack?: string;
  dashed?: boolean;
  format?: (value: number) => string;
}

export interface ChartProps {
  rows: Row[];
  fields: Field[];
  /** The sentence a screen reader gets in place of the drawing. */
  summary: string;
  /** Names the offscreen table. Defaults to the summary. */
  caption?: string;
  height?: number;
  loading?: boolean;
  blankLabel?: string;
  /** A horizontal line the series is meant to be compared against. */
  reference?: { value: number; label: string; axis?: "left" | "right" };
  rightDomain?: [number, number];
}

/** The tone at a position in the palette, cycling rather than running out. */
const toneAt = (index: number): Tone => TONES[index % TONES.length] ?? "gray";
const toneOf = (field: Field, index: number): Tone => field.tone ?? toneAt(index);
const formatOf = (fields: Field[], key: string) =>
  fields.find((field) => field.key === key)?.format ?? compact;

function tableOf(rows: Row[], fields: Field[], caption: string): ChartTable {
  return {
    caption,
    head: ["Day", ...fields.map((field) => field.label)],
    body: rows.map((row) => [
      dayLabel(row.date),
      ...fields.map((field) => (field.format ?? compact)(Number(row[field.key]) || 0)),
    ]),
  };
}

function axes(palette: Palette, fields: Field[], props: ChartProps) {
  const tick = { fill: palette.muted, fontSize: 10 };
  // An axis is labelled in the units of the series on it, so each side takes
  // its formatter from its first series -- milliseconds on the left, a rate on
  // the right, and not `1200` for both.
  const onLeft = fields.find((field) => field.axis !== "right");
  const onRight = fields.find((field) => field.axis === "right");
  const leftFormat = onLeft?.format ?? compact;
  const rightFormat = onRight?.format ?? compact;
  return (
    <>
      <CartesianGrid vertical={false} stroke={palette.line} />
      <XAxis
        dataKey="date"
        tickFormatter={(value: string) => dayLabel(value)}
        tick={tick}
        tickLine={false}
        axisLine={false}
        minTickGap={24}
      />
      <YAxis
        yAxisId="left"
        width={44}
        tickFormatter={leftFormat}
        tick={tick}
        tickLine={false}
        axisLine={false}
      />
      {onRight ? (
        <YAxis
          yAxisId="right"
          orientation="right"
          width={46}
          domain={props.rightDomain}
          tickFormatter={rightFormat}
          tick={tick}
          tickLine={false}
          axisLine={false}
        />
      ) : null}
      <Tooltip
        cursor={{ fill: palette.panel, stroke: palette.line }}
        content={
          <ChartTooltip
            labelFormat={(value) => dayLabel(String(value), { long: true })}
            valueFormat={(value, key) => formatOf(fields, key)(value)}
          />
        }
      />
      {props.reference ? (
        <ReferenceLine
          yAxisId={props.reference.axis ?? "left"}
          y={props.reference.value}
          stroke={palette.danger}
          strokeDasharray="4 4"
          // Grow the axis to fit the line rather than dropping it, which is
          // recharts' default: a budget line is most worth seeing precisely
          // when every day is comfortably under it.
          ifOverflow="extendDomain"
        >
          {/* Left, not right: at the right edge the text runs past the
              plotting area and is clipped by the chart's own margin. */}
          <Label value={props.reference.label} position="insideTopLeft" fill={palette.danger} fontSize={9} />
        </ReferenceLine>
      ) : null}
    </>
  );
}

function marks(palette: Palette, fields: Field[]) {
  return fields.map((field, index) => {
    const color = palette[toneOf(field, index)];
    const axis = field.axis ?? "left";
    return field.as === "bar" ? (
      <Bar
        key={field.key}
        yAxisId={axis}
        dataKey={field.key}
        name={field.label}
        stackId={field.stack}
        fill={color}
        radius={field.stack ? undefined : [3, 3, 0, 0]}
        maxBarSize={30}
        isAnimationActive={false}
      />
    ) : (
      <Line
        key={field.key}
        yAxisId={axis}
        // Straight segments, not a spline: a smoothed curve through a spiky
        // daily rate draws values that were never measured, and an acceptance
        // rate eased through 1.0 appears to exceed 100%.
        type="linear"
        dataKey={field.key}
        name={field.label}
        stroke={color}
        strokeWidth={1.7}
        strokeDasharray={field.dashed ? "4 3" : undefined}
        dot={false}
        activeDot={{ r: 3, strokeWidth: 0 }}
        isAnimationActive={false}
      />
    );
  });
}

function legendOf(palette: Palette, fields: Field[]) {
  return (
    <ChartLegend
      items={fields.map((field, index) => ({
        label: field.axis === "right" ? `${field.label} (right axis)` : field.label,
        color: palette[toneOf(field, index)],
      }))}
    />
  );
}

/** Lines and bars over days, on one or two axes. */
export function TimeSeries(props: ChartProps) {
  const palette = usePalette();
  const { rows, fields, summary, caption, height = 250, loading, blankLabel } = props;
  const keys = useMemo(() => fields.map((field) => field.key), [fields]);
  return (
    <ChartFrame
      summary={summary}
      table={tableOf(rows, fields, caption ?? summary)}
      height={height}
      loading={loading}
      blank={isBlank(rows, keys)}
      blankLabel={blankLabel}
      legend={legendOf(palette, fields)}
    >
      <ComposedChart data={rows} margin={{ top: 10, right: 6, left: -12, bottom: 0 }} accessibilityLayer>
        {axes(palette, fields, props)}
        {marks(palette, fields)}
      </ComposedChart>
    </ChartFrame>
  );
}

/** Bars stacked by group -- the shape for "how many, and of what". */
export function StackedBars(props: ChartProps) {
  const stacked = useMemo(
    () => props.fields.map((field) => ({ ...field, as: "bar" as const, stack: field.stack ?? "one" })),
    [props.fields],
  );
  return <TimeSeries {...props} fields={stacked} />;
}

export interface Slice {
  label: string;
  value: number;
  tone?: Tone;
}

/** A composition, with its total in the hole. */
export function Donut({
  slices,
  summary,
  caption,
  centerLabel,
  height = 210,
  loading,
  blankLabel = "Nothing pending.",
}: {
  slices: Slice[];
  summary: string;
  caption?: string;
  centerLabel: string;
  height?: number;
  loading?: boolean;
  blankLabel?: string;
}) {
  const palette = usePalette();
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const colored = slices.map((slice, index) => ({
    ...slice,
    color: palette[slice.tone ?? toneAt(index)],
  }));
  return (
    <ChartFrame
      summary={summary}
      table={{
        caption: caption ?? summary,
        head: ["Group", "Count", "Share"],
        body: colored.map((slice) => [
          slice.label,
          slice.value,
          total ? `${Math.round((slice.value / total) * 100)}%` : "—",
        ]),
      }}
      height={height}
      loading={loading}
      blank={total === 0}
      blankLabel={blankLabel}
      legend={<ChartLegend items={colored.map((slice) => ({ label: `${slice.label} · ${slice.value}`, color: slice.color }))} />}
      overlay={
        <div className="donut-center">
          <strong style={{ fontVariantNumeric: "tabular-nums" }}>{compact(total)}</strong>
          <span>{centerLabel}</span>
        </div>
      }
    >
      <PieChart margin={{ top: 4, right: 4, bottom: 4, left: 4 }} accessibilityLayer>
        <Pie
          data={colored}
          dataKey="value"
          nameKey="label"
          innerRadius="62%"
          outerRadius="88%"
          paddingAngle={1.5}
          strokeWidth={0}
          isAnimationActive={false}
        >
          {colored.map((slice) => <Cell key={slice.label} fill={slice.color} />)}
        </Pie>
        <Tooltip
          content={<ChartTooltip valueFormat={(value) => `${compact(value)}${total ? ` · ${Math.round((value / total) * 100)}%` : ""}`} />}
        />
      </PieChart>
    </ChartFrame>
  );
}

export interface BarItem {
  id: string;
  label: ReactNode;
  value: number;
  hint?: string;
  /** Plain text for the offscreen table, where `label` may be a link. */
  text: string;
}

/**
 * A ranked bar list, in markup rather than SVG.
 *
 * The rows on this dashboard are links to an entity, and a link drawn inside a
 * chart's SVG is not tabbable, not styled by the app's focus ring, and not
 * openable in a new tab. The bar is a div; the label is whatever the caller
 * passes, usually an anchor.
 */
export function HBar({
  items,
  summary,
  caption,
  tone = "blue",
  loading,
  blankLabel = "Nothing recorded yet.",
  valueFormat = compact,
}: {
  items: BarItem[];
  summary: string;
  caption?: string;
  tone?: Tone;
  loading?: boolean;
  blankLabel?: string;
  valueFormat?: (value: number) => string;
}) {
  const palette = usePalette();
  const peak = items.reduce((max, item) => Math.max(max, item.value), 0);
  return (
    <ChartFrame
      plain
      height={items.length ? 0 : 120}
      summary={summary}
      table={{
        caption: caption ?? summary,
        head: ["Name", "Memories"],
        body: items.map((item) => [item.text, valueFormat(item.value)]),
      }}
      loading={loading}
      blank={!items.length}
      blankLabel={blankLabel}
    >
      <div style={{ display: "grid", gap: 10, padding: "4px 0" }}>
        {items.map((item) => (
          <div key={item.id} style={{ display: "grid", gap: 4 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8, fontSize: 12 }}>
              <span className="type-bar-label" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {item.label}
              </span>
              {item.hint ? <span className="subtle" style={{ fontSize: 10 }}>{item.hint}</span> : null}
              <strong className="mono" style={{ marginLeft: "auto", fontSize: 11 }}>{valueFormat(item.value)}</strong>
            </div>
            <span className="importance-track" style={{ width: "100%", height: 6 }} aria-hidden="true">
              <span style={{ width: `${peak ? Math.max(2, (item.value / peak) * 100) : 0}%`, background: palette[tone] }} />
            </span>
          </div>
        ))}
      </div>
    </ChartFrame>
  );
}
