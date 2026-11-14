"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
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
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};
const Context = createContext<Session>({
  user: null,
  loading: true,
  authError: null,
  refresh: async () => {},
  logout: async () => {},
});
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
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
    await api("/auth/logout", { method: "POST" });
    setUser(null);
    setCsrf(null);
  }
  useEffect(() => {
    let active = true;
    const telegramWebApp = (
      window as Window & {
        Telegram?: { WebApp?: { initData?: string; ready?: () => void } };
      }
    ).Telegram?.WebApp;
    telegramWebApp?.ready?.();
    async function initialize() {
      if (telegramWebApp?.initData) {
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
            body: body({ init_data: telegramWebApp.initData }),
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
    <Context.Provider value={{ user, loading, authError, refresh, logout }}>
      {children}
    </Context.Provider>
  );
}
export const useSession = () => useContext(Context);
