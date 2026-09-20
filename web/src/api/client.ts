/**
 * HTTP access for the dashboard.
 *
 * The dashboard authenticates with a session cookie, not an API key. The
 * browser attaches that cookie to any request to this origin, including one
 * another site provokes, so every mutation also carries a header no
 * cross-origin form is able to set. That header is the CSRF defence and it
 * works because the service keeps CORS closed.
 *
 * An API key is still accepted, and the dev proxy injects one, so a checkout
 * running against a local service works without signing in.
 */

const CSRF_HEADER = "X-Requested-With";
const CSRF_VALUE = "memkit";
const DEV_KEY_NAME = "memkit.api-key";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** A key typed in by hand, for a checkout talking to a local service. */
export function getApiKey(): string {
  return sessionStorage.getItem(DEV_KEY_NAME) ?? "";
}

export function rememberApiKey(key: string): void {
  sessionStorage.setItem(DEV_KEY_NAME, key.trim());
  window.dispatchEvent(new Event("memkit:identity-changed"));
}

export function forgetApiKey(): void {
  sessionStorage.removeItem(DEV_KEY_NAME);
  window.dispatchEvent(new Event("memkit:unauthorized"));
}

const UNSAFE = new Set(["POST", "PATCH", "PUT", "DELETE"]);

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  const key = getApiKey();
  if (key) headers.set("X-API-Key", key);
  if (UNSAFE.has(method)) headers.set(CSRF_HEADER, CSRF_VALUE);
  if (init.body) headers.set("Content-Type", "application/json");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  init.signal?.addEventListener("abort", () => controller.abort(), { once: true });
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      method,
      headers,
      credentials: "same-origin",
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeout);
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      // Preserve the HTTP fallback.
    }
    if (response.status === 401) {
      sessionStorage.removeItem(DEV_KEY_NAME);
      window.dispatchEvent(new Event("memkit:unauthorized"));
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function queryString(
  values: Record<string, string | number | boolean | null | undefined>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}
