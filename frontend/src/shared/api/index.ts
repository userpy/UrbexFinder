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
    const data = await response
      .json()
      .catch(() => ({ detail: "Сервис недоступен" }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Проверьте заполнение полей",
    );
  }
  return response.json();
}
export const body = (value: unknown) => JSON.stringify(value);
export type Page<T> = { items: T[]; total: number; page: number };
