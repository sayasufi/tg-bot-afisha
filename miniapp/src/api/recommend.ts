import { API_BASE, getJson, toNum } from "./http";
import type { EventItem } from "./types";

// A rail item is an EventItem (so it opens the sheet the same way) plus the
// server-computed distance from you.
export type RailItem = EventItem & { distance_m?: number | null };
// `count` is the collection's TRUE total (for the «N событий» grid tile); auto rails omit it.
export type Rail = { key: string; title: string; subtitle?: string | null; count?: number; items: RailItem[] };
export type RecommendationsResponse = { rails: Rail[]; collections: Rail[]; total: number };
export type Collection = { key: string; title: string; subtitle?: string | null; count: number; items: RailItem[] };

export async function fetchRecommendations(
  params: { lat?: number | null; lon?: number | null; interests?: string[]; recent?: string[]; city?: string | null },
  signal?: AbortSignal,
): Promise<RecommendationsResponse> {
  const p = new URLSearchParams();
  if (params.lat != null && params.lon != null) {
    p.set("lat", String(params.lat));
    p.set("lon", String(params.lon));
  }
  for (const c of params.interests ?? []) p.append("interests", c);
  for (const c of params.recent ?? []) p.append("recent", c);
  if (params.city) p.set("city", params.city);
  const data = await getJson<RecommendationsResponse>(`/v1/recommendations?${p.toString()}`, signal);
  const hydrate = (rs: Rail[] | undefined) =>
    (rs ?? []).map((r) => ({
      ...r,
      items: (r.items ?? []).map((x: RailItem) => ({ ...x, price_min: toNum(x.price_min) })),
    }));
  return { rails: hydrate(data.rails), collections: hydrate(data.collections), total: data.total ?? 0 };
}

// One «Подборка» in full, paginated — the detail screen behind a grid tile. Same scored pool
// as the feed, so the detail agrees with the shelf preview. `slug` is the bare collection slug
// (e.g. "date"), NOT the rail key ("collection:date").
export async function fetchCollection(
  slug: string,
  params: { lat?: number | null; lon?: number | null; interests?: string[]; recent?: string[]; city?: string | null },
  limit = 24,
  offset = 0,
  signal?: AbortSignal,
): Promise<Collection> {
  const p = new URLSearchParams();
  if (params.lat != null && params.lon != null) {
    p.set("lat", String(params.lat));
    p.set("lon", String(params.lon));
  }
  for (const c of params.interests ?? []) p.append("interests", c);
  for (const c of params.recent ?? []) p.append("recent", c);
  if (params.city) p.set("city", params.city);
  p.set("limit", String(limit));
  p.set("offset", String(offset));
  const data = await getJson<Collection>(`/v1/recommendations/collection/${encodeURIComponent(slug)}?${p.toString()}`, signal);
  return { ...data, items: (data.items ?? []).map((x: RailItem) => ({ ...x, price_min: toNum(x.price_min) })) };
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
