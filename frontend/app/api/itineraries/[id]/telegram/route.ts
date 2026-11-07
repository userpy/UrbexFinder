export const runtime = "nodejs";

const json = (data: unknown, status: number) =>
  Response.json(data, { status, headers: { "Cache-Control": "no-store" } });

export async function POST(
  request: Request,
  context: { params: Promise<{ id: string }> },
) {
  const { id } = await context.params;
  if (!/^[1-9]\d*$/.test(id))
    return json({ detail: "Некорректный маршрут" }, 400);

  // Preserve the browser Origin: FastAPI checks it against the configured
  // public site origin, then validates the session, CSRF token and ownership.
  // Never replace it with an internal URL or trust forwarded host headers.
  const origin = request.headers.get("origin");
  if (!origin || origin === "null")
    return json({ detail: "Недопустимый источник запроса" }, 403);
  const headers = new Headers({ Origin: origin });
  for (const name of ["cookie", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  try {
    const base = process.env.API_INTERNAL_URL || "http://127.0.0.1:58000";
    const response = await fetch(
      new URL(`/api/itineraries/${id}/telegram`, base),
      {
        method: "POST",
        headers,
        cache: "no-store",
        redirect: "error",
      },
    );
    const data = await response.json();
    if (!response.ok) {
      return json(
        {
          detail:
            typeof data.detail === "string"
              ? data.detail
              : "Не удалось отправить маршрут в Telegram",
        },
        response.status,
      );
    }
    return json(data, response.status);
  } catch {
    // Delivery may have happened before a connection failure; do not retry.
    return json(
      {
        detail:
          "Не удалось получить ответ сервера. Проверьте чат Telegram перед повторной отправкой.",
      },
      502,
    );
  }
}
