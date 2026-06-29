import { createContext, useContext, useEffect, useState, ReactNode } from "react";

import { apiGet, apiPost, getToken, setToken } from "./api";

export type AdminUser = { username: string };

type AuthState = {
  user: AdminUser | null;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthState>(null as any);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AdminUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    (async () => {
      if (!getToken()) {
        setReady(true);
        return;
      }
      try {
        setUser(await apiGet("/me"));
      } catch {
        setToken(null); // протухла → на логин
      }
      setReady(true);
    })();
  }, []);

  const login = async (username: string, password: string) => {
    const r = await apiPost("/session", { username, password });
    setToken(r.token);
    setUser(r.user);
  };

  const logout = async () => {
    try {
      await apiPost("/logout");
    } catch {
      /* всё равно чистим локально */
    }
    setToken(null);
    setUser(null);
  };

  return <Ctx.Provider value={{ user, ready, login, logout }}>{children}</Ctx.Provider>;
}
