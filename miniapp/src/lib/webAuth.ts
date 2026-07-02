// Веб-аккаунты (email+пароль) — auth-слой для работы ВНЕ Telegram (сайт, будущие приложения).
// Сессионный токен хранится в localStorage и передаётся серверу В ТОМ ЖЕ поле, что Telegram
// initData, с префиксом "web:" — validate_init_data на бэке понимает оба транспорта, поэтому
// все существующие эндпойнты (избранное/настройки/заявки) работают без изменений.
import { API_BASE } from "../api/http";

const TOKEN_KEY = "okrest_web_token";

export function getWebToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setWebToken(t: string | null): void {
  try {
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* приват-режим — сессия проживёт вкладку */
  }
}

// Единый auth-пейлоад: внутри Telegram — родной initData, в браузере — "web:<token>".
// undefined = не аутентифицирован (браузер без входа): account-глаголы недоступны.
export function getAuthPayload(): string | undefined {
  const tg = (window as { Telegram?: { WebApp?: { initData?: string } } }).Telegram?.WebApp?.initData;
  if (tg) return tg;
  const token = getWebToken();
  return token ? `web:${token}` : undefined;
}

export function isWebMode(): boolean {
  const wa = (window as { Telegram?: { WebApp?: { initData?: string; platform?: string } } }).Telegram?.WebApp;
  return !(wa && (wa.initData?.length || (wa.platform && wa.platform !== "unknown")));
}

type AuthResult = { token?: string; email?: string; telegram_linked?: boolean; detail?: string };

async function post(path: string, body: unknown): Promise<{ ok: boolean; status: number; data: AuthResult }> {
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = (await r.json().catch(() => ({}))) as AuthResult;
    return { ok: r.ok, status: r.status, data };
  } catch {
    return { ok: false, status: 0, data: { detail: "Нет сети — попробуй ещё раз" } };
  }
}

export async function authRegister(email: string, password: string) {
  const r = await post("/v1/auth/register", { email, password });
  if (r.ok && r.data.token) setWebToken(r.data.token);
  return r;
}

export async function authLogin(email: string, password: string) {
  const r = await post("/v1/auth/login", { email, password });
  if (r.ok && r.data.token) setWebToken(r.data.token);
  return r;
}

export async function authMe(): Promise<{ exists: boolean; email: string | null; telegram_linked: boolean } | null> {
  const payload = getAuthPayload();
  if (!payload) return null;
  const r = await post("/v1/auth/me", { init_data: payload });
  if (!r.ok) return null;
  const d = r.data as unknown as { exists: boolean; email: string | null; telegram_linked: boolean };
  return d;
}

export async function authLinkCode(): Promise<string | null> {
  const payload = getAuthPayload();
  if (!payload) return null;
  const r = await post("/v1/auth/link-code", { init_data: payload });
  return r.ok ? ((r.data as unknown as { url?: string }).url ?? null) : null;
}

export async function authSetCredentials(email: string, password: string) {
  const payload = getAuthPayload();
  return post("/v1/auth/set-credentials", { init_data: payload ?? "", email, password });
}

export function logoutWeb(): void {
  setWebToken(null);
}
