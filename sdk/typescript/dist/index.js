import createClient from "openapi-fetch";
export function createMemkitClient({ baseUrl, apiKey }) {
    return createClient({
        baseUrl: baseUrl.replace(/\/$/, ""),
        headers: { "X-API-Key": apiKey },
    });
}
