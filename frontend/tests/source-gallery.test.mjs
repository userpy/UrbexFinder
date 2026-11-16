import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const require = createRequire(import.meta.url);
const compiled = ts.transpileModule(
  readFileSync(new URL("../src/widgets/place-detail/gallery.tsx", import.meta.url), "utf8"),
  { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } },
).outputText;
const loaded = { exports: {} };
new Function("module", "exports", "require", compiled)(loaded, loaded.exports, (name) => {
  if (name === "./delete-photo") return { DeletePhoto: () => null };
  if (name === "@/shared/ui/button") return { Button: (props) => React.createElement("button", props) };
  if (name === "./telegram-photo") return { PlacePhoto: ({ id }) => React.createElement("img", { src: `/api/photos/${id}/content` }) };
  return require(name);
});
const { PhotoGallery } = loaded.exports;

test("cache photos populate the main gallery, retain attribution and cannot be deleted as uploads", () => {
  const html = renderToStaticMarkup(React.createElement(PhotoGallery, {
    photos: [], name: "Не называя их…", canDelete: () => true, onDeleted: () => {},
    sourcePhotos: [1, 2, 3, 4].map((id) => ({
      image_url: `https://geocaching.su/photos/areas/${id}.jpg`,
      source_url: "https://geocaching.su/cache/18398", title: "Фото тайника",
    })),
  }));
  assert.match(html, /4 фото/);
  assert.match(html, /src="https:\/\/geocaching.su\/photos\/areas\/1.jpg"/);
  assert.match(html, /href="https:\/\/geocaching.su\/cache\/18398"/);
  assert.match(html, /Фото · Geocaching/);
  assert.doesNotMatch(html, /Удалить фото|Фотографии пока не добавлены/);
});

test("source failures are shown separately from an empty gallery", () => {
  const html = renderToStaticMarkup(React.createElement(PhotoGallery, {
    photos: [], name: "Тайник", onDeleted: () => {}, sourceStatus: "Фото источника временно недоступны",
  }));
  assert.match(html, /Фото источника временно недоступны/);
  assert.doesNotMatch(html, /Фотографии пока не добавлены/);
});


test("estate source photos retain Podmoskovnye attribution", () => {
  const html = renderToStaticMarkup(React.createElement(PhotoGallery, {
    photos: [], name: "Шилля усадьба", onDeleted: () => {},
    sourcePhotos: [{image_url: "https://podmoskovnye.ru/images/stories/photos/yaroslavskaya/shill/photo.jpg",
      source_url: "https://podmoskovnye.ru/usadba/example", title: "Шилля усадьба"}],
  }));
  assert.match(html, /Фото · Подмосковные/);
  assert.doesNotMatch(html, /Geocaching|Удалить фото/);
});
