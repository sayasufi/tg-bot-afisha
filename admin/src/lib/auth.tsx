import { createContext, useContext, useEffect, useState, ReactNode } from "react";

import { apiGet, apiPost, getToken, setToken } from "./api";

export type AdminUser = { uid: number; username: string | null; first_name: string };

type AuthState = {
  user: AdminUser | null;
  ready: boolean;
  loginWithWidget: (data: any) => Promise<void>;
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
        setToken(null); // протухла/отозвана → на логин
      }
      setReady(true);
    })();
  }, []);

  const loginWithWidget = async (data: any) => {
    const r = await apiPost("/session", data);
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

  return <Ctx.Provider value={{ user, ready, loginWithWidget, logout }}>{children}</Ctx.Provider>;
}
