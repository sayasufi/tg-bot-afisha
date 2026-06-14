// Default to same-origin (the API is reverse-proxied under /v1 on the same host),
// which is more robust than a hard-coded URL when the domain changes.
export const API_BASE = ((import.meta.env.VITE_API_BASE as string) || "").replace(/\/$/, "");

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { signal });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

export function toNum(v: unknown): number | null {
  return v != null ? Number(v) : null;
}
