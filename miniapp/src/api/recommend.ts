import { API_BASE, getJson, toNum } from "./http";
import type { EventItem } from "./types";

// A rail item is an EventItem (so it opens the sheet the same way) plus the
// server-computed distance from you.
export type RailItem = EventItem & { distance_m?: number | null };
export type Rail = { key: string; title: string; subtitle?: string | null; items: RailItem[] };
export type RecommendationsResponse = { rails: Rail[]; total: number };

export async function fetchRecommendations(
  params: { lat?: number | null; lon?: number | null; interests?: string[]; recent?: string[] },
  signal?: AbortSignal,
): Promise<RecommendationsResponse> {
  const p = new URLSearchParams();
  if (params.lat != null && params.lon != null) {
    p.set("lat", String(params.lat));
    p.set("lon", String(params.lon));
  }
  for (const c of params.interests ?? []) p.append("interests", c);
  for (const c of params.recent ?? []) p.append("recent", c);
  const data = await getJson<RecommendationsResponse>(`/v1/recommendations?${p.toString()}`, signal);
  const rails = (data.rails ?? []).map((r) => ({
    ...r,
    items: (r.items ?? []).map((x: RailItem) => ({ ...x, price_min: toNum(x.price_min) })),
  }));
  return { rails, total: data.total ?? 0 };
}

// Fire-and-forget engagement ping when an event is opened — feeds the
// "Популярное" rail and the popularity term in the recommendation score. Send
// the signed Telegram initData so the server can authenticate + dedupe the
// signal (an unauthenticated ping is silently ignored server-side).
export function logEventSeen(eventId: string): void {
  try {
    const initData = (window as any)?.Telegram?.WebApp?.initData as string | undefined;
    void fetch(`${API_BASE}/v1/recommendations/seen/${eventId}`, {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData ?? "" }),
    }).catch(() => undefined);
  } catch {
    /* ignore */
  }
}
