type ExportPoint = {
  name: string;
  latitude: number;
  longitude: number;
  description?: string;
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
    .replace(/[^\p{L}\p{N}\-_ ]+/gu, "")
    .replace(/\s+/g, "_")
    .slice(0, 80);
  return `${base || "route"}.${extension}`;
}


async function downloadText(
  filename: string,
  content: string,
  mime: string
): Promise<void> {
  const tg = (
    window as Window & {
      Telegram?: {
        WebApp?: { initData?: string };
      };
    }
  ).Telegram?.WebApp;

  const isTelegram = Boolean(tg?.initData);

  // Создаём файл на фронтенде
  const file = new File([content], filename, {
    type: mime,
  });

  // Если открыто в Telegram Mini App
  if (isTelegram) {
    console.log("Telegram Mini App detected");

    if (
      typeof navigator.share === "function" &&
      navigator.canShare?.({ files: [file] })
    ) {
      try {
        await navigator.share({
          files: [file],
          title: filename,
        });

        return;
      } catch (error) {
        if (
          error instanceof DOMException &&
          error.name === "AbortError"
        ) {
          return;
        }

        console.warn("Telegram share failed:", error);
      }
    }
  }

  // Fallback: обычное скачивание
  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = filename;

  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  setTimeout(() => URL.revokeObjectURL(url), 10000);
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

export function downloadRouteKml(routeName: string, points: ExportPoint[]) {
  downloadText(
    safeFilename(routeName, "kml"),
    buildKml(routeName, points),
    "application/vnd.google-earth.kml+xml",
  );
}

export function downloadRouteGpx(routeName: string, points: ExportPoint[]) {
  downloadText(
    safeFilename(routeName, "gpx"),
    buildGpx(routeName, points),
    "application/gpx+xml",
  );
}
