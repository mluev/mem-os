import { describe, expect, it } from "vitest";
import { dateTime, duration, integer, money, relativeTime } from "./format";

describe("format", () => {
  it("formats money and durations", () => {
    expect(money(0.125)).toBe("$0.1250");
    expect(money(null)).toBe("$0.0000");
    expect(duration(null)).toBe("—");
    expect(duration(940)).toBe("940ms");
    expect(duration(1500)).toBe("1.5s");
  });

  it("says never rather than inventing a relative time", () => {
    expect(relativeTime(null)).toBe("never");
  });

  // The exact rendering is the reader's locale and timezone, so assert only
  // what the caller depends on: a real instant renders, an absent one is a dash
  // rather than "Invalid Date".
  it("renders an exact instant, and a dash when there is none", () => {
    expect(dateTime("2026-09-04T12:00:00Z")).toContain("2026");
    expect(dateTime(null)).toBe("—");
    expect(dateTime("not a date")).toBe("—");
  });

  it("groups integers and refuses to guess at a missing one", () => {
    expect(integer(1234)).toBe((1234).toLocaleString());
    expect(integer(null)).toBe("—");
  });
});
