import { telegramLaunch } from "@/entities/session/telegram";
import { api, body } from "@/shared/api";

export type ExportPoint = {
  name: string;
  latitude: number;
  longitude: number;
  description?: string;
};

export type DownloadResult =
  | { status: "telegram-accepted"; filename: string }
  | { status: "saved"; filename: string }
  | { status: "shared"; filename: string }
  | { status: "requested"; filename: string }
  | { status: "cancelled"; filename: string }
  | { status: "manual"; filename: string; content: string };

type SaveFileHandle = {
  createWritable: () => Promise<{
    write: (data: Blob) => Promise<void>;
    close: () => Promise<void>;
  }>;
};

type SavePickerWindow = Window & {
  showSaveFilePicker?: (options: {
    suggestedName: string;
  }) => Promise<SaveFileHandle>;
};

type TelegramDownloadWebApp = {
  isVersionAtLeast?: (version: string) => boolean;
  downloadFile?: (
    params: { url: string; file_name: string },
    callback?: (accepted: boolean) => void,
  ) => void;
};

type TelegramDownloadWindow = Window & {
  Telegram?: { WebApp?: TelegramDownloadWebApp };
};

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function safeFilename(name: string, extension: string): string {
  const base = (name || "route")
    .trim()
    .replace(/[^\p{L}\p{N}_ -]+/gu, "")
    .replace(/\s+/g, "_")
    .slice(0, 80);

  return `${base || "route"}.${extension}`;
}

function isCancelled(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function downloadText(
  filename: string,
  content: string,
  mime: string,
): Promise<DownloadResult> {
  const file = new File([content], filename, { type: mime });
  const isMiniApp = telegramLaunch(window).isMiniApp;

  if (isMiniApp) {
    const tg = (window as TelegramDownloadWindow).Telegram?.WebApp;

    // Telegram Mini Apps API 8.0+: нативный запрос на скачивание.
    // Метод принимает HTTPS URL, поэтому передаём готовый XML в Next.js,
    // а не в FastAPI. Next.js создаёт временную публичную ссылку.
    if (
      tg?.isVersionAtLeast?.("8.0") &&
      typeof tg.downloadFile === "function"
    ) {
      const { path } = await api<{ path: string }>("/exports", {
        method: "POST",
        body: body({ filename, content, mime }),
      });
      const url = new URL(path, window.location.origin);
      if (url.origin !== window.location.origin || url.protocol !== "https:") {
        throw new Error("Для Telegram нужен публичный HTTPS-адрес экспорта");
      }

      // Accepted означает только согласие пользователя, не завершение загрузки.
      return new Promise<DownloadResult>((resolve, reject) => {
        try {
          tg.downloadFile!(
            { url: url.href, file_name: filename },
            (accepted) => resolve({
              status: accepted ? "telegram-accepted" : "cancelled",
              filename,
            }),
          );
        } catch (error) {
          reject(error);
        }
      });
    }

    // Для старых Telegram-клиентов: браузерный диалог сохранения. 
    const pickerWindow = window as SavePickerWindow;

    if (typeof pickerWindow.showSaveFilePicker === "function") {
      try {
        // Вызываем на объекте window, чтобы не терять контекст метода.
        const handle = await pickerWindow.showSaveFilePicker({
          suggestedName: filename,
        });
        const writable = await handle.createWritable();
        await writable.write(file);
        await writable.close();
        return { status: "saved", filename };
      } catch (error) {
        if (isCancelled(error)) return { status: "cancelled", filename };
        console.warn("[Export] File picker failed:", error);
      }
    }

    // 2. Системное меню передачи файла (чаще доступно на телефонах).
    if (
      typeof navigator.share === "function" &&
      navigator.canShare?.({ files: [file] })
    ) {
      try {
        await navigator.share({ files: [file], title: filename });
        return { status: "shared", filename };
      } catch (error) {
        if (isCancelled(error)) return { status: "cancelled", filename };
        console.warn("[Export] File share failed:", error);
      }
    }

    // 3. Telegram Desktop Linux: не показываем ложное «Файл скачан».
    // Вызывающий React-компонент должен показать content и кнопку копирования.
    return { status: "manual", filename, content };
  }

  // Обычный браузер: скачивание через Blob URL.
  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);

  // Это запрос на скачивание, а не подтверждение сохранения на диск.
  return { status: "requested", filename };
}

export function buildKml(routeName: string, points: ExportPoint[]): string {
  const placemarks = points
    .map((point) => {
      const description = point.description
        ? `\n      <description>${escapeXml(point.description)}</description>`
        : "";

      return `    <Placemark>
      <name>${escapeXml(point.name)}</name>${description}
      <Point><coordinates>${point.longitude},${point.latitude},0</coordinates></Point>
    </Placemark>`;
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>${escapeXml(routeName)}</name>
${placemarks}
  </Document>
</kml>
`;
}

export function buildGpx(routeName: string, points: ExportPoint[]): string {
  const waypoints = points
    .map((point) => {
      const description = point.description
        ? `\n    <desc>${escapeXml(point.description)}</desc>`
        : "";

      return `  <wpt lat="${point.latitude}" lon="${point.longitude}">
    <name>${escapeXml(point.name)}</name>${description}
  </wpt>`;
    })
    .join("\n");

  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="UrbexFinder" xmlns="http://www.topografix.com/GPX/1/1">
  <metadata>
    <name>${escapeXml(routeName)}</name>
  </metadata>
${waypoints}
</gpx>
`;
}

export function downloadRouteKml(
  routeName: string,
  points: ExportPoint[],
): Promise<DownloadResult> {
  return downloadText(
    safeFilename(routeName, "kml"),
    buildKml(routeName, points),
    "application/vnd.google-earth.kml+xml",
  );
}

export function downloadRouteGpx(
  routeName: string,
  points: ExportPoint[],
): Promise<DownloadResult> {
  return downloadText(
    safeFilename(routeName, "gpx"),
    buildGpx(routeName, points),
    "application/gpx+xml",
  );
}
