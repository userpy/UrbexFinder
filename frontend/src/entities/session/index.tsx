"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { telegramLaunch } from "./telegram";
export { telegramLaunch } from "./telegram";
import { api, body, setCsrf } from "@/shared/api";

export type User = {
  id: number;
  email: string | null;
  name: string;
  role: "user" | "moderator" | "admin";
  blocked: boolean;
};

type Session = {
  user: User | null;
  loading: boolean;
  authError: string | null;
  isMiniApp: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

type SessionResponse = {
  user: User | null;
  csrf: string | null;
};

const Context = createContext<Session>({
  user: null,
  loading: true,
  authError: null,
  isMiniApp: false,
  refresh: async () => {},
  logout: async () => {},
});

function getErrorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Неизвестная ошибка авторизации";
}

export function SessionProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(
    null
  );
  const [isMiniApp, setIsMiniApp] = useState(false);

  // Обновление текущей сессии
  async function refresh(): Promise<void> {
    try {
      const data = await api<SessionResponse>("/auth/me");

      setUser(data.user);
      setCsrf(data.csrf);
    } finally {
      setLoading(false);
    }
  }

  // Выход из обычной браузерной сессии
  async function logout(): Promise<void> {
    if (telegramLaunch(window).isMiniApp) return;

    await api("/auth/logout", {
      method: "POST",
    });

    setUser(null);
    setCsrf(null);
    setAuthError(null);
  }

  useEffect(() => {
    let active = true;

    async function initialize() {
      let telegram = telegramLaunch(window);

      setIsMiniApp(telegram.isMiniApp);

      try {
        // Telegram Desktop может инициализировать
        // WebView Bridge с задержкой.
        if (telegram.isMiniApp) {
          for (
            let attempt = 0;
            attempt < 30 && active && !telegram.initData;
            attempt++
          ) {
            await new Promise<void>((resolve) => {
              setTimeout(resolve, 100);
            });

            telegram = telegramLaunch(window);
          }
        }

        if (!active) return;

        setIsMiniApp(telegram.isMiniApp);

        // Сообщаем Telegram, что интерфейс готов.
        if (telegram.isMiniApp) {
          telegram.ready();
        }

        // Диагностика без раскрытия initData
        console.info("[Telegram]", {
          isMiniApp: telegram.isMiniApp,
          platform: telegram.platform,
          version: telegram.version,
          hasInitData: Boolean(telegram.initData),
        });

        let loginError: string | null = null;
        let telegramAuthorized = false;

        // Авторизация через Telegram
        if (telegram.initData) {
          // Необязательная попытка получить CSRF.
          // HTTP 401 не должен блокировать вход.
          try {
            const currentSession =
              await api<SessionResponse>("/auth/me");

            if (!active) return;

            setCsrf(currentSession.csrf);
          } catch {
            // Сессии пока может не быть.
          }

          if (!active) return;

          try {
            const session = await api<{
              csrf: string;
            }>("/auth/telegram/mini-app", {
              method: "POST",
              body: body({
                init_data: telegram.initData,
              }),
            });

            if (!active) return;

            setCsrf(session.csrf);
            telegramAuthorized = true;

            console.info(
              "[Telegram] Authentication successful"
            );
          } catch (error) {
            loginError = getErrorMessage(error);

            console.error(
              "[Telegram] Authentication failed:",
              loginError
            );
          }
        } else if (telegram.isMiniApp) {
          loginError =
            "Telegram не передал данные авторизации. " +
            "Закройте Mini App и откройте его заново " +
            "через бота.";
        }

        if (!active) return;

        // Получаем пользователя после авторизации
        try {
          const currentSession =
            await api<SessionResponse>("/auth/me");

          if (!active) return;

          setUser(currentSession.user);
          setCsrf(currentSession.csrf);

          // Проверяем, что Telegram login
          // действительно создал сессию.
          if (
            telegramAuthorized &&
            !currentSession.user
          ) {
            loginError =
              "Telegram подтвердил вход, но сервер " +
              "не сохранил пользовательскую сессию.";
          }

          // Ранее созданная сессия может
          // оставаться действительной.
          if (
            currentSession.user &&
            !telegram.initData
          ) {
            loginError = null;
          }
        } catch (error) {
          if (!active) return;

          setUser(null);
          setCsrf(null);

          if (telegramAuthorized) {
            loginError =
              "Вход через Telegram выполнен, " +
              "но получить сессию не удалось: " +
              getErrorMessage(error);
          }

          console.warn(
            "[Session] Failed to load user:",
            error
          );
        }

        if (active) {
          setAuthError(loginError);
        }
      } catch (error) {
        if (active) {
          setAuthError(getErrorMessage(error));
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void initialize();

    return () => {
      active = false;
    };
  }, []);

  return (
    <Context.Provider
      value={{
        user,
        loading,
        authError,
        isMiniApp,
        refresh,
        logout,
      }}
    >
      {children}
    </Context.Provider>
  );
}

export const useSession = () => useContext(Context);
