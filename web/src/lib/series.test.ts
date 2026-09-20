import { describe, expect, it } from "vitest";
import type { SeriesPoint } from "../api/types";
import {
  chartRows,
  compact,
  costModels,
  dayLabel,
  dayRange,
  fillDays,
  formatRate,
  heatLevel,
  isBlank,
  percent,
  pivot,
  seriesKeys,
  sumColumn,
  sumOf,
  toDay,
  totalsByKey,
  type Row,
} from "./series";

const point = (date: string | null, key: string, value: number): SeriesPoint => ({ date, key, value });

describe("toDay", () => {
  it("keeps a bucket label as it arrives", () => expect(toDay("2026-09-01")).toBe("2026-09-01"));
  it("truncates an ISO timestamp to its day", () =>
    expect(toDay("2026-09-01T22:14:05.221Z")).toBe("2026-09-01"));
  it("rejects what is not a day", () => {
    expect(toDay(null)).toBeNull();
    expect(toDay("")).toBeNull();
    expect(toDay("last tuesday")).toBeNull();
  });
});

describe("dayRange", () => {
  it("is inclusive of both ends", () =>
    expect(dayRange("2026-09-01", "2026-09-04")).toEqual([
      "2026-09-01",
      "2026-09-02",
      "2026-09-03",
      "2026-09-04",
    ]));

  it("accepts the timestamps the envelope actually carries", () =>
    expect(dayRange("2026-08-31T09:00:00Z", "2026-09-02T08:59:00Z")).toEqual([
      "2026-08-31",
      "2026-09-01",
      "2026-09-02",
    ]));

  it("crosses a month, a leap day and a daylight saving boundary without dropping a bucket", () => {
    expect(dayRange("2028-02-27", "2028-03-01")).toEqual([
      "2028-02-27",
      "2028-02-28",
      "2028-02-29",
      "2028-03-01",
    ]);
    // 29 March 2026 is when most of Europe springs forward; a range walked in
    // local time loses or repeats this day.
    expect(dayRange("2026-03-28", "2026-03-30")).toEqual([
      "2026-03-28",
      "2026-03-29",
      "2026-03-30",
    ]);
    expect(dayRange("2026-01-01", "2026-12-31")).toHaveLength(365);
  });

  it("returns nothing for an absent, unparsable or inverted range", () => {
    expect(dayRange(null, "2026-09-01")).toEqual([]);
    expect(dayRange("2026-09-01", null)).toEqual([]);
    expect(dayRange("nonsense", "2026-09-01")).toEqual([]);
    expect(dayRange("2026-09-04", "2026-09-01")).toEqual([]);
  });

  it("is one day long when both ends are the same day", () =>
    expect(dayRange("2026-09-04", "2026-09-04")).toEqual(["2026-09-04"]));

  it("refuses to materialise a malformed range", () =>
    expect(dayRange("1990-01-01", "2026-01-01").length).toBeLessThanOrEqual(400));
});

describe("dayLabel", () => {
  it("labels an axis tick", () =>
    expect(dayLabel("2026-09-04", { locale: "en-GB" })).toBe("4 Sept"));

  it("labels a tooltip", () =>
    expect(dayLabel("2026-09-04", { long: true, locale: "en-GB" })).toBe("Fri 4 September"));

  it("stays on the bucket's own day regardless of the reader's timezone", () => {
    // A label formatted in local time moves a UTC-midnight bucket to the
    // previous day for anyone west of Greenwich.
    expect(dayLabel("2026-01-01T00:00:00Z", { locale: "en-GB" })).toBe("1 Jan");
  });

  it("says nothing when there is no day", () => {
    expect(dayLabel(null)).toBe("—");
    expect(dayLabel("not a day")).toBe("—");
  });
});

describe("pivot", () => {
  it("transposes days into rows and keys into columns", () =>
    expect(
      pivot([
        point("2026-09-02", "note", 3),
        point("2026-09-01", "note", 1),
        point("2026-09-01", "preference", 2),
      ]),
    ).toEqual([
      { date: "2026-09-01", note: 1, preference: 2 },
      { date: "2026-09-02", note: 3 },
    ]));

  it("sums a key the endpoint repeats within a day", () => {
    // The pipeline endpoint emits `tokens` once per model per day, so a
    // two-model day arrives as two points for the same column.
    expect(pivot([point("2026-09-01", "tokens", 900), point("2026-09-01", "tokens", 100)])).toEqual([
      { date: "2026-09-01", tokens: 1000 },
    ]);
  });

  it("drops points that belong to no day and values that are not numbers", () => {
    expect(pivot([point(null, "note", 4)])).toEqual([]);
    expect(pivot([point("2026-09-01", "note", Number.NaN)])).toEqual([]);
  });

  it("sorts by day rather than by arrival", () =>
    expect(
      pivot([point("2026-10-01", "a", 1), point("2026-09-30", "a", 1)]).map((row) => row.date),
    ).toEqual(["2026-09-30", "2026-10-01"]));
});

describe("fillDays", () => {
  const rows: Row[] = [{ date: "2026-09-01", added: 4 }, { date: "2026-09-03", added: 2 }];

  it("turns a gap into a zero instead of a straight line", () =>
    expect(fillDays(rows, dayRange("2026-09-01", "2026-09-03"), ["added"])).toEqual([
      { date: "2026-09-01", added: 4 },
      { date: "2026-09-02", added: 0 },
      { date: "2026-09-03", added: 2 },
    ]));

  it("gives every row every column so a stack does not lose a band", () =>
    expect(fillDays(rows.slice(0, 1), ["2026-09-01"], ["added", "deleted"])).toEqual([
      { date: "2026-09-01", added: 4, deleted: 0 },
    ]));

  it("keeps a day that falls outside the stated range", () =>
    expect(
      fillDays(rows, dayRange("2026-09-01", "2026-09-02"), ["added"]).map((row) => row.date),
    ).toEqual(["2026-09-01", "2026-09-02", "2026-09-03"]));

  it("falls back to the rows it has when the range is unusable", () =>
    expect(fillDays(rows, [], ["added"])).toEqual([
      { date: "2026-09-01", added: 4 },
      { date: "2026-09-03", added: 2 },
    ]));
});

describe("seriesKeys and totals", () => {
  const points = [
    point("2026-09-01", "note", 1),
    point("2026-09-02", "note", 1),
    point("2026-09-01", "preference", 5),
    point("2026-09-01", "fact", 5),
  ];

  it("counts each key across the window", () =>
    expect(totalsByKey(points)).toEqual({ note: 2, preference: 5, fact: 5 }));

  it("orders by size, then by name so a redraw does not reshuffle the stack", () =>
    expect(seriesKeys(points)).toEqual(["fact", "preference", "note"]));

  it("reads one key's total", () => {
    expect(sumOf(points, "note")).toBe(2);
    expect(sumOf(points, "absent")).toBe(0);
  });

  it("reads a column total off the rows a chart was given", () =>
    expect(sumColumn(pivot(points), "note")).toBe(2));
});

describe("chartRows", () => {
  it("fills the envelope's whole range, not just the days with data", () => {
    const rows = chartRows({
      from: "2026-09-01T00:00:00Z",
      to: "2026-09-04T00:00:00Z",
      series: [point("2026-09-02", "added", 3)],
    });
    expect(rows).toEqual([
      { date: "2026-09-01", added: 0 },
      { date: "2026-09-02", added: 3 },
      { date: "2026-09-03", added: 0 },
      { date: "2026-09-04", added: 0 },
    ]);
  });

  it("draws only the columns a panel asked for, in that order", () => {
    const rows = chartRows(
      { from: "2026-09-01", to: "2026-09-01", series: [point("2026-09-01", "added", 3), point("2026-09-01", "cost:sonnet", 2)] },
      ["cost:sonnet"],
    );
    expect(rows).toEqual([{ date: "2026-09-01", "cost:sonnet": 2 }]);
  });

  it("survives an absent response", () => expect(chartRows(undefined)).toEqual([]));
});

describe("rates and denominators", () => {
  it("computes a percentage", () => expect(percent(3, 12)).toBe(25));

  it("refuses to invent one without a denominator", () => {
    expect(percent(3, 0)).toBeNull();
    expect(percent(Number.NaN, 10)).toBeNull();
  });

  it("renders a 0-1 rate, and an unknown rate as unknown rather than zero", () => {
    expect(formatRate(0.8421)).toBe("84%");
    expect(formatRate(0.8421, 1)).toBe("84.2%");
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(null)).toBe("—");
    expect(formatRate(undefined)).toBe("—");
  });
});

describe("compact", () => {
  it("leaves small numbers alone", () => {
    expect(compact(0)).toBe("0");
    expect(compact(42)).toBe("42");
    expect(compact(999)).toBe("999");
    expect(compact(12.34)).toBe("12.3");
  });

  it("shortens with one decimal at most", () => {
    expect(compact(1000)).toBe("1k");
    expect(compact(1250)).toBe("1.3k");
    expect(compact(42_800)).toBe("42.8k");
    expect(compact(128_400)).toBe("128k");
    expect(compact(4_200_000)).toBe("4.2M");
    expect(compact(2_500_000_000)).toBe("2.5B");
  });

  it("rolls up rather than reporting a thousand thousands", () => {
    expect(compact(999_999)).toBe("1M");
    expect(compact(999_999_999)).toBe("1B");
    expect(compact(999.5)).toBe("1k");
  });

  it("keeps the sign and says nothing when there is nothing to say", () => {
    expect(compact(-1500)).toBe("-1.5k");
    expect(compact(null)).toBe("—");
    expect(compact(Number.NaN)).toBe("—");
  });
});

describe("costModels", () => {
  it("names the models the bill came from", () =>
    expect(
      costModels([
        point("2026-09-01", "cost:haiku", 0.01),
        point("2026-09-02", "cost:haiku", 0.02),
        point("2026-09-01", "cost:sonnet", 0.4),
        point("2026-09-01", "tokens", 900),
      ]),
    ).toEqual(["haiku", "sonnet"]));

  it("ignores a cost key with no model behind it", () =>
    expect(costModels([point("2026-09-01", "cost:", 1)])).toEqual([]));
});

describe("heatLevel", () => {
  it("gives zero its own shade", () => {
    expect(heatLevel(0, 10)).toBe(0);
    expect(heatLevel(-1, 10)).toBe(0);
  });

  it("spreads the rest over four shades", () => {
    expect(heatLevel(1, 100)).toBe(1);
    expect(heatLevel(25, 100)).toBe(1);
    expect(heatLevel(26, 100)).toBe(2);
    expect(heatLevel(75, 100)).toBe(3);
    expect(heatLevel(100, 100)).toBe(4);
  });

  it("stays in range when the peak is missing or exceeded", () => {
    expect(heatLevel(5, 0)).toBe(0);
    expect(heatLevel(200, 100)).toBe(4);
  });
});

describe("isBlank", () => {
  const rows = fillDays([{ date: "2026-09-02", added: 2 }], dayRange("2026-09-01", "2026-09-03"), ["added"]);

  it("is false when a single day carries anything", () => expect(isBlank(rows, ["added"])).toBe(false));

  it("is true for a window where every column is zero", () =>
    expect(isBlank(fillDays([], dayRange("2026-09-01", "2026-09-03"), ["added"]), ["added"])).toBe(true));

  it("is true with no rows or no columns", () => {
    expect(isBlank([], ["added"])).toBe(true);
    expect(isBlank(rows, [])).toBe(true);
  });
});
