import { test } from "node:test";
import { chromium, expect } from "@playwright/test";

test("geolocation reports errors and allows retry, including after a stalled request", async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--enable-unsafe-swiftshader"],
  });
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      let attempt = 0;
      navigator.geolocation.getCurrentPosition = (success, error, options) => {
        attempt++;
        if (attempt === 1) error({ code: 1 });
        else if (
          (attempt === 2 && !options.enableHighAccuracy && options.maximumAge >= 60000) ||
          (attempt === 8 && options.enableHighAccuracy)
        )
          success({
            coords: { latitude: 55.75, longitude: 37.62, accuracy: 120000 },
          });
        else if (attempt === 3 || attempt === 4) error({ code: 2 });
        else if (attempt === 7) error({ code: 3 });
        // Fifth and sixth requests deliberately never resolve.
      };
    });
    await page.goto(process.env.MAP_TEST_URL || "http://localhost:3100");
    const button = page.getByRole("button", {
      name: "Моё местоположение",
      exact: true,
    });
    const status = page.locator(".map-hint");
    await button.click();
    await expect(status).toContainText("Доступ к местоположению запрещён");
    await expect(button).toBeEnabled();
    await button.click();
    await expect(page.locator(".maplibregl-user-location-dot")).toBeVisible();
    await expect(status).toContainText("±120.0 км");
    // Huge browser uncertainty must not cover the map with a blue overlay.
    await expect(
      page.locator(".maplibregl-user-location-accuracy-circle"),
    ).toHaveCount(0);
    const accuracyToggle = page.getByRole("button", { name: "Погрешность геолокации", exact: true });
    await accuracyToggle.click();
    await expect(page.locator(".maplibregl-user-location-accuracy-circle")).toBeVisible();
    await accuracyToggle.click();
    await expect(page.locator(".maplibregl-user-location-accuracy-circle")).toHaveCount(0);
    await button.click();
    await expect(status).toContainText("Служба геолокации браузера недоступна");
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
    await accuracyToggle.click();
    await button.click();
    await expect(status).toContainText("Местоположение определено");
    await expect(page.locator(".maplibregl-user-location-accuracy-circle")).toBeVisible();
  } finally {
    await browser.close();
  }
});
