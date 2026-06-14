export type EventItem = {
  event_id: string;
  title: string;
  category: string;
  date_start: string;
  date_end: string | null;
  price_min: number | null;
  venue: string | null;
  lat: number | null;
  lon: number | null;
  primary_image_url?: string | null;
};

export type MapResponse = {
  clusters: Array<{ id: string; lat: number; lon: number; count: number }>;
  items: EventItem[];
  total: number;
};

export type EventOccurrence = {
  occurrence_id: number;
  date_start: string;
  date_end: string | null;
  price_min: number | null;
  price_max: number | null;
  currency: string;
  source_best_url: string;
  venue: string | null;
  address: string | null;
  lat: number | null;
  lon: number | null;
};

export type EventDetail = {
  event_id: string;
  canonical_title: string;
  canonical_description: string;
  category: string;
  subcategory: string;
  age_limit: string;
  primary_image_url: string;
  occurrences: EventOccurrence[];
};

// Default to same-origin (the API is reverse-proxied under /v1 on the same host),
// which is more robust than a hard-coded URL when the domain changes.
const API_BASE = ((import.meta.env.VITE_API_BASE as string) || "").replace(/\/$/, "");

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { signal });
  if (!res.ok) throw new Error(`${res.status} ${path}`);
  return res.json();
}

function toNum(v: unknown): number | null {
  return v != null ? Number(v) : null;
}

// The API returns one row per occurrence, so an event with several dates repeats.
// For map pins we want one marker per event.
function dedupeByEvent(items: EventItem[]): EventItem[] {
  const seen = new Set<string>();
  const out: EventItem[] = [];
  for (const item of items) {
    if (seen.has(item.event_id)) continue;
    seen.add(item.event_id);
    out.push(item);
  }
  return out;
}

export async function fetchMapEvents(params: URLSearchParams, signal?: AbortSignal): Promise<MapResponse> {
  const data = await getJson<MapResponse>(`/v1/events/map?${params.toString()}`, signal);
  const items = dedupeByEvent((data.items ?? []).map((x: any) => ({ ...x, price_min: toNum(x.price_min) })));
  return {
    clusters: data.clusters ?? [],
    items,
    total: data.total ?? items.length,
  };
}

export async function fetchNearby(
  lat: number,
  lon: number,
  radiusM: number,
  signal?: AbortSignal,
): Promise<MapResponse> {
  const search = new URLSearchParams({ lat: String(lat), lon: String(lon), radius_m: String(radiusM) });
  const data = await getJson<{ items: any[] }>(`/v1/events/nearby?${search.toString()}`, signal);
  const items = dedupeByEvent(
    (data.items ?? []).map((x) => ({
      event_id: x.event_id,
      title: x.title,
      category: x.category ?? "",
      date_start: x.date_start,
      price_min: toNum(x.price_min),
      venue: x.venue ?? null,
      lat: toNum(x.lat),
      lon: toNum(x.lon),
    })),
  );
  return { clusters: [], items, total: items.length };
}

export async function fetchEventDetail(eventId: string, signal?: AbortSignal): Promise<EventDetail> {
  return getJson<EventDetail>(`/v1/events/${eventId}`, signal);
}

// Persist the user's home city from their first map geolocation (replaces the
// old in-bot city picker). Best-effort: never blocks the UI, ignores failures,
// and does nothing outside Telegram (no signed initData to authenticate with).
export async function saveUserLocation(lat: number, lon: number): Promise<void> {
  const initData = (window as any)?.Telegram?.WebApp?.initData as string | undefined;
  if (!initData) return;
  try {
    await fetch(`${API_BASE}/v1/users/location`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData, lat, lon }),
      keepalive: true,
    });
  } catch {
    /* saving the city is non-critical */
  }
}
