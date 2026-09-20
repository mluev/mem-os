/**
 * Turning `/v1/admin/stats/*` into something a chart can draw.
 *
 * Every statistics endpoint answers with the same flat shape -- a list of
 * `{date, key, value}` -- and recharts wants the transpose of that: one row per
 * day with a column per series. The conversion is small, it is used by every
 * panel on the dashboard, and it is the part most likely to be quietly wrong,
 * so it lives here as plain functions with tests rather than inline in a
 * component where a bug reads as a design choice.
 */

import type { SeriesPoint } from "../api/types";

/**
 * One recharts datum: a calendar day plus a numeric column per series key.
 *
 * An index signature rather than an intersection with `Record<string, number>`,
 * which would make `date` both a string and a number and force every literal
 * through a cast.
 */
export interface Row {
  date: string;
  [column: string]: number | string;
}

const DAY_MS = 86_400_000;

/**
 * A range wider than this is refused rather than materialised. The API caps
 * `days` at 365; anything past that is a malformed envelope, and filling it
 * would build a million-element array inside a render.
 */
const MAX_DAYS = 400;

/**
 * The calendar day a bucket label names.
 *
 * The series endpoints send a bare `YYYY-MM-DD` for day buckets but an ISO
 * timestamp for the entity endpoint's `last_activity`, and a null date for a
 * point that has no day at all. All three arrive here.
 */
export function toDay(value: string | null | undefined): string | null {
  if (!value) return null;
  const day = value.slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(day) ? day : null;
}

/**
 * Every day from `from` to `to` inclusive.
 *
 * Arithmetic is anchored to UTC midnight so a range that crosses a daylight
 * saving boundary does not gain or lose a bucket -- the server's buckets are
 * UTC dates, and a local-time loop silently produces 29 or 31 days for a month.
 */
export function dayRange(
  from: string | null | undefined,
  to: string | null | undefined,
): string[] {
  const first = toDay(from);
  const last = toDay(to);
  if (!first || !last) return [];
  const end = Date.parse(`${last}T00:00:00Z`);
  let cursor = Date.parse(`${first}T00:00:00Z`);
  if (!Number.isFinite(cursor) || !Number.isFinite(end) || end < cursor) return [];
  const days: string[] = [];
  while (cursor <= end && days.length < MAX_DAYS) {
    days.push(new Date(cursor).toISOString().slice(0, 10));
    cursor += DAY_MS;
  }
  return days;
}

/**
 * A bucket label as a reader sees it: `2026-09-04` as "4 Sep", or as
 * "Fri, 4 September" where there is room for it.
 *
 * Rendered in UTC because the bucket is a UTC date -- formatting it in local
 * time moves half the year's points to the previous day. `locale` exists so a
 * test can assert on the output; production leaves it to the browser.
 */
export function dayLabel(
  value: string | null | undefined,
  options: { long?: boolean; locale?: string } = {},
): string {
  const day = toDay(value);
  if (!day) return "—";
  const at = new Date(`${day}T00:00:00Z`);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleDateString(
    options.locale,
    options.long
      ? { weekday: "short", day: "numeric", month: "long", timeZone: "UTC" }
      : { day: "numeric", month: "short", timeZone: "UTC" },
  );
}

/** The sum each key contributes across the whole window. */
export function totalsByKey(points: readonly SeriesPoint[]): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const point of points) {
    const value = Number(point.value);
    if (!Number.isFinite(value)) continue;
    totals[point.key] = (totals[point.key] ?? 0) + value;
  }
  return totals;
}

/**
 * The keys present, largest contributor first.
 *
 * Ordering by size rather than by arrival keeps a stacked chart's bands stable
 * between polls and puts the band worth reading at the bottom of the stack.
 * Ties break on name so the order is deterministic.
 */
export function seriesKeys(points: readonly SeriesPoint[]): string[] {
  const totals = totalsByKey(points);
  return Object.keys(totals).sort(
    (left, right) => (totals[right] ?? 0) - (totals[left] ?? 0) || left.localeCompare(right),
  );
}

/**
 * Transpose the flat series into one row per day.
 *
 * Repeated `(day, key)` pairs are summed, which is not defensive tidying: the
 * pipeline endpoint emits `tokens`, `calls` and `errors` once per model per
 * day, so a two-model day arrives as two points for the same column and the
 * day's total is their sum. Every key the endpoints repeat is additive; the
 * ones that are not -- `acceptance`, `p50`, `p95` -- are emitted once a day.
 */
export function pivot(points: readonly SeriesPoint[]): Row[] {
  const byDay = new Map<string, Row>();
  for (const point of points) {
    const day = toDay(point.date);
    if (!day) continue;
    const value = Number(point.value);
    if (!Number.isFinite(value)) continue;
    const row = byDay.get(day) ?? { date: day };
    // `date` is the one string column; a series key that collided with it
    // would be a server bug, and overwriting the bucket label would be worse.
    if (point.key === "date") continue;
    row[point.key] = (Number(row[point.key]) || 0) + value;
    byDay.set(day, row);
  }
  return [...byDay.values()].sort((left, right) => left.date.localeCompare(right.date));
}

/**
 * Give every day in the range a row, and every row every column.
 *
 * A missing day is the reason this exists. Recharts joins the points it is
 * given, so a gap in the data draws as a straight line across it -- a quiet
 * day reads as a busy one interpolated. Zero is the truth for a count.
 */
export function fillDays(
  rows: readonly Row[],
  days: readonly string[],
  keys: readonly string[],
): Row[] {
  const byDay = new Map(rows.map((row) => [row.date, row]));
  const all = days.length ? [...new Set([...days, ...byDay.keys()])].sort() : rows.map((r) => r.date);
  return all.map((day) => {
    const row = { date: day } as Row;
    const found = byDay.get(day);
    for (const key of keys) row[key] = found?.[key] ?? 0;
    return row;
  });
}

/**
 * The whole conversion: flat series in, gap-free recharts rows out.
 *
 * `keys` narrows and orders the columns when a panel draws a subset of what
 * the endpoint sent; omitted, every key is drawn largest-first.
 */
export function chartRows(
  stats: { series: SeriesPoint[]; from: string | null; to: string | null } | undefined,
  keys?: readonly string[],
): Row[] {
  if (!stats) return [];
  const columns = keys ?? seriesKeys(stats.series);
  return fillDays(pivot(stats.series), dayRange(stats.from, stats.to), columns);
}

/** What one key adds up to across the window. */
export function sumOf(points: readonly SeriesPoint[], key: string): number {
  return totalsByKey(points)[key] ?? 0;
}

/** The column total across rows -- the denominator a rate needs beside it. */
export function sumColumn(rows: readonly Row[], key: string): number {
  return rows.reduce((total, row) => total + (Number(row[key]) || 0), 0);
}

/** `part` as a percentage of `whole`, or null when there is no denominator. */
export function percent(part: number, whole: number): number | null {
  if (!Number.isFinite(part) || !Number.isFinite(whole) || whole === 0) return null;
  return (part / whole) * 100;
}

/** A 0-1 rate as a percentage. Null in, em dash out: an unknown rate is not 0%. */
export function formatRate(value: number | null | undefined, digits = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/**
 * A number short enough for an axis tick or a stat card.
 *
 * Hand-rolled rather than `Intl.NumberFormat`'s compact notation so the output
 * does not shift with the runtime's ICU data, and so 999 999 reads as `1M`
 * instead of `1000k`.
 */
export function compact(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value < 0 ? "-" : "";
  const size = Math.abs(value);
  const scale = (divisor: number, suffix: string) => {
    const scaled = size / divisor;
    const text = scaled >= 100 ? String(Math.round(scaled)) : scaled.toFixed(1).replace(/\.0$/, "");
    return `${sign}${text}${suffix}`;
  };
  if (size >= 999_500_000) return scale(1e9, "B");
  if (size >= 999_500) return scale(1e6, "M");
  if (size >= 999.5) return scale(1e3, "k");
  return sign + (Number.isInteger(size) ? String(size) : String(Number(size.toFixed(1))));
}

/**
 * The models the pipeline endpoint charged for, cheapest name first.
 *
 * Cost arrives as one key per model (`cost:claude-...`) because the interesting
 * question is which model the bill came from, not what the bill was.
 */
export function costModels(points: readonly SeriesPoint[]): string[] {
  return [...new Set(points.filter((p) => p.key.startsWith("cost:")).map((p) => p.key.slice(5)))]
    .filter(Boolean)
    .sort();
}

/** Which of the five heatmap shades a cell gets. Zero is its own level. */
export function heatLevel(value: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (!Number.isFinite(value) || value <= 0 || !Number.isFinite(max) || max <= 0) return 0;
  const level = Math.ceil((Math.min(value, max) / max) * 4);
  return Math.min(4, Math.max(1, level)) as 1 | 2 | 3 | 4;
}

/**
 * Whether a panel has anything to draw.
 *
 * Rows exist for every day in the range even when nothing happened, so row
 * count answers nothing; a window in which every column is zero deserves a
 * sentence, not axes drawn around a flat line.
 */
export function isBlank(rows: readonly Row[], keys: readonly string[]): boolean {
  if (!rows.length || !keys.length) return true;
  return !rows.some((row) => keys.some((key) => (Number(row[key]) || 0) !== 0));
}
