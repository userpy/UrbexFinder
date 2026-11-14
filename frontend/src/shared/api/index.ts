let csrf: string | null = null;
export function setCsrf(value: string | null) {
  csrf = value;
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(`/api${path}`, {
    ...init,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) {
    const raw = await response.text().catch(() => "");
    let detail = `Сервис недоступен (${response.status})`;
    try {
      const data = JSON.parse(raw) as { detail?: unknown };
      if (typeof data.detail === "string" && data.detail.trim()) {
        detail = data.detail;
      }
    } catch {
      /* non-JSON gateway/proxy error */
    }
    throw new Error(detail);
  }
  return response.json();
}
export const body = (value: unknown) => JSON.stringify(value);
export type Page<T> = { items: T[]; total: number; page: number };
