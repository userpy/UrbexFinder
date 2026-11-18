import { expect, test } from "@playwright/test";

test("shared place loads without showing the map first", async ({ page }) => {
  let resolvePlaceRequest!: () => void;
  const placeRequestPending = new Promise<void>((resolve) => {
    resolvePlaceRequest = resolve;
  });

  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/places/42") {
      await placeRequestPending;
      return route.fulfill({
        json: {
          id: 42,
          name: "Место по ссылке",
          latitude: 55.3,
          longitude: 37.7,
          region: "Москва",
          description: "",
          category_id: 1,
          condition: "unknown",
          access: "unknown",
          status: "published",
        },
      });
    }
    return route.fulfill({ json: { items: [], total: 0 } });
  });

  await page.goto("/?place=42");
  await expect(page.getByRole("status")).toHaveText("Загружаем место…");
  await expect(page.locator(".maplibregl-canvas")).toHaveCount(0);

  resolvePlaceRequest();
  await expect(
    page.getByRole("dialog", { name: "Место по ссылке" }),
  ).toBeVisible();
});
