type TelegramWindow = Window & {
  Telegram?: { WebApp?: { initData?: string; platform?: string; ready?: () => void } };
  TelegramWebviewProxy?: { postEvent?: unknown };
};

// Launch parameters are only transport: the API must verify their signature.
export function telegramLaunch(window: TelegramWindow) {
  const webApp = window.Telegram?.WebApp;
  const urls = [window.location.href];
  const navigation = window.performance?.getEntriesByType("navigation")[0];
  if (navigation?.name) urls.push(navigation.name);
  let stored: Record<string, unknown> = {};
  try {
    stored = JSON.parse(window.sessionStorage.getItem("__telegram__initParams") || "{}") || {};
  } catch { /* Storage may be disabled in the embedded browser. */ }
  const candidates = urls.flatMap((url) => {
    const parsed = new URL(url);
    return [new URLSearchParams(parsed.hash.slice(1)), parsed.searchParams];
  });
  const launch = candidates.find((params) => params.get("tgWebAppData"));
  const savedData = typeof stored.tgWebAppData === "string" ? stored.tgWebAppData : "";
  const initData = launch?.get("tgWebAppData") || webApp?.initData || savedData;
  if (launch) {
    try {
      window.sessionStorage.setItem("__telegram__initParams", JSON.stringify({
        ...stored, ...Object.fromEntries(launch),
      }));
    } catch { /* Authentication can still use the launch URL. */ }
  }
  const platform = webApp?.platform || candidates.map((params) => params.get("tgWebAppPlatform")).find(Boolean) || stored.tgWebAppPlatform;
  const isMiniApp = Boolean(initData || (platform && platform !== "unknown") || window.TelegramWebviewProxy);
  return { initData, isMiniApp, ready: () => webApp?.ready?.() };
}
