import { copyFile, mkdir } from "node:fs/promises";
const destination = new URL("../public/vendor/maplibre/", import.meta.url);
await mkdir(destination, { recursive: true });
for (const name of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  await copyFile(
    new URL("../node_modules/maplibre-gl/dist/" + name, import.meta.url),
    new URL(name, destination),
  );
}
await copyFile(
  new URL("../node_modules/maplibre-gl/LICENSE.txt", import.meta.url),
  new URL("LICENSE.txt", destination),
);
