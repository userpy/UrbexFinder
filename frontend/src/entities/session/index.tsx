"use client";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
} from "react";
import { api, setCsrf } from "@/shared/api";
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
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};
const Context = createContext<Session>({
  user: null,
  loading: true,
  refresh: async () => {},
  logout: async () => {},
});
export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true);
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
    refresh().catch(() => setLoading(false));
  }, []);
  return (
    <Context.Provider value={{ user, loading, refresh, logout }}>
      {children}
    </Context.Provider>
  );
}
export const useSession = () => useContext(Context);
