import type { paths } from "./schema.js";
export type MemkitClientOptions = {
    baseUrl: string;
    apiKey: string;
};
export declare function createMemkitClient({ baseUrl, apiKey }: MemkitClientOptions): import("openapi-fetch").Client<paths, `${string}/${string}`>;
export type { paths } from "./schema.js";
