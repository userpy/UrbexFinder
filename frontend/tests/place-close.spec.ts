import { expect, test } from "@playwright/test";

const place = {
  id: 42,
  name: "Карьер",
  latitude: 55.3,
  longitude: 37.7,
  region: "Москва",
  description: "Описание места",
  category_id: 1,
  condition: "unknown",
  access: "unknown",
  status: "published",
};
const stop = { place_id: place.id, note: "", status: "planned" };
const itinerary = {
  id: 1,
  name: "Поездка",
  active: true,
  stops: [stop],
  items: [{ ...stop, place }],
  version: 1,
  notes: "",
  trip_date: null,
};

for (const close of ["button", "escape"] as const) {
  for (const reportFails of [false, true]) {
    test(`closing ${reportFails ? "failed" : "cached"} report by ${close} does not reload sources`, async ({ page }) => {
      let sourceRequests = 0;
      await page.route("**/api/places/42/source-photos", (route) => {
        sourceRequests++;
        return route.fulfill({ json: { items: [] } });
      });
      await page.route("**/api/places/42/osint-report", (route) => route.fulfill(
        reportFails
          ? { status: 502, json: { detail: "Отчёт недоступен" } }
          : { json: { items: [], total: 0, cached: true } },
      ));
      await page.goto("/?place=42");
      await expect.poll(() => sourceRequests).toBe(1);
      // Reopening a saved or failed report must not trigger gallery requests either.
      for (let attempt = 0; attempt < 2; attempt++) {
        await page.getByRole("button", { name: "Подробный отчёт", exact: true }).click();
        await expect(page.getByRole("button", { name: "Обновить отчёт" })).toBeVisible();
        if (close === "button") await page.getByRole("button", { name: "Закрыть отчёт" }).click();
        else await page.keyboard.press("Escape");
        await expect(page.getByRole("dialog", { name: "Подробный отчёт" })).toHaveCount(0);
        await page.evaluate(() => new Promise<void>((resolve) => {
          requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
        }));
        expect(sourceRequests).toBe(1);
      }
    });
  }

  for (const refreshFails of [false, true]) {
    test(`report closed by ${close} keeps photos during ${refreshFails ? "failed" : "successful"} refresh`, async ({ page }) => {
      const sourcePhotos = ["a", "b", "c"].map((digest) => ({
        image_url: `/api/source-images/${digest.repeat(64)}`,
        source_url: "https://example.com/place",
        title: "Фото места",
      }));
      let requests = 0;
      let releaseRefresh!: () => void;
      const pendingRefresh = new Promise<void>((resolve) => { releaseRefresh = resolve; });
      await page.route("**/api/places/42/osint-report*", (route) => route.fulfill({
        json: {
          items: [], total: 0,
          cached: close === "escape" && !new URL(route.request().url()).searchParams.has("refresh"),
        },
      }));
      await page.route("**/api/places/42/source-photos", async (route) => {
        requests++;
        if (requests > 1) {
          await pendingRefresh;
          if (refreshFails) return route.fulfill({ status: 502, json: { detail: "Источник недоступен" } });
        }
        return route.fulfill({ json: { items: sourcePhotos.slice(0, requests === 1 ? 2 : 3) } });
      });
      await page.route("**/api/source-images/**", (route) => route.fulfill({
        contentType: "image/png",
        body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64"),
      }));
      await page.goto("/?place=42");
      await expect(page.locator(".gallery-total")).toHaveText("2 фото");
      await page.getByRole("button", { name: "Фото 2", exact: true }).click();
      const image = page.locator(".gallery-stage img");
      await expect(image).toBeVisible();
      const originalImage = await image.elementHandle();
      await page.getByRole("button", { name: "Подробный отчёт", exact: true }).click();
      await expect(page.getByRole("dialog", { name: "Подробный отчёт" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Обновить отчёт" })).toBeVisible();
      if (close === "escape") {
        const reportResponse = page.waitForResponse("**/api/places/42/osint-report?refresh=1");
        await page.getByRole("button", { name: "Обновить отчёт" }).click();
        await (await reportResponse).finished();
        await expect(page.getByRole("button", { name: "Обновить отчёт" })).toBeVisible();
      }
      if (close === "button") await page.getByRole("button", { name: "Закрыть отчёт" }).click();
      else await page.keyboard.press("Escape");
      await expect(page.getByRole("dialog", { name: "Подробный отчёт" })).toHaveCount(0);
      await expect.poll(() => requests).toBe(2);
      const refreshResponse = page.waitForResponse("**/api/places/42/source-photos");
      try {
        await expect(page.locator(".gallery-total")).toHaveText("2 фото");
        await expect(image).toBeVisible();
        expect(await originalImage!.evaluate((node) => node.isConnected)).toBe(true);
      } finally {
        releaseRefresh();
      }
      await (await refreshResponse).finished();
      await page.evaluate(() => new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }));
      await expect(page.locator(".gallery-total")).toHaveText(refreshFails ? "2 фото" : "3 фото");
      await expect(page.locator(".gallery-count")).toHaveText(refreshFails ? "2 / 2" : "2 / 3");
      await expect(image).toBeVisible();
      expect(await originalImage!.evaluate((node) => node.isConnected)).toBe(true);
    });
  }
}

test.beforeEach(async ({ page }) => {
  await page.route("https://telegram.org/js/telegram-web-app.js", (route) =>
    route.fulfill({ body: "" }),
  );
  await page.route("**/e2e-map-style.json", (route) =>
    route.fulfill({
      json: { version: 8, sources: {}, layers: [] },
    }),
  );
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/auth/me") {
      return route.fulfill({
        json: {
          user: { id: 1, name: "Исследователь", role: "user", blocked: false },
          csrf: "test",
        },
      });
    }
    if (path === "/api/itineraries")
      return route.fulfill({ json: { items: [itinerary], total: 1, page: 1 } });
    if (path === "/api/itineraries/1")
      return route.fulfill({ json: itinerary });
    if (path === "/api/itineraries/1/share")
      return route.fulfill({ json: { token: "test" } });
    if (path === "/api/places/42") return route.fulfill({ json: place });
    if (path === "/api/places")
      return route.fulfill({ json: { items: [place], total: 1, page: 1 } });
    if (path === "/api/places/42/itinerary")
      return route.fulfill({ json: { added: true } });
    if (path === "/api/map")
      return route.fulfill({
        json: { type: "FeatureCollection", features: [], total: 1 },
      });
    return route.fulfill({ json: { items: [], total: 0, page: 1 } });
  });
});

for (const close of ["button", "escape"] as const) {
  for (const source of ["route", "map", "link"] as const) {
    test(`place closes from ${source} using ${close}`, async ({ page }) => {
      await page.goto(
        source === "route" ? "/routes" : source === "link" ? "/?place=42" : "/",
      );
      if (source === "route") {
        await page
          .getByRole("button", { name: place.name, exact: true })
          .click();
      } else if (source === "map") {
        await page.locator(".place-row").first().click();
        await page.getByRole("button", { name: "Во весь экран" }).click();
      }
      const dialog = page.getByRole("dialog", {
        name: place.name,
        exact: true,
      });
      await expect(dialog).toBeVisible();
      if (close === "button") {
        await dialog
          .getByRole("button", { name: "Закрыть", exact: true })
          .click();
      } else {
        await page.keyboard.press("Escape");
      }
      await expect(dialog).toHaveCount(0);
      await expect(page.locator("body")).not.toHaveCSS("overflow", "hidden");
      if (source === "route") {
        await expect(page).toHaveURL(/\/routes$/);
        await expect(page.locator(".detail")).toHaveCount(0);
        await expect(page.locator(".detail-overlay")).toHaveCount(0);
        // The route is usable again, and opening another card still works.
        await page
          .getByRole("button", { name: place.name, exact: true })
          .click();
        await expect(dialog).toBeVisible();
      } else {
        await expect(page.locator(".map-canvas")).toBeVisible();
        await expect(page.locator(".detail h2")).toHaveText(place.name);
        await expect(
          page.getByRole("button", { name: "Во весь экран" }),
        ).toBeVisible();
        await page
          .getByRole("button", { name: "Закрыть карточку", exact: true })
          .click();
        await expect(page.locator(".detail-idle")).toBeVisible();
        await expect(page).not.toHaveURL(/place=/);
      }
    });
  }
}
