import { describe, expect, it } from "vitest";
import { isUnchanged, wordDiff } from "./MemoryDiff";

/**
 * The parts must reassemble into the texts they came from — exactly for the
 * newer one, and up to whitespace for the older, since a shared run is shown
 * with the newer text's spacing.
 */
function rebuild(parts: ReturnType<typeof wordDiff>, side: "before" | "after"): string {
  const keep = side === "before" ? ["same", "removed"] : ["same", "added"];
  return parts
    .filter((part) => keep.includes(part.op))
    .map((part) => part.text)
    .join("");
}

describe("word diff", () => {
  it("reports an unchanged text as one shared run", () => {
    const parts = wordDiff("Prefers pnpm", "Prefers pnpm");
    expect(parts).toEqual([{ op: "same", text: "Prefers pnpm" }]);
    expect(isUnchanged(parts)).toBe(true);
  });

  it("isolates an inserted word", () => {
    const parts = wordDiff("Prefers pnpm for installs", "Prefers pnpm for all installs");
    expect(parts).toEqual([
      { op: "same", text: "Prefers pnpm for " },
      { op: "added", text: "all " },
      { op: "same", text: "installs" },
    ]);
    expect(isUnchanged(parts)).toBe(false);
  });

  it("isolates a removed word", () => {
    expect(wordDiff("never force pushes to master", "never pushes to master")).toEqual([
      { op: "same", text: "never " },
      { op: "removed", text: "force " },
      { op: "same", text: "pushes to master" },
    ]);
  });

  it("reports a replacement as a removal beside an addition", () => {
    expect(wordDiff("deploys on Friday", "deploys on Monday")).toEqual([
      { op: "same", text: "deploys on " },
      { op: "removed", text: "Friday" },
      { op: "added", text: "Monday" },
    ]);
  });

  it("handles an empty side in either direction", () => {
    expect(wordDiff("", "Prefers pnpm")).toEqual([{ op: "added", text: "Prefers pnpm" }]);
    expect(wordDiff("Prefers pnpm", "")).toEqual([{ op: "removed", text: "Prefers pnpm" }]);
    expect(wordDiff("", "")).toEqual([]);
    expect(isUnchanged(wordDiff("", ""))).toBe(true);
  });

  // Rewrapping a sentence is not an edit, and marking it up as one buries the
  // edit the reader is actually looking for.
  it("does not report a whitespace-only change as a change", () => {
    expect(wordDiff("Prefers  pnpm", "Prefers pnpm")).toEqual([
      { op: "same", text: "Prefers pnpm" },
    ]);
    expect(isUnchanged(wordDiff("Prefers pnpm\n", "Prefers pnpm"))).toBe(true);
  });

  it("never emits a whitespace-only part", () => {
    for (const part of wordDiff("a  b   c", "a b c d")) {
      expect(part.text.trim()).not.toBe("");
    }
  });

  it("reassembles both texts exactly, punctuation and non-Latin script included", () => {
    const before = "Предпочитает pnpm, не npm — всегда.";
    const after = "Предпочитает pnpm и uv, не npm — всегда.";
    const parts = wordDiff(before, after);
    expect(rebuild(parts, "before")).toBe(before);
    expect(rebuild(parts, "after")).toBe(after);
    expect(parts.some((part) => part.op === "added")).toBe(true);
  });

  it("keeps the shared words when a sentence is rewritten around them", () => {
    const parts = wordDiff(
      "The team reviews migrations before merge",
      "The team reviews every migration before merge",
    );
    expect(rebuild(parts, "before")).toBe("The team reviews migrations before merge");
    expect(rebuild(parts, "after")).toBe("The team reviews every migration before merge");
    expect(parts.filter((part) => part.op === "same").map((part) => part.text)).toEqual([
      "The team reviews ",
      "before merge",
    ]);
  });
});
