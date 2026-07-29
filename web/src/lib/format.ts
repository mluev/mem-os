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

export function shortId(value: string): string {
  return value.slice(0, 8);
}

export function guessLang(value: string): "ru" | "en" {
  const letters = value.match(/[A-Za-zА-Яа-яЁё]/g) ?? [];
  if (!letters.length) return "en";
  const cyrillic = letters.filter((letter) => /[А-Яа-яЁё]/.test(letter)).length;
  return cyrillic / letters.length > 0.3 ? "ru" : "en";
}
