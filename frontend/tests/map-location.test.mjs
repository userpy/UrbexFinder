import { test } from "node:test";
import { chromium, expect } from "@playwright/test";

test("geolocation accepts coarse positions and allows retry after errors and stalled requests", async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--enable-unsafe-swiftshader"],
  });
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      let attempt = 0;
      const timers = new Map();
      navigator.geolocation.clearWatch = (id) => {
        clearTimeout(timers.get(id));
        timers.delete(id);
      };
      navigator.geolocation.watchPosition = (success, error, options) => {
        if (!options.enableHighAccuracy) {
          const id = 100 + attempt;
          if (options.maximumAge !== 60000) throw new Error("Expected bounded cache age");
          if (attempt === 3 || attempt === 6) timers.set(id, setTimeout(() => success({
            coords: { latitude: 55.97, longitude: 37.41, accuracy: 500 },
          }), 0));
          return id;
        }
        const id = ++attempt;
        if (options.maximumAge !== 0)
          throw new Error("Expected a fresh high-accuracy request");
        timers.set(
          id,
          setTimeout(() => {
            if (id === 1) error({ code: 1 });
            else if (id === 3) error({ code: 2 });
            else if (id === 2 || id === 5) {
              success({
                coords: {
                  latitude: 55.97,
                  longitude: 37.41,
                  accuracy: id === 2 ? 120000 : 25,
                },
              });
            }
            // Fourth request deliberately never resolves.
          }, 0),
        );
        return id;
      };
    });
    await page.goto(process.env.MAP_TEST_URL || "http://localhost:3100");
    const button = page.getByRole("button", {
      name: "Моё местоположение",
      exact: true,
    });
    const status = page.getByTestId("map-location-status");
    await button.click();
    await expect(status).toContainText("Доступ к местоположению запрещён");
    await expect(button).toBeEnabled();
    await button.click();
    await expect(status).toContainText("Местоположение определено");
    await expect(status).toContainText("±120.0 км");
    await expect(button).toBeEnabled();
    await expect(page.locator(".maplibregl-user-location-dot")).toBeVisible();
    const accuracyToggle = page.getByRole("button", {
      name: "Погрешность геолокации",
      exact: true,
    });
    await button.click();
    await expect(status).toContainText("±500 м");
    await button.click();
    await expect(status).toContainText("Определяем местоположение");
    await expect(button).toBeDisabled();
    // Native :disabled uses MapLibre's red denied-location icon.
    await expect(button).toHaveJSProperty("disabled", false);
    await expect(button).toHaveAttribute("aria-busy", "true");
    const background = await button
      .locator(".maplibregl-ctrl-icon")
      .evaluate((element) => getComputedStyle(element).backgroundImage);
    expect(background).not.toContain("%23f00");
    await expect(button).toBeEnabled({ timeout: 35000 });
    await expect(status).toContainText("Браузер не сообщил местоположение");
    await expect(status).toBeVisible();
    await expect(page.locator(".maplibregl-user-location-dot")).toBeVisible();
    await accuracyToggle.click();
    await button.click();
    await expect(status).toContainText("Местоположение определено");
    await expect(status).toContainText("±25 м");
    await expect(page.locator(".maplibregl-user-location-dot")).toBeVisible();
    await expect(
      page.locator(".maplibregl-user-location-accuracy-circle"),
    ).toBeVisible();
    // A silent high-accuracy provider must also trigger the fallback.
    await button.click();
    await expect(status).toContainText("±500 м", { timeout: 12000 });
    await expect(button).toBeEnabled();
  } finally {
    await browser.close();
  }
});
