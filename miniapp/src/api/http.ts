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

const DEFAULT_TIMEOUT = 8000;

// fetch + a MANUAL timeout bridge: aborts after `timeoutMs` and rethrows a clean TimeoutError, and
// forwards an external signal (query-change cancellation). We don't use AbortSignal.timeout()/any() —
// older Telegram in-app webviews don't have them. A `priority` hint is passed through (ignored on iOS).
export async function fetchT(
  path: string,
  init: (RequestInit & { timeoutMs?: number; priority?: "high" | "low" | "auto" }) = {},
  external?: AbortSignal,
): Promise<Response> {
  const { timeoutMs = DEFAULT_TIMEOUT, priority, ...rest } = init;
  const ctrl = new AbortController();
  let timedOut = false;
  const onExt = () => ctrl.abort();
  if (external) {
    if (external.aborted) ctrl.abort();
    else external.addEventListener("abort", onExt, { once: true });
  }
  const timer = setTimeout(() => {
    timedOut = true;
    ctrl.abort();
  }, timeoutMs);
  const opts: RequestInit = { ...rest, signal: ctrl.signal };
  if (priority) (opts as Record<string, unknown>).priority = priority;
  try {
    return await fetch(`${API_BASE}${path}`, opts);
  } catch (e) {
    if (timedOut) throw new DOMException("timeout", "TimeoutError"); // normalise old-webview AbortError → TimeoutError
    throw e;
  } finally {
    clearTimeout(timer);
    if (external) external.removeEventListener("abort", onExt);
  }
}

type GetOpts = { signal?: AbortSignal; timeoutMs?: number; priority?: "high" | "low" | "auto"; retry?: boolean };

// GET JSON with a timeout. GETs are idempotent, so a TIMED-OUT request is retried once (NOT a request the
// caller aborted — e.g. a query change — and never a 4xx/5xx). Pass `priority:'low'` for the bulk map fetch.
export async function getJson<T>(path: string, opts: AbortSignal | GetOpts = {}): Promise<T> {
  const o: GetOpts = opts instanceof AbortSignal ? { signal: opts } : opts;
  const { signal, timeoutMs, priority, retry = true } = o;
  const once = async (): Promise<T> => {
    const res = await fetchT(path, { timeoutMs, priority }, signal);
    if (!res.ok) throw new ApiError(res.status, path);
    return (await res.json()) as T;
  };
  try {
    return await once();
  } catch (e) {
    if (retry && e instanceof DOMException && e.name === "TimeoutError" && !signal?.aborted) return once();
    throw e;
  }
}

export function toNum(v: unknown): number | null {
  return v != null ? Number(v) : null;
}
