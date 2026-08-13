import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  api,
  forgetApiKey,
  getApiKey,
  queryString,
  rememberApiKey,
} from "./client";

const values = new Map<string, string>();
const events: string[] = [];

beforeEach(() => {
  values.clear();
  events.length = 0;
  vi.restoreAllMocks();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
  vi.stubGlobal("window", {
    setTimeout,
    clearTimeout,
    dispatchEvent: (event: Event) => {
      events.push(event.type);
      return true;
    },
  });
});

describe("API client", () => {
  it("stores a trimmed key for the session and emits lifecycle events", () => {
    rememberApiKey("  secret  ");
    expect(getApiKey()).toBe("secret");
    expect(events).toEqual(["memkit:key-changed"]);

    forgetApiKey();
    expect(getApiKey()).toBe("");
    expect(events).toEqual(["memkit:key-changed", "memkit:unauthorized"]);
  });

  it("sends the Memkit header and JSON content type", async () => {
    rememberApiKey("secret");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(api<{ ok: boolean }>("/v1/probe", { body: "{}", method: "POST" })).resolves.toEqual({
      ok: true,
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.get("X-API-Key")).toBe("secret");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("clears a rejected key and preserves the API detail", async () => {
    rememberApiKey("expired");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "invalid API key" }), {
          status: 401,
          statusText: "Unauthorized",
        }),
      ),
    );

    await expect(api("/v1/probe")).rejects.toEqual(new ApiError("invalid API key", 401));
    expect(getApiKey()).toBe("");
    expect(events.at(-1)).toBe("memkit:unauthorized");
  });

  it("encodes only meaningful query values", () => {
    expect(queryString({ status: "active", limit: 20, empty: "", cursor: null })).toBe(
      "?status=active&limit=20",
    );
  });
});
