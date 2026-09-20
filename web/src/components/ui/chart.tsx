/**
 * The chrome around a chart: the frame, the tooltip, the legend, and the parts
 * that make a picture readable without looking at it.
 *
 * Recharts draws pixels. Pixels are unavailable to a screen reader, unusable in
 * a report, and silent about whether an empty panel means "nothing happened" or
 * "the fetch failed". So every chart on this dashboard is wrapped in a `figure`
 * that carries a written summary and, offscreen, the same numbers as a table.
 */

import type { CSSProperties, ReactNode } from "react";
import { ResponsiveContainer } from "recharts";
import { cn } from "../../lib/utils";

/**
 * Present to assistive technology and to "select all", absent from the layout.
 * Inline rather than a utility class so it cannot be dropped by a CSS purge.
 */
const OFFSCREEN: CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  margin: -1,
  padding: 0,
  overflow: "hidden",
  clipPath: "inset(50%)",
  border: 0,
  whiteSpace: "nowrap",
};

/** The chart's data as a table, for a reader who cannot see the drawing. */
export interface ChartTable {
  caption: string;
  head: string[];
  body: (string | number)[][];
}

export interface ChartFrameProps {
  /** A sentence naming what the chart shows and the numbers worth knowing. */
  summary: string;
  table?: ChartTable;
  height?: number;
  loading?: boolean;
  /** True when there is nothing to draw; says so instead of drawing axes. */
  blank?: boolean;
  blankLabel?: string;
  legend?: ReactNode;
  /**
   * Markup laid over the drawing -- a donut's centre total. Text in the middle
   * of a chart is text, not graphics: as DOM it inherits the app's typography
   * and its colour tokens, where an SVG `<text>` would need both restated.
   */
  overlay?: ReactNode;
  children?: ReactNode;
  className?: string;
  /**
   * The children are ordinary markup rather than a recharts tree -- a bar list
   * or a heatmap, where a real anchor and a real focus ring matter more than an
   * SVG. They still get the frame: a summary, a table, and one empty state.
   */
  plain?: boolean;
}

export function ChartFrame({
  summary,
  table,
  height = 250,
  loading = false,
  blank = false,
  blankLabel = "No data in this range.",
  legend,
  overlay,
  children,
  className,
  plain = false,
}: ChartFrameProps) {
  // One height for all three states, so a panel does not jump as it loads.
  const box: CSSProperties = plain
    ? { minHeight: height, position: "relative" }
    : { height, position: "relative" };
  return (
    <figure className={cn("chart-body", className)} style={{ margin: 0 }}>
      <figcaption style={OFFSCREEN}>{summary}</figcaption>
      {loading ? (
        <div style={{ ...box, display: "grid", placeItems: "center" }} aria-busy="true">
          <span className="subtle" style={{ fontSize: 11 }}>Loading…</span>
        </div>
      ) : blank ? (
        <p className="quiet-empty" style={{ ...box, display: "grid", placeItems: "center", margin: 0 }}>
          {blankLabel}
        </p>
      ) : (
        <>
          {plain ? (
            <div style={box}>{children}</div>
          ) : (
            // `box` is already `position: relative`, which is all an overlay
            // needs; `.donut-wrap` would also impose its min-height on every
            // panel that borrowed it.
            <div style={box}>
              <ResponsiveContainer width="100%" height="100%">
                {children}
              </ResponsiveContainer>
              {overlay}
            </div>
          )}
          {table ? <ChartDataTable table={table} /> : null}
        </>
      )}
      {legend && !blank && !loading ? legend : null}
    </figure>
  );
}

/** The same numbers the chart draws, offscreen and in reading order. */
export function ChartDataTable({ table }: { table: ChartTable }) {
  return (
    <table style={OFFSCREEN}>
      <caption>{table.caption}</caption>
      <thead>
        <tr>{table.head.map((cell) => <th key={cell} scope="col">{cell}</th>)}</tr>
      </thead>
      <tbody>
        {table.body.map((row) => (
          <tr key={String(row[0])}>
            <th scope="row">{row[0]}</th>
            {row.slice(1).map((cell, index) => <td key={table.head[index + 1] ?? index}>{cell}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export interface TooltipEntry {
  name?: string | number;
  dataKey?: string | number;
  value?: number | string | (number | string)[];
  color?: string;
}

export interface ChartTooltipProps {
  /** Injected by recharts when this element is handed to `Tooltip content`. */
  active?: boolean;
  label?: string | number;
  payload?: readonly TooltipEntry[];
  labelFormat?: (label: string | number) => string;
  valueFormat?: (value: number, key: string) => string;
}

export function ChartTooltip({ active, label, payload, labelFormat, valueFormat }: ChartTooltipProps) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter((entry) => entry.value != null && !Array.isArray(entry.value));
  if (!rows.length) return null;
  return (
    <div className="shadcn-tooltip-content" style={{ padding: "7px 9px", pointerEvents: "none" }}>
      {label == null ? null : (
        <strong style={{ display: "block", marginBottom: 5, fontSize: 11 }}>
          {labelFormat ? labelFormat(label) : label}
        </strong>
      )}
      {rows.map((entry) => {
        const key = String(entry.dataKey ?? entry.name ?? "");
        const numeric = Number(entry.value);
        return (
          <span key={key} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 11, lineHeight: 1.6 }}>
            <i aria-hidden="true" style={{ width: 8, height: 8, borderRadius: 2, background: entry.color, flex: "0 0 auto" }} />
            <span className="subtle">{entry.name ?? key}</span>
            <strong className="mono" style={{ marginLeft: "auto" }}>
              {valueFormat && Number.isFinite(numeric) ? valueFormat(numeric, key) : String(entry.value)}
            </strong>
          </span>
        );
      })}
    </div>
  );
}

/** A legend that is a caption, not a control: same order as the stack. */
export function ChartLegend({ items }: { items: { label: string; color: string; hint?: string }[] }) {
  return (
    <div className="chart-legend" style={{ flexWrap: "wrap", marginTop: 8 }}>
      {items.map((item) => (
        <span key={item.label} title={item.hint}>
          <i aria-hidden="true" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}
