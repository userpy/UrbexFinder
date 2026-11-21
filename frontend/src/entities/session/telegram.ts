
type TelegramWindow = Window & {
  Telegram?: {
    WebApp?: {
      initData?: string;
      platform?: string;
      version?: string;
      ready?: () => void;
    };
  };
  TelegramWebviewProxy?: {
    postEvent?: unknown;
  };
};

const STORAGE_KEY = "__telegram__initParams";

type LaunchParams = {
  tgWebAppData?: string;
  tgWebAppPlatform?: string;
  tgWebAppVersion?: string;
};

// Извлечение параметров запуска из URL
function extractParams(url: string): URLSearchParams[] {
  try {
    const parsed = new URL(url);
    const hash = parsed.hash.slice(1);

    const result: URLSearchParams[] = [];

    if (hash) {
      result.push(new URLSearchParams(hash));

      // Поддержка hash-routing:
      // #/route?tgWebAppData=...
      const questionIndex = hash.indexOf("?");

      if (questionIndex !== -1) {
        result.push(
          new URLSearchParams(
            hash.slice(questionIndex + 1)
          )
        );
      }
    }

    result.push(parsed.searchParams);

    return result;
  } catch {
    return [];
  }
}

// Чтение сохранённых параметров
function readStoredParams(
  win: TelegramWindow
): LaunchParams {
  try {
    const raw = win.sessionStorage.getItem(STORAGE_KEY);

    if (!raw) return {};

    const parsed: unknown = JSON.parse(raw);

    if (!parsed || typeof parsed !== "object") {
      return {};
    }

    const data = parsed as Record<string, unknown>;

    return {
      tgWebAppData:
        typeof data.tgWebAppData === "string"
          ? data.tgWebAppData
          : undefined,

      tgWebAppPlatform:
        typeof data.tgWebAppPlatform === "string"
          ? data.tgWebAppPlatform
          : undefined,

      tgWebAppVersion:
        typeof data.tgWebAppVersion === "string"
          ? data.tgWebAppVersion
          : undefined,
    };
  } catch {
    return {};
  }
}

// Сохранение параметров
function saveParams(
  win: TelegramWindow,
  params: LaunchParams
): void {
  try {
    win.sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(params)
    );
  } catch {
    // Storage может быть недоступен в WebView.
  }
}

export function telegramLaunch(win: TelegramWindow) {
  const webApp = win.Telegram?.WebApp;

  const urls = [win.location.href];

  // URL первоначальной загрузки
  try {
    const navigation = win.performance
      ?.getEntriesByType("navigation")[0];

    if (navigation?.name) {
      urls.push(navigation.name);
    }
  } catch {
    // Performance API недоступен
  }

  const candidates = urls.flatMap(extractParams);
  const stored = readStoredParams(win);

  function getParam(key: string): string {
    for (const params of candidates) {
      const value = params.get(key);

      if (value) return value;
    }

    return "";
  }

  const urlInitData = getParam("tgWebAppData");
  const urlPlatform = getParam("tgWebAppPlatform");
  const urlVersion = getParam("tgWebAppVersion");

  const sdkInitData = webApp?.initData || "";

  // Приоритет: SDK -> URL -> sessionStorage
  const initData =
    sdkInitData ||
    urlInitData ||
    stored.tgWebAppData ||
    "";

  const sdkPlatform =
    webApp?.platform &&
    webApp.platform !== "unknown"
      ? webApp.platform
      : "";

  const platform =
    sdkPlatform ||
    urlPlatform ||
    stored.tgWebAppPlatform ||
    "";

  const version =
    webApp?.version ||
    urlVersion ||
    stored.tgWebAppVersion ||
    "";

  // Сохраняем параметры актуального запуска
  if (sdkInitData || urlInitData) {
    saveParams(win, {
      tgWebAppData: sdkInitData || urlInitData,
      tgWebAppPlatform: urlPlatform || platform,
      tgWebAppVersion: urlVersion || version,
    });
  }

  const hasBridge =
    typeof win.TelegramWebviewProxy?.postEvent ===
    "function";

  const hasLaunchParams = Boolean(
    urlInitData ||
    urlPlatform ||
    urlVersion
  );

  const isMiniApp = Boolean(
    initData ||
    hasLaunchParams ||
    sdkPlatform ||
    hasBridge
  );

  return {
    initData,
    platform,
    version,
    isMiniApp,

    ready: () => {
      if (isMiniApp) {
        webApp?.ready?.();
      }
    },
  };
}
