import { describe, expect, it } from "vitest";
import { spanContext, spanState, verifySpans } from "./MemoryEvidence";

const MESSAGE = "We agreed to use pnpm everywhere, and never npm, for every service.";

describe("evidence spans", () => {
  it("respects the server's verdict for pre-sliced evidence", async () => {
    const base = { message_id: 1, start_char: 0, end_char: 5, excerpt: "drift", role: "user", created_at: null };
    const spans = await verifySpans([
      { ...base, verified: false }, { ...base, verified: true }, base,
    ]);
    expect(spans.map((span) => span.state)).toEqual(["unverified", "verified", "unchecked"]);
  });

  it("interprets stored character offsets as Unicode code points", () => {
    expect(spanContext("😀 Use pnpm.", 6, 10, 0)?.excerpt).toBe("pnpm");
  });
  it("slices the span and keeps a little of the message around it", () => {
    const start = MESSAGE.indexOf("pnpm");
    const context = spanContext(MESSAGE, start, start + 4, 8);
    expect(context).toEqual({
      before: `…${MESSAGE.slice(start - 8, start)}`,
      excerpt: "pnpm",
      after: `${MESSAGE.slice(start + 4, start + 12)}…`,
    });
  });

  it("does not ellipsize when the window reaches the ends of the message", () => {
    expect(spanContext(MESSAGE, 0, 2, 500)).toEqual({
      before: "",
      excerpt: "We",
      after: MESSAGE.slice(2),
    });
  });

  // Offsets that no longer land inside the retained message are exactly the
  // drift the recorded hash exists to catch.
  it("refuses offsets that do not land inside the message", () => {
    expect(spanContext(MESSAGE, 5, 9999)).toBeNull();
    expect(spanContext(MESSAGE, -1, 4)).toBeNull();
    expect(spanContext(MESSAGE, 10, 10)).toBeNull();
    expect(spanContext(MESSAGE, 10, 4)).toBeNull();
    expect(spanContext(MESSAGE, 1.5, 4)).toBeNull();
    expect(spanContext(null, 0, 4)).toBeNull();
    expect(spanContext(undefined, 0, 4)).toBeNull();
  });

  it("verifies a span only when the re-sliced text hashes to the recorded value", () => {
    expect(spanState("pnpm", "abc", "abc")).toBe("verified");
    expect(spanState("pnpm", "ABC", "abc")).toBe("verified");
    expect(spanState("pnpm", "abc", "def")).toBe("unverified");
  });

  it("says unverified when the span cannot be taken at all", () => {
    expect(spanState(null, "abc", "abc")).toBe("unverified");
  });

  it("says unchecked rather than implying a check that never ran", () => {
    // No hash was stored for this span…
    expect(spanState("pnpm", null, "abc")).toBe("unchecked");
    expect(spanState("pnpm", "", "abc")).toBe("unchecked");
    // …or this browser has no crypto.subtle to hash with.
    expect(spanState("pnpm", "abc", null)).toBe("unchecked");
  });
});
