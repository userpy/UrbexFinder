
import { telegramLaunch } from "@/entities/session/telegram";

export type ExportPoint = {
  name: string;
  latitude: number;
  longitude: number;
  description?: string;
};

export type DownloadResult =
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

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function safeFilename(
  name: string,
  extension: string,
): string {
  const base = (name || "route")
    .trim()
    .replace(/[^\p{L}\p{N}_ -]+/gu, "")
    .replace(/\s+/g, "_")
    .slice(0, 80);

  return `${base || "route"}.${extension}`;
}

function isCancelled(error: unknown): boolean {
  return (
    error instanceof DOMException &&
    error.name === "AbortError"
  );
}

async function downloadText(
  filename: string,
  content: string,
  mime: string,
): Promise<DownloadResult> {
  const file = new File([content], filename, {
    type: mime,
  });

  const isMiniApp = telegramLaunch(window).isMiniApp;

  if (isMiniApp) {
    // 1. Пробуем системный диалог сохранения.
    const pickerWindow = window as SavePickerWindow;

    if (
      typeof pickerWindow.showSaveFilePicker === "function"
    ) {
      try {
        const handle =
          await pickerWindow.showSaveFilePicker({
            suggestedName: filename,
          });

        const writable = await handle.createWritable();

        await writable.write(file);
        await writable.close();

        return { status: "saved", filename };
      } catch (error) {
        if (isCancelled(error)) {
          return { status: "cancelled", filename };
        }

        console.warn(
          "[Export] File picker failed:",
          error
        );
      }
    }

    // 2. Пробуем системное меню передачи файла.
    if (
      typeof navigator.share === "function" &&
      navigator.canShare?.({ files: [file] })
    ) {
      try {
        await navigator.share({
          files: [file],
          title: filename,
        });

        return { status: "shared", filename };
      } catch (error) {
        if (isCancelled(error)) {
          return { status: "cancelled", filename };
        }

        console.warn(
          "[Export] File share failed:",
          error
        );
      }
    }

    // 3. Резервный вариант для Telegram Desktop.
    // Возвращаем XML для ручного сохранения.
    return {
      status: "manual",
      filename,
      content,
    };
  }

  // 4. Обычный браузер.
  const url = URL.createObjectURL(file);

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;

  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 10000);

  // Запрос отправлен, но запись на диск не подтверждена.
  return { status: "requested", filename };
}

export function buildKml(
  routeName: string,
  points: ExportPoint[],
): string {
  const placemarks = points
    .map((point) => {
      const description = point.description
        ? `
      <description>${escapeXml(point.description)}</description>`
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

export function buildGpx(
  routeName: string,
  points: ExportPoint[],
): string {
  const waypoints = points
    .map((point) => {
      const description = point.description
        ? `
    <desc>${escapeXml(point.description)}</desc>`
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
