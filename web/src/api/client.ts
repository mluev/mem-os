const KEY_NAME = "memkit.api-key";

export function getApiKey(): string {
  return sessionStorage.getItem(KEY_NAME) ?? "";
}

export function rememberApiKey(key: string): void {
  sessionStorage.setItem(KEY_NAME, key.trim());
  window.dispatchEvent(new Event("memkit:key-changed"));
}

export function forgetApiKey(): void {
  sessionStorage.removeItem(KEY_NAME);
  window.dispatchEvent(new Event("memkit:unauthorized"));
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  const key = getApiKey();
  if (key) headers.set("X-API-Key", key);
  if (init.body) headers.set("Content-Type", "application/json");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);
  init.signal?.addEventListener("abort", () => controller.abort(), { once: true });
  let response: Response;
  try {
    response = await fetch(path, { ...init, headers, signal: controller.signal });
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
      sessionStorage.removeItem(KEY_NAME);
      window.dispatchEvent(new Event("memkit:unauthorized"));
    }
    throw new ApiError(message, response.status);
  }
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
