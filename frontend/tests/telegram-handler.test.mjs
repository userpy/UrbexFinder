import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(
  new URL("../app/api/itineraries/[id]/telegram/route.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const { POST } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);
const context = { params: Promise.resolve({ id: "42" }) };
function request(origin = "https://site.example") {
  return new Request("http://web:3100/api/itineraries/42/telegram", {
    method: "POST",
    headers: {
      ...(origin ? { origin } : {}),
      cookie: "urbex_session=test-session",
      "x-csrf-token": "test-csrf",
      "x-forwarded-host": "evil.example",
    },
  });
}

test("server forwards to internal API with original security headers", async (t) => {
  const old = process.env.API_INTERNAL_URL;
  process.env.API_INTERNAL_URL = "http://api:8000";
  t.after(() => {
    if (old === undefined) delete process.env.API_INTERNAL_URL;
    else process.env.API_INTERNAL_URL = old;
  });
  t.mock.method(globalThis, "fetch", async (url, init) => {
    assert.equal(String(url), "http://api:8000/api/itineraries/42/telegram");
    assert.equal(init.method, "POST");
    assert.equal(init.headers.get("origin"), "https://site.example");
    assert.equal(init.headers.get("cookie"), "urbex_session=test-session");
    assert.equal(init.headers.get("x-csrf-token"), "test-csrf");
    assert.equal(init.headers.has("x-forwarded-host"), false);
    assert.equal(init.redirect, "error");
    return Response.json({ sent: true });
  });
  const result = await POST(request(), context);
  assert.equal(result.status, 200);
  assert.equal(result.headers.get("cache-control"), "no-store");
  assert.deepEqual(await result.json(), { sent: true });
});

test("missing origin and invalid IDs never reach API", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", () => {
    throw Error("unexpected");
  });
  assert.equal((await POST(request(""), context)).status, 403);
  assert.equal((await POST(request("null"), context)).status, 403);
  assert.equal(
    (await POST(request(), { params: Promise.resolve({ id: "../other" }) }))
      .status,
    400,
  );
  assert.equal(fetch.mock.callCount(), 0);
});

test("API authentication, CSRF, ownership and partial delivery errors survive", async (t) => {
  for (const status of [401, 403, 404, 502]) {
    const mock = t.mock.method(globalThis, "fetch", async () =>
      Response.json({ detail: "Ошибка API" }, { status }),
    );
    const result = await POST(request("https://evil.example"), context);
    assert.equal(result.status, status);
    assert.deepEqual(await result.json(), { detail: "Ошибка API" });
    mock.mock.restore();
  }
});

test("network failure is sanitized and never retried", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => {
    throw Error("internal-secret");
  });
  const result = await POST(request(), context);
  assert.equal(result.status, 502);
  assert.equal((await result.text()).includes("internal-secret"), false);
  assert.equal(fetch.mock.callCount(), 1);
});
