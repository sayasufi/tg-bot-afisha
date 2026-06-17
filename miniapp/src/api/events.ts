import { getJson, toNum } from "./http";
import type { City, EventDetail, EventItem, MapResponse } from "./types";

// Active cities the app serves — for the city picker / auto-detect and per-city centring.
export async function fetchCities(signal?: AbortSignal): Promise<City[]> {
  const data = await getJson<{ cities: City[] }>(`/v1/cities`, signal);
  return data.cities ?? [];
}

// Typeahead search by code / title / venue → ranked EventItem rows (already shaped to
// open the sheet with no extra fetch). city scopes to the active city.
export async function searchEvents(q: string, city?: string | null, signal?: AbortSignal): Promise<EventItem[]> {
  const p = new URLSearchParams({ q });
  if (city) p.set("city", city);
  const data = await getJson<{ items: EventItem[] }>(`/v1/search?${p.toString()}`, signal);
  return (data.items ?? []).map((x: any) => ({ ...x, price_min: toNum(x.price_min) }));
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
      date_end: x.date_end ?? null,
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

export type MetroStation = { name: string; lat: number; lon: number };

// Metro stations as a flat list (same GeoJSON the basemap draws), for finding
// the nearest station to an event. The dataset mixes in the (defunct) Moscow
// Monorail — drop it so we never label a monorail stop as a metro "м.".
const NON_METRO = /монорельс/i;

export async function fetchMetro(signal?: AbortSignal): Promise<MetroStation[]> {
  const data = await getJson<any>(`/v1/places?kind=metro&city=Moscow`, signal);
  const feats: any[] = data?.features ?? [];
  return feats
    .filter((f) => !NON_METRO.test(f?.properties?.line ?? ""))
    .map((f) => ({
      name: f?.properties?.name ?? "",
      lat: f?.geometry?.coordinates?.[1],
      lon: f?.geometry?.coordinates?.[0],
    }))
    .filter((s) => s.name && typeof s.lat === "number" && typeof s.lon === "number");
}
