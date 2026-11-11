import { test, expect, Page } from "@playwright/test";

// Only the map's background is a local fixture: all application APIs, DB and S3 are real.
// This removes a third-party tile network dependency while exercising real WebGL/MapLibre.
test.beforeEach(async ({ page }) => {
  await page.route("**/e2e-map-style.json", (route) =>
    route.fulfill({
      json: {
        version: 8,
        sources: {},
        layers: [
          {
            id: "background",
            type: "background",
            paint: { "background-color": "#172128" },
          },
        ],
      },
    }),
  );
});
async function dragPlaceMarker(page: Page) {
  const marker = page.getByLabel("Переместить точку места");
  await expect(marker).toBeVisible();
  const box = (await marker.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 40, box.y + box.height / 2 + 20, {steps:10});
  await page.mouse.up();
}
async function login(page: Page, role = "moderator") {
  await page.goto("/login");
  await page.getByRole("button", { name: "Логин и пароль", exact: true }).click();
  await page
    .getByLabel("Email", { exact: true })
    .fill(`${role}@e2e.example.com`);
  await page
    .getByLabel("Пароль", { exact: true })
    .fill("e2e-only-password-12345");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
}

test("guest map covers all pages; search, empty state and selection", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.locator(".map-canvas")).toBeVisible();
  await expect(page.locator(".map-label")).toContainText("65 в области");
  await expect(page.locator(".place-row")).toHaveCount(30);
  await expect(
    page
      .locator(".place-row")
      .first()
      .locator('[data-category-icon="industry"]'),
  ).toBeVisible();
  await page.getByRole("button", { name: "Далее →" }).click();
  await expect(page.locator(".pager")).toContainText("2 / 3");
  await expect(page.locator(".map-label")).toContainText("65 в области");
  await page.locator(".place-row").first().click();
  await expect(page.locator(".detail h2")).toContainText("Тестовая башня");
  await expect(
    page.locator(".detail").getByRole("link", { name: "Войдите", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Закрыть карточку" }).click();
  await page.getByLabel("Поиск мест").fill("ничегоненайдено");
  await expect(page.getByText("Здесь пока тихо")).toBeVisible();
  await page.getByLabel("Поиск мест").fill("башня");
  await expect(page.locator(".place-row")).toHaveCount(30);
});

test("registration → submission → moderator approval → map → persistent favorite", async ({
  page,
  browser,
}) => {
  const unique = Date.now();
  const name = `Фабрика E2E ${unique}`;
  await page.goto("/login");
  await page.getByRole("button", { name: "Логин и пароль", exact: true }).click();
  await page.getByRole("link", { name: "Регистрация", exact: true }).click();
  await expect(page).toHaveURL(/\/register$/);
  await page.getByRole("button", { name: "Логин и пароль", exact: true }).click();
  await page.getByLabel("Имя", { exact: true }).fill("Исследователь E2E");
  await page
    .getByLabel("Email", { exact: true })
    .fill(`reader${unique}@example.com`);
  await page
    .getByLabel("Пароль", { exact: true })
    .fill("e2e-reader-password-12345");
  await page.getByRole("button", { name: "Создать аккаунт" }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/submit");
  await page.getByLabel("Название", { exact: true }).fill(name);
  await page
    .getByLabel("Описание", { exact: true })
    .fill(
      "Историческая фабрика для проверки полного пользовательского сценария.",
    );
  await dragPlaceMarker(page);
  await page.getByLabel("Регион", { exact: true }).fill("Москва");
  await page.getByRole("button", { name: "Отправить на проверку" }).click();
  await expect(
    page.getByRole("heading", { name: "Заявка отправлена" }),
  ).toBeVisible();
  const userPlaces = await (await page.request.get("/api/me/places")).json();
  const id = userPlaces.items.find((p: { name: string }) => p.name === name).id;
  const moderatorContext = await browser.newContext({
    baseURL: "http://localhost:3101",
  });
  const moderator = await moderatorContext.newPage();
  await moderator.route("**/e2e-map-style.json", (route) =>
    route.fulfill({ json: { version: 8, sources: {}, layers: [] } }),
  );
  await login(moderator);
  await moderator.goto("/admin");
  await moderator
    .getByRole("button", { name: "Очередь мест", exact: true })
    .click();
  await moderator.getByRole("button").filter({ hasText: name }).click();
  await expect(
    moderator.getByRole("button", { name: "Отклонить", exact: true }),
  ).toBeDisabled();
  await moderator
    .getByRole("button", { name: "Опубликовать", exact: true })
    .click();
  await expect(moderator.locator(".admin-inspector")).toHaveCount(0);
  await page.goto("/");
  await page.getByLabel("Поиск мест").fill(String(unique));
  await page.getByLabel("Поиск мест").press("Escape");
  await expect(page.locator(".map-label")).toContainText("1 в области");
  await page.locator(".place-row").filter({ hasText: name }).click();
  await expect(page.getByRole("button", {name:"Сохранить отзыв"})).toHaveCount(0);
  await expect(page.locator('.detail input[type="file"]')).toHaveCount(0);
  await page.getByRole("button", {name:"Добавить в маршрутный лист", exact:true}).click();
  await expect(page.getByRole("status")).toContainText("Добавлено в маршрут");
  await expect(page).toHaveURL(/\/$/);
  await page.reload();
  await page.goto("/account");
  await expect(page.getByRole("button", { name: "Избранное", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Войти в аккаунт" }),
  ).toBeVisible();
  expect((await page.request.get(`/api/places/${id}/favorite`)).status()).toBe(
    401,
  );
  await moderatorContext.close();
});

test("mobile list, map and bottom detail panel", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.locator(".place-row").first()).toBeVisible();
  await page.getByRole("button", { name: "Карта", exact: true }).click();
  await expect(page.locator(".map-canvas canvas")).toBeVisible();
  await expect(page.locator(".catalog")).not.toBeVisible();
  await page.getByRole("button", { name: "Список", exact: true }).click();
  await page.locator(".place-row").first().click();
  await expect(page.locator(".detail h2")).toBeVisible();
  const bounds = await page.locator(".detail").boundingBox();
  expect(bounds?.width).toBe(390);
  await page.screenshot({ path: "test-results/mobile-detail.png" });
});

test("map provider failure keeps public list usable", async ({ page }) => {
  await page.route("**/e2e-map-style.json", (route) => route.abort());
  await page.goto("/");
  await expect(
    page.getByText("Карта недоступна", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".place-row")).toHaveCount(30);
  await page.locator(".place-row").first().click();
  await expect(page.locator(".detail h2")).toBeVisible();
});

test("guest admin access is blocked in UI and API", async ({ page }) => {
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "Доступ ограничен" }),
  ).toBeVisible();
  expect((await page.request.get("/api/admin/users")).status()).toBe(401);
});

test("moderator cannot manage users; administrator can see audit and categories", async ({
  page,
}) => {
  await login(page);
  await page.goto("/admin");
  await expect(
    page.getByRole("button", { name: "Пользователи", exact: true }),
  ).toHaveCount(0);
  expect((await page.request.get("/api/admin/users")).status()).toBe(403);
  await page.goto("/account");
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await login(page, "admin");
  await page.goto("/admin");
  await page.getByRole("button", { name: "Категории", exact: true }).click();
  await expect(
    page.getByRole("button").filter({ hasText: "Промышленность" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Журнал действий", exact: true })
    .click();
  await expect(page.locator(".admin-table")).toBeVisible();
});

test("description matches outside viewport appear in suggestions and open on map", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".map-label")).toContainText(/6[56] в области/);
  await page.getByLabel("Поиск мест").fill("Кувин");
  const suggestion = page.locator("#search-suggestions button").filter({ hasText: "Войсковая часть за пределами карты" });
  await expect(suggestion.locator("mark")).toHaveText("Кувин");
  await expect(page.locator(".place-row")).toHaveCount(1);
  await suggestion.click();
  await expect(page.locator(".detail h2")).toContainText("Войсковая часть за пределами карты");
  await expect(page.locator(".map-label")).toContainText("1 в области");
});

test("staff opens place dialog and saves description without republishing", async ({ page }) => {
  await login(page, "admin");
  await page.goto("/admin");
  await page.getByRole("button", { name: "Все места", exact: true }).click();
  await page.locator(".table-row").first().click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const description = "Новое описание места для проверки редактирования.";
  await dialog.getByLabel("Описание места").fill(description);
  await dragPlaceMarker(page);
  const savedLatitude = await dialog.getByLabel("Широта", {exact:true}).inputValue();
  await page.route("**/api/admin/geocode/reverse?*", route => route.fulfill({json:{address:"Новый адрес, Александров"}}));
  await dialog.getByRole("button", {name:"Обновить адрес по координатам"}).click();
  await expect(dialog.getByLabel("Адрес", {exact:true})).toHaveValue("Новый адрес, Александров");
  await dialog.getByRole("button", { name: "Сохранить изменения", exact: true }).click();
  await expect(dialog.getByRole("status")).toHaveText("Изменения сохранены");
  await dialog.getByRole("button", { name: "Закрыть ×" }).click();
  await page.locator(".table-row").first().click();
  await expect(page.getByLabel("Описание места")).toHaveValue(description);
  await expect(page.getByLabel("Широта", {exact:true})).toHaveValue(savedLatitude);
  await expect(page.getByLabel("Адрес", {exact:true})).toHaveValue("Новый адрес, Александров");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("personal itinerary adds a place and persists visited status", async ({page}) => {
  await login(page,"admin");
  await page.goto("/");
  await page.locator(".place-row").first().click();
  await page.getByRole("button",{name:"Добавить в маршрутный лист",exact:true}).click();
  await expect(page.getByRole("status")).toContainText("Добавлено в маршрут");
  await expect(page.getByRole("button",{name:"Удалить из маршрутного листа",exact:true})).toBeVisible();
  await page.goto("/routes");
  await page.locator(".route-open").first().click();
  await expect(page.locator(".route-stop")).toHaveCount(1);
  await page.locator(".route-settings-toggle").click();
  await page.getByLabel("Название маршрута", {exact:true}).fill("Поездка E2E");
  await expect(page.getByLabel("Заметка к месту")).toHaveCount(0);
  await page.getByLabel("Статус точки").selectOption("visited");
  await page.getByRole("button",{name:"Сохранить маршрут",exact:true}).click();
  await expect(page.getByRole("status")).toHaveText("Сохранено");
  await page.reload();
  await page.getByRole("button").filter({hasText:"Поездка E2E"}).click();
  await expect(page.getByLabel("Заметка к месту")).toHaveCount(0);
  await expect(page.getByLabel("Статус точки")).toHaveValue("visited");
  await page.locator(".route-stop h3 button").click();
  await expect(page.locator(".detail")).toBeVisible();
});
