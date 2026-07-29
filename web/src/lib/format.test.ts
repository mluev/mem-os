import { describe, expect, it } from "vitest";
import { guessLang, money, shortId } from "./format";

describe("format", () => {
  it("detects Cyrillic", () => expect(guessLang("Предпочитает pnpm")).toBe("ru"));
  it("keeps English", () => expect(guessLang("Prefers pnpm")).toBe("en"));
  it("formats ids and money", () => {
    expect(shortId("123456789")).toBe("12345678");
    expect(money(0.125)).toBe("$0.1250");
  });
});
