import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import ts from "typescript";

const compiled = ts.transpileModule(
  readFileSync(new URL("../src/entities/place/category-visuals.tsx", import.meta.url), "utf8"),
  { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS } },
).outputText;
const loaded = { exports: {} };
new Function("module", "exports", "require", compiled)(loaded, loaded.exports, createRequire(import.meta.url));
const { categoryVisual, CategoryIcon } = loaded.exports;

test("catalog without saved icons renders distinct category shapes", () => {
  for (const [name, key] of [
    ["geocaching", "geocache"], ["Бомбоубежища", "shelter"],
    ["Заброшенные пионерские лагеря", "camp"],
    ["Красивые природные места", "nature"], ["Церкви", "church"],
    ["Заброшенные усадьбы, дома отдыха, санатории", "estate"],
    ["Школы/колледжи/институты", "school"], ["разное", "other"],
  ]) {
    for (const icon of [undefined, null, "", "invalid"]) {
      assert.equal(categoryVisual(icon, name).key, key);
      assert.equal(CategoryIcon({ category: name, icon }).props["data-category-icon"], key);
    }
  }
});

test("explicit selections take precedence and unknown names are safe", () => {
  assert.equal(categoryVisual("castle", "Церкви").key, "castle");
  assert.equal(categoryVisual("other", "Церкви").key, "other");
  assert.equal(categoryVisual(null, "unknown").key, "other");
  assert.equal(categoryVisual(null, "constructor").key, "other");
});
