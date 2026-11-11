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
      const timers = new Map();
      navigator.geolocation.clearWatch = (id) => {
        clearTimeout(timers.get(id));
        timers.delete(id);
      };
      navigator.geolocation.watchPosition = (success, error, options) => {
        const id = ++attempt;
        if (!options.enableHighAccuracy || options.maximumAge !== 0)
          throw new Error("Expected a fresh high-accuracy request");
        timers.set(
          id,
          setTimeout(() => {
            if (id === 1) error({ code: 1 });
            else if (id === 3) error({ code: 2 });
            else if (id === 2 || id === 5) {
              success({
                coords: { latitude: 55.97, longitude: 37.41, accuracy: 120000 },
              });
              if (id === 5)
                timers.set(
                  id,
                  setTimeout(
                    () =>
                      success({
                        coords: {
                          latitude: 55.75,
                          longitude: 37.62,
                          accuracy: 25,
                        },
                      }),
                    100,
                  ),
                );
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
    const status = page.locator(".map-hint");
    await button.click();
    await expect(status).toContainText("Доступ к местоположению запрещён");
    await expect(button).toBeEnabled();
    await button.click();
    await expect(status).toContainText("Уточняем местоположение");
    await expect(page.locator(".maplibregl-user-location-dot")).toHaveCount(0);
    await expect(status).toContainText(
      "Не удалось определить точное местоположение",
      { timeout: 25000 },
    );
    await expect(status).toContainText("±120.0 км");
    await expect(page.locator(".maplibregl-user-location-dot")).toHaveCount(0);
    const accuracyToggle = page.getByRole("button", {
      name: "Погрешность геолокации",
      exact: true,
    });
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
    await expect(status).toContainText("±25 м");
    await expect(page.locator(".maplibregl-user-location-dot")).toBeVisible();
    await expect(
      page.locator(".maplibregl-user-location-accuracy-circle"),
    ).toBeVisible();
  } finally {
    await browser.close();
  }
});
