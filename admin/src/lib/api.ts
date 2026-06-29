// Same-origin по умолчанию: nginx на admin.okrestmap.ru проксирует /v1 → api. Override через VITE_API_BASE.
const BASE = ((import.meta as any).env?.VITE_API_BASE ?? "").replace(/\/$/, "");
const TOKEN_KEY = "okrest_admin_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string | null) => {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
};

export class ApiError extends Error {
  status: number;
  constructor(status: number, msg: string) {
    super(msg);
    this.status = status;
  }
}

async function req(method: string, path: string, body?: unknown): Promise<any> {
  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(`${BASE}/v1/admin${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? null : res.json();
}

export const apiGet = (path: string) => req("GET", path);
export const apiPost = (path: string, body?: unknown) => req("POST", path, body);
