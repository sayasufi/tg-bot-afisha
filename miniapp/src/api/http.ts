// Default to same-origin (the API is reverse-proxied under /v1 on the same host),
// which is more robust than a hard-coded URL when the domain changes.
export const API_BASE = ((import.meta.env.VITE_API_BASE as string) || "").replace(/\/$/, "");

// A non-OK HTTP response (4xx/5xx). Distinct from a network/abort failure so callers
// can tell "the server said no" apart from "the request never landed". `.status` is the
// HTTP code; AbortError and TypeError (offline) still propagate as their own native types.
export class ApiError extends Error {
  status: number;
  constructor(status: number, path: string) {
    super(`${status} ${path}`);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { signal });
  if (!res.ok) throw new ApiError(res.status, path);
  return res.json();
}

export function toNum(v: unknown): number | null {
  return v != null ? Number(v) : null;
}
