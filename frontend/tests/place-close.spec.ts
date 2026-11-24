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
