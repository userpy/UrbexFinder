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

function downloadText(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
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
