import { expect, test } from "@playwright/test";

for (const mode of [
  "sent",
  "cancelled",
  "failed",
  "legacy",
  "bridge",
  "clipboard-denied",
  "browser",
] as const) {
  test(`route sharing: ${mode}`, async ({ page }) => {
    let prepared = 0;
    await page.route("https://telegram.org/js/telegram-web-app.js", (route) =>
      route.fulfill({ body: "" }),
    );
    await page.addInitScript((mode) => {
      let copied = "";
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
          writeText: async (text: string) => {
            if (mode === "clipboard-denied")
              throw new DOMException("Denied", "NotAllowedError");
            copied = text;
          },
          readText: async () => copied,
        },
      });
      if (mode === "clipboard-denied") document.execCommand = () => false;
      Object.defineProperty(navigator, "share", {
        value: () => {
          throw new Error("Desktop must not use navigator.share");
        },
      });
      if (mode === "browser") return;
      const record = (kind: string, value: string) => {
        document.documentElement.dataset[kind] = value;
      };
      if (mode === "bridge") {
        sessionStorage.setItem(
          "__telegram__initParams",
          JSON.stringify({
            tgWebAppData: "test-init-data",
            tgWebAppPlatform: "tdesktop",
          }),
        );
        Object.defineProperty(window, "TelegramWebviewProxy", {
          value: {
            postEvent: (event: string, data: string) => {
              record("event", event);
              record("payload", data);
            },
          },
        });
        return;
      }
      Object.defineProperty(window, "Telegram", {
        value: {
          WebApp: {
            initData: "test-init-data",
            platform: "tdesktop",
            version: mode === "legacy" ? "7.0" : "8.0",
            isVersionAtLeast: () => mode !== "legacy",
            shareMessage: (id: string, callback: (sent: boolean) => void) => {
              record("prepared", id);
              callback(mode !== "cancelled");
            },
            openTelegramLink: (url: string) => record("link", url),
          },
        },
      });
    }, mode);
    await page.route("**/api/**", async (request) => {
      const path = new URL(request.request().url()).pathname;
      const route = {
        id: 42,
        name: "Маршрут & поездка",
        active: true,
        stops: [],
        items: [],
        version: 1,
        notes: "",
        trip_date: null,
      };
      if (path === "/api/auth/me" || path === "/api/auth/telegram/mini-app") {
        return request.fulfill({
          json: {
            user: {
              id: 1,
              name: "Исследователь",
              role: "user",
              blocked: false,
            },
            csrf: "test",
          },
        });
      }
      if (path === "/api/itineraries")
        return request.fulfill({ json: { items: [route], total: 1, page: 1 } });
      if (path.endsWith("/share-message")) {
        prepared++;
        return request.fulfill(
          mode === "failed"
            ? {
                status: 502,
                json: { detail: "Не удалось подготовить сообщение Telegram" },
              }
            : { json: { id: "prepared-42" } },
        );
      }
      if (path.endsWith("/share"))
        return request.fulfill({ json: { token: "public-token" } });
      if (path === "/api/itineraries/42")
        return request.fulfill({ json: route });
      return request.fulfill({ json: {} });
    });
    await page.goto("/routes");
    await page.getByRole("button", { name: "Поделиться маршрутом" }).click();
    await expect(page).toHaveURL(/\/routes$/);
    if (mode === "sent" || mode === "clipboard-denied") {
      await expect(page.locator("html")).toHaveAttribute(
        "data-prepared",
        "prepared-42",
      );
      await expect(page.getByRole("status")).toHaveText("Маршрут отправлен");
    } else if (mode === "legacy") {
      const link = new URL(
        (await page.locator("html").getAttribute("data-link"))!,
      );
      expect(link.pathname).toBe("/share/url");
      expect(link.searchParams.get("text")).toBe("Маршрут & поездка");
      expect(link.searchParams.get("url")).toContain(
        "/routes/share?token=public-token",
      );
    } else if (mode === "bridge") {
      await expect(page.locator("html")).toHaveAttribute(
        "data-event",
        "web_app_open_tg_link",
      );
      const payload = JSON.parse(
        (await page.locator("html").getAttribute("data-payload"))!,
      );
      expect(payload.path_full).toMatch(/^\/share\/url\?url=/);
    } else if (mode === "failed") {
      await expect(
        page
          .getByRole("alert")
          .filter({ hasText: "Не удалось подготовить сообщение" }),
      ).toBeVisible();
    }
    if (mode === "cancelled" || mode === "failed") {
      await expect(page.getByLabel("Ссылка на маршрут")).toHaveValue(
        /token=public-token/,
      );
      await expect(page.locator("html")).not.toHaveAttribute("data-link");
      await expect(
        page.getByText("Маршрут отправлен", { exact: true }),
      ).toHaveCount(0);
    }
    if (mode !== "browser")
      await page
        .getByRole("button", { name: "Скопировать ссылку", exact: true })
        .click();
    if (mode === "clipboard-denied") {
      await expect(page.getByLabel("Ссылка на маршрут")).toHaveValue(
        /token=public-token/,
      );
      await expect(
        page.getByText("Ссылка скопирована", { exact: true }),
      ).toHaveCount(0);
    } else {
      await expect(page.getByRole("status")).toHaveText("Ссылка скопирована");
      expect(
        await page.evaluate(() => navigator.clipboard.readText()),
      ).toContain("/routes/share?token=public-token");
    }
    expect(prepared).toBe(
      ["sent", "cancelled", "failed", "clipboard-denied"].includes(mode)
        ? 1
        : 0,
    );
  });
}
