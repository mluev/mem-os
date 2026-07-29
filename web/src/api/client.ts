const KEY_NAME = "memkit.api-key";

export function getApiKey(): string {
  return localStorage.getItem(KEY_NAME) ?? "";
}

export function rememberApiKey(key: string): void {
  localStorage.setItem(KEY_NAME, key.trim());
  window.dispatchEvent(new Event("memkit:key-changed"));
}

export function forgetApiKey(): void {
  localStorage.removeItem(KEY_NAME);
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
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      // Preserve the HTTP fallback.
    }
    if (response.status === 401) {
      localStorage.removeItem(KEY_NAME);
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
