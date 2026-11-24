type TelegramShareApp = {
  isVersionAtLeast?: (version: string) => boolean;
  shareMessage?: (id: string, callback: (sent: boolean) => void) => void;
  openTelegramLink?: (url: string) => void;
};

export function telegramShareApp() {
  return (
    window as Window & {
      Telegram?: { WebApp?: TelegramShareApp };
    }
  ).Telegram?.WebApp;
}

export function sharePreparedMessage(
  app: TelegramShareApp,
  id: string,
): Promise<boolean> {
  return new Promise((resolve, reject) => {
    // A broken bridge must not leave the button disabled indefinitely.
    const timer = setTimeout(() => {
      reject(
        new Error(
          "Telegram не ответил. Попробуйте снова или скопируйте ссылку.",
        ),
      );
    }, 60_000);
    try {
      app.shareMessage!(id, (sent) => {
        clearTimeout(timer);
        resolve(sent);
      });
    } catch (error) {
      clearTimeout(timer);
      reject(error);
    }
  });
}

export function openTelegramShare(url: string, title: string) {
  const link = new URL("https://t.me/share/url");
  link.searchParams.set("url", url);
  link.searchParams.set("text", title);
  const app = telegramShareApp();
  if (app?.openTelegramLink) {
    app.openTelegramLink(link.href);
    return;
  }
  // Desktop can expose its bridge even when the remote SDK failed to load.
  const bridge = (
    window as Window & {
      TelegramWebviewProxy?: {
        postEvent: (event: string, data: string) => void;
      };
    }
  ).TelegramWebviewProxy;
  if (typeof bridge?.postEvent === "function") {
    bridge.postEvent(
      "web_app_open_tg_link",
      JSON.stringify({
        path_full: link.pathname + link.search,
      }),
    );
    return;
  }
  throw new Error(
    "Не удалось открыть меню Telegram. Скопируйте ссылку на маршрут.",
  );
}
