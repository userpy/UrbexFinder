"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { telegramLaunch } from "./telegram";
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
const Context = createContext<Session>({
  user: null,
  loading: true,
  authError: null,
  isMiniApp: false,
  refresh: async () => {},
  logout: async () => {},
});
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [isMiniApp, setIsMiniApp] = useState(false);
  async function refresh() {
    try {
      const data = await api<{ user: User | null; csrf: string | null }>(
        "/auth/me",
      );
      setUser(data.user);
      setCsrf(data.csrf);
    } finally {
      setLoading(false);
    }
  }
  async function logout() {
    if (telegramLaunch(window).isMiniApp) return;
    await api("/auth/logout", { method: "POST" });
    setUser(null);
    setCsrf(null);
  }
  useEffect(() => {
    let active = true;
    async function initialize() {
      let telegram = telegramLaunch(window);
      setIsMiniApp(telegram.isMiniApp);
      // A desktop WebView may initialize its bridge after React has mounted.
      for (let attempt = 0; telegram.isMiniApp && !telegram.initData && attempt < 30 && active; attempt++) {
        await new Promise((resolve) => setTimeout(resolve, 100));
        telegram = telegramLaunch(window);
      }
      if (!active) return;
      telegram.ready();
      setIsMiniApp(telegram.isMiniApp);
      if (telegram.isMiniApp && !telegram.initData) {
        setAuthError("Telegram не передал данные для входа. Закройте мини-приложение и откройте его заново кнопкой в профиле бота.");
      }
      if (telegram.initData) {
        try {
          const currentSession = await api<{
            user: User | null;
            csrf: string | null;
          }>("/auth/me");
          if (active) {
            setUser(currentSession.user);
            setCsrf(currentSession.csrf);
          }
          const session = await api<{ csrf: string }>("/auth/telegram/mini-app", {
            method: "POST",
            body: body({ init_data: telegram.initData }),
          });
          if (active) {
            setCsrf(session.csrf);
            setAuthError(null);
          }
        } catch (error) {
          if (active) setAuthError((error as Error).message);
        }
      }
      try {
        await refresh();
      } catch {
        if (active) setLoading(false);
      }
    }
    void initialize();
    return () => {
      active = false;
    };
  }, []);
  return (
    <Context.Provider value={{ user, loading, authError, isMiniApp, refresh, logout }}>
      {children}
    </Context.Provider>
  );
}
export const useSession = () => useContext(Context);
