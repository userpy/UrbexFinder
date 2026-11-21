import {
  readFile,
  stat,
} from "node:fs/promises";

import { tmpdir } from "node:os";
import { join } from "node:path";

export const runtime = "nodejs";

const ROOT = join(
  tmpdir(),
  "urbexfinder-route-exports"
);

const TTL_MS = 15 * 60 * 1000;

const MIME: Record<string, string> = {
  kml: "application/vnd.google-earth.kml+xml",
  gpx: "application/gpx+xml",
};

const NAME_RE =
  /^[\p{L}\p{N}_ -]{1,80}\.(kml|gpx)$/u;

// GET /api/exports/{token}/{filename}
export async function GET(
  _request: Request,
  context: {
    params: Promise<{
      token: string;
      filename: string;
    }>;
  }
) {
  const { token, filename } = await context.params;

  const matched = NAME_RE.exec(filename);

  if (
    !/^[a-f0-9]{48}$/.test(token) ||
    !matched
  ) {
    return new Response("Not found", {
      status: 404,
    });
  }

  const path = join(ROOT, token, filename);

  try {
    const info = await stat(path);

    if (
      !info.isFile() ||
      Date.now() - info.mtimeMs > TTL_MS
    ) {
      return new Response("Not found", {
        status: 404,
      });
    }

    const content = await readFile(path);

    // ASCII-имя для совместимости
    const ascii = filename
      .replace(/[^\x20-\x7E]/g, "_")
      .replace(/["\\]/g, "_");

    return new Response(
      new Uint8Array(content),
      {
        status: 200,
        headers: {
          "Content-Type":
            `${MIME[matched[1]]}; charset=utf-8`,

          "Content-Length":
            String(content.length),

          "Content-Disposition":
            `attachment; filename="${ascii}"; ` +
            `filename*=UTF-8''${encodeURIComponent(filename)}`,

          "Access-Control-Allow-Origin":
            "https://web.telegram.org",

          "Cache-Control":
            "private, no-store",

          "X-Content-Type-Options":
            "nosniff",
        },
      }
    );
  } catch {
    return new Response("Not found", {
      status: 404,
    });
  }
}
