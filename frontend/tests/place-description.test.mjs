import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { chromium } from "@playwright/test";
import ts from "typescript";

// Run the actual renderer with the browser's HTML parser and React runtime.
test("place descriptions preserve formatting and links without executable HTML", async () => {
  const source = readFileSync(
    new URL("../src/widgets/place-detail/description.tsx", import.meta.url),
    "utf8",
  );
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  }).outputText;
  const react = readFileSync(
    new URL("../node_modules/react/cjs/react.production.js", import.meta.url),
    "utf8",
  );
  const jsx = readFileSync(
    new URL(
      "../node_modules/react/cjs/react-jsx-runtime.production.js",
      import.meta.url,
    ),
    "utf8",
  );
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const result = await page.evaluate(
      ({ compiled, react, jsx }) => {
        function load(source, require = () => {}) {
          const loaded = { exports: {} };
          new Function("module", "exports", "require", source)(
            loaded,
            loaded.exports,
            require,
          );
          return loaded.exports;
        }
        const runtime = load(react);
        const jsxRuntime = load(jsx, () => runtime);
        const { renderDescription } = load(compiled, (name) =>
          name === "react" ? runtime : jsxRuntime,
        );
        function inspect(node) {
          if (Array.isArray(node)) return node.flatMap(inspect);
          if (node == null) return [];
          if (typeof node === "string") return [node];
          return [
            {
              tag: node.type,
              props: Object.fromEntries(
                Object.entries(node.props).filter(
                  ([key]) => key !== "children",
                ),
              ),
              children: inspect(node.props.children),
            },
          ];
        }
        return inspect(
          renderDescription(
            '<p>Текст &amp; <strong>жирный</strong><br>строка</p><ul><li>Пункт</li></ul><a href="https://example.com/?a=1&amp;b=2" onclick="alert(1)">Источник</a> https://example.org/path. <script>alert(1)</script><img src=x onerror="alert(1)"><a href="java&#x73;cript:alert(1)">Плохая ссылка</a><svg onload="alert(1)"></svg><code>https://code.example</code>' +
              String.raw`Об объекте. Запланированный карьер.\<br>\<br>[http://urban3p.ru/object9433/](http://urban3p.ru/object9433/)` +
              "&lt;br&gt;&lt;br&gt;[Источник](https://example.net/) [Опасная](javascript:evil)",
          ),
        );
      },
      { compiled, react, jsx },
    );
    const nodes = [];
    function walk(items) {
      for (const item of items)
        if (typeof item === "object") {
          nodes.push(item);
          walk(item.children);
        }
    }
    walk(result);
    assert.ok(
      nodes.some(
        (node) => node.tag === "strong" && node.children.includes("жирный"),
      ),
    );
    assert.ok(
      nodes.some(
        (node) => node.tag === "li" && node.children.includes("Пункт"),
      ),
    );
    assert.equal(nodes.filter((node) => node.tag === "br").length, 5);
    assert.ok(!JSON.stringify(result).includes("[http://urban3p"));
    assert.ok(!JSON.stringify(result).includes("javascript:"));
    assert.ok(!JSON.stringify(result).includes(String.raw`\\`));
    const links = nodes.filter((node) => node.tag === "a");
    assert.deepEqual(
      links.map((node) => node.props.href),
      [
        "https://example.com/?a=1&b=2",
        "https://example.org/path",
        "http://urban3p.ru/object9433/",
        "https://example.net/",
      ],
    );
    assert.ok(
      links.every(
        (node) =>
          node.props.rel === "noopener noreferrer" &&
          node.props.target === "_blank",
      ),
    );
    assert.ok(
      !nodes.some((node) => ["script", "img", "svg"].includes(node.tag)),
    );
    assert.ok(
      nodes.every(
        (node) => !Object.keys(node.props).some((key) => key.startsWith("on")),
      ),
    );
    assert.ok(JSON.stringify(result).includes("Плохая ссылка"));
    assert.ok(!JSON.stringify(result).includes("alert(1)"));
  } finally {
    await browser.close();
  }
});
