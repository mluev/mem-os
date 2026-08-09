import createClient from "openapi-fetch";
import type { paths } from "./schema.js";

export type MemkitClientOptions = { baseUrl: string; apiKey: string };

export function createMemkitClient({ baseUrl, apiKey }: MemkitClientOptions) {
  return createClient<paths>({
    baseUrl: baseUrl.replace(/\/$/, ""),
    headers: { "X-API-Key": apiKey },
  });
}

export type { paths } from "./schema.js";
