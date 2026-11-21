
import { randomBytes } from "node:crypto";
import {
  mkdir,
  readdir,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const runtime = "nodejs";

const ROOT = join(tmpdir(), "urbexfinder-route-exports");
const TTL_MS = 15 * 60 * 1000;
const MAX_BYTES = 512 * 1024;

const NAME_RE =
  /^[\p{L}\p{N}_ -]{1,80}\.(kml|gpx)$/u;

const MIME: Record<string, string> = {
  kml: "application/vnd.google-earth.kml+xml",
  gpx: "application/gpx+xml",
};

function json(data: unknown, status: number) {
  return Response.json(data, {
    status,
    headers: {
      "Cache-Control": "no-store",
    },
  });
}

// Удаляем устаревшие временные файлы
async function clearExpired(): Promise<void> {
  await mkdir(ROOT, {
    recursive: true,
    mode: 0o700,
  });

  const entries = await readdir(ROOT, {
    withFileTypes: true,
  });

  const now = Date.now();

  for (const entry of entries) {
    if (
      !entry.isDirectory() ||
      !/^[a-f0-9]{48}$/.test(entry.name)
    ) {
      continue;
    }

    const dir = join(ROOT, entry.name);

    try {
      const info = await stat(dir);

      if (now - info.mtimeMs > TTL_MS) {
        await rm(dir, {
          recursive: true,
          force: true,
        });
      }
    } catch {
      // Файл уже мог быть удалён
    }
  }
}

// Проверка существующей сессии FastAPI.
// Новый endpoint в FastAPI не создаём.
async function hasSession(
  request: Request
): Promise<boolean> {
  const cookie = request.headers.get("cookie");

  if (!cookie) return false;

  const base =
    process.env.API_INTERNAL_URL ||
    "http://127.0.0.1:58000";

  const response = await fetch(
    new URL("/api/auth/me", base),
    {
      method: "GET",
      headers: {
        Cookie: cookie,
      },
      cache: "no-store",
      redirect: "error",
    }
  );

  if (!response.ok) return false;

  const data: unknown = await response.json();

  return Boolean(
    data &&
    typeof data === "object" &&
    "user" in data &&
    (data as { user: unknown }).user
  );
}

// POST /api/exports
export async function POST(request: Request) {
  const expectedOrigin =
    process.env.EXPORT_PUBLIC_ORIGIN ||
    new URL(request.url).origin;

  if (
    request.headers.get("origin") !==
    expectedOrigin
  ) {
    return json(
      { detail: "Недопустимый источник запроса" },
      403
    );
  }

  const declaredSize = Number(
    request.headers.get("content-length") || 0
  );

  if (declaredSize > MAX_BYTES * 2) {
    return json(
      { detail: "Превышен размер запроса" },
      413
    );
  }

  try {
    if (!(await hasSession(request))) {
      return json(
        { detail: "Необходима авторизация" },
        401
      );
    }
  } catch {
    return json(
      { detail: "Не удалось проверить сессию" },
      502
    );
  }

  // Дополнительное ограничение размера
  // фактически прочитанного тела запроса.
  let raw = "";
  try {
    const reader = request.body?.getReader();

    if (!reader) {
      return json({ detail: "Пустой запрос" }, 400);
    }

    const decoder = new TextDecoder();
    let bytesReceived = 0;
    const limit = MAX_BYTES * 2;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      bytesReceived += value.byteLength;

      if (bytesReceived > limit) {
        await reader.cancel();
        return json(
          { detail: "Превышен размер запроса" },
          413
        );
      }

      raw += decoder.decode(value, { stream: true });
    }

    raw += decoder.decode();
  } catch {
    return json(
      { detail: "Ошибка чтения запроса" },
      400
    );
  }

  let data: unknown;

  try {
    data = JSON.parse(raw);
  } catch {
    return json(
      { detail: "Некорректный JSON" },
      400
    );
  }

  if (!data || typeof data !== "object") {
    return json(
      { detail: "Ожидался объект" },
      400
    );
  }

  const { filename, content, mime } =
    data as Record<string, unknown>;

  if (
    typeof filename !== "string" ||
    typeof content !== "string" ||
    typeof mime !== "string"
  ) {
    return json(
      { detail: "Некорректные параметры экспорта" },
      400
    );
  }

  const matched = NAME_RE.exec(filename);

  if (!matched || mime !== MIME[matched[1]]) {
    return json(
      { detail: "Допустимы только KML и GPX" },
      400
    );
  }

  const bytes = Buffer.from(content, "utf8");

  if (
    bytes.length === 0 ||
    bytes.length > MAX_BYTES
  ) {
    return json(
      { detail: "Недопустимый размер файла" },
      413
    );
  }

  try {
    await clearExpired();

    const token = randomBytes(24).toString("hex");
    const directory = join(ROOT, token);

    await mkdir(directory, {
      mode: 0o700,
    });

    await writeFile(
      join(directory, filename),
      bytes,
      {
        flag: "wx",
        mode: 0o600,
      }
    );

    return json(
      {
        path:
          `/api/exports/${token}/` +
          encodeURIComponent(filename),
      },
      201
    );
  } catch {
    return json(
      {
        detail:
          "Не удалось подготовить файл экспорта",
      },
      500
    );
  }
}
