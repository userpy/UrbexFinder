type TelegramWindow = Window & {
  Telegram?: { WebApp?: { initData?: string; ready?: () => void } };
};

// The SDK can be unavailable while Telegram's signed launch data is present.
// These values only identify the UI context; the API verifies the signature.
export function telegramLaunch(window: TelegramWindow) {
  const webApp = window.Telegram?.WebApp;
  const params = new URLSearchParams(window.location.hash.slice(1));
  let stored: Record<string, unknown> = {};
  try {
    stored = JSON.parse(window.sessionStorage.getItem("__telegram__initParams") || "{}") || {};
  } catch { /* Storage may be disabled in the embedded browser. */ }
  const savedData = typeof stored.tgWebAppData === "string" ? stored.tgWebAppData : "";
  const initData = params.get("tgWebAppData") || webApp?.initData || savedData;
  if (params.get("tgWebAppData")) {
    try {
      window.sessionStorage.setItem("__telegram__initParams", JSON.stringify({
        ...stored, ...Object.fromEntries(params),
      }));
    } catch { /* Authentication can still use the launch URL. */ }
  }
  return { initData, isMiniApp: Boolean(initData), ready: () => webApp?.ready?.() };
}
