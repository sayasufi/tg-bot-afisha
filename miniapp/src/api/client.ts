export type EventItem = {
  event_id: string;
  title: string;
  category: string;
  date_start: string;
  price_min: number | null;
  venue: string | null;
  lat: number | null;
  lon: number | null;
};

export type MapResponse = {
  clusters: Array<{ id: string; lat: number; lon: number; count: number }>;
  items: EventItem[];
  total: number;
};

const API_BASE = (import.meta.env.VITE_API_BASE as string) || "http://localhost:8000";

export async function fetchMapEvents(params: URLSearchParams): Promise<MapResponse> {
  const res = await fetch(`${API_BASE}/v1/events/map?${params.toString()}`);
  if (!res.ok) {
    throw new Error("Failed to load map events");
  }
  return res.json();
}

export async function fetchNearby(lat: number, lon: number, radiusM: number): Promise<MapResponse> {
  const search = new URLSearchParams({ lat: String(lat), lon: String(lon), radius_m: String(radiusM) });
  const res = await fetch(`${API_BASE}/v1/events/nearby?${search.toString()}`);
  if (!res.ok) {
    throw new Error("Failed to load nearby events");
  }
  const data = await res.json();
  return {
    clusters: [],
    items: data.items.map((x: any) => ({
      event_id: x.event_id,
      title: x.title,
      category: "",
      date_start: x.date_start,
      price_min: null,
      venue: null,
      lat: null,
      lon: null,
    })),
    total: data.items.length,
  };
}
