import { getJson, toNum } from "./http";
import type { EventDetail, EventItem, MapResponse } from "./types";

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
