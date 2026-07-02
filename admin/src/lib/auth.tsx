import { createContext, useContext, useEffect, useState, ReactNode } from "react";

import { apiGet, apiPost, getToken, setToken } from "./api";

export type AdminUser = { username: string };

type AuthState = {
  user: AdminUser | null;
  ready: boolean;
  /** unix-мс истечения сессии (из exp токена) или null, если неизвестно */
  expiresAt: number | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthState>(null as any);
export const useAuth = () => useContext(Ctx);

/** exp (unix-мс) из подписанного токена вида base64url(payload).sig. payload = {sub,iat,exp}. */
function tokenExp(token: string | null): number | null {
  if (!token) return null;
  try {
    const seg = token.split(".")[0];
    if (!seg) return null;
    const b64 = seg.replace(/-/g, "+").replace(/_/g, "/");
    const json = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
    const exp = JSON.parse(json).exp;
    return typeof exp === "number" ? exp * 1000 : null;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AdminUser | null>(null);
  const [ready, setReady] = useState(false);
  const [expiresAt, setExpiresAt] = useState<number | null>(() => tokenExp(getToken()));

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
        setExpiresAt(null);
      }
      setReady(true);
    })();
  }, []);

  const login = async (username: string, password: string) => {
    const r = await apiPost("/session", { username, password });
    setToken(r.token);
    setExpiresAt(tokenExp(r.token));
    setUser(r.user);
  };

  const logout = async () => {
    try {
      await apiPost("/logout");
    } catch {
      /* всё равно чистим локально */
    }
    setToken(null);
    setExpiresAt(null);
    setUser(null);
  };

  return <Ctx.Provider value={{ user, ready, expiresAt, login, logout }}>{children}</Ctx.Provider>;
}

/** Баннер-предупреждение о скором истечении сессии. Показываем за ≤5 мин до exp. */
export function useExpiryWarning(): { soon: boolean; minsLeft: number } {
  const { expiresAt } = useAuth();
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(id);
  }, []);
  if (expiresAt == null) return { soon: false, minsLeft: 0 };
  const msLeft = expiresAt - now;
  return { soon: msLeft > 0 && msLeft <= 5 * 60 * 1000, minsLeft: Math.max(0, Math.ceil(msLeft / 60000)) };
}
