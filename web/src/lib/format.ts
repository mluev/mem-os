export function relativeTime(value: string | null): string {
  if (!value) return "never";
  const then = new Date(value).getTime();
  const seconds = Math.round((then - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return formatter.format(Math.round(seconds / size), unit);
  }
  return formatter.format(seconds, "second");
}

export function money(value: number | null | undefined): string {
  return `$${(value ?? 0).toFixed(4)}`;
}

export function duration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

/**
 * An exact instant, for the places a relative one is not enough.
 *
 * Provenance is one of them: "3 months ago" is fine for a listing, but an
 * evidence span is a claim about a specific moment in a specific transcript,
 * and a reader checking it needs the date it actually carries.
 */
export function dateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const at = new Date(value);
  if (Number.isNaN(at.getTime())) return "—";
  return at.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** A grouped integer, for counts that sit in tabular columns. */
export function integer(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString();
}
