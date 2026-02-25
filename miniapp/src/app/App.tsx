import { useEffect, useMemo, useState } from "react";

import { fetchMapEvents, fetchNearby, type EventItem } from "../api/client";
import { Filters } from "../features/filters/Filters";
import { EventsMap } from "../features/map/EventsMap";
import { SearchCard } from "../features/search/SearchCard";

type FilterState = {
  q: string;
  category: string;
  dateFrom: string;
  dateTo: string;
  priceMax: string;
};

const initialFilters: FilterState = {
  q: "",
  category: "",
  dateFrom: "",
  dateTo: "",
  priceMax: "",
};

export function App() {
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [items, setItems] = useState<EventItem[]>([]);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [loadingNearby, setLoadingNearby] = useState(false);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", "200");
    if (filters.q) params.set("q", filters.q);
    if (filters.category) params.append("categories", filters.category);
    if (filters.dateFrom) params.set("date_from", new Date(filters.dateFrom).toISOString());
    if (filters.dateTo) params.set("date_to", new Date(filters.dateTo).toISOString());
    if (filters.priceMax) params.set("price_max", filters.priceMax);
    return params;
  }, [filters]);

  useEffect(() => {
    fetchMapEvents(query)
      .then((res) => setItems(res.items))
      .catch(() => setItems([]));
  }, [query]);

  const loadNearby = () => {
    if (!navigator.geolocation) {
      return;
    }
    setLoadingNearby(true);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        fetchNearby(position.coords.latitude, position.coords.longitude, 5000)
          .then((res) => setItems(res.items))
          .finally(() => setLoadingNearby(false));
      },
      () => setLoadingNearby(false),
      { enableHighAccuracy: true, timeout: 10000 }
    );
  };

  return (
    <div className="app">
      <Filters value={filters} onChange={setFilters} />
      <button
        type="button"
        onClick={loadNearby}
        style={{ position: "absolute", right: 12, top: 12, zIndex: 1200, padding: "8px 12px", borderRadius: 8 }}
      >
        {loadingNearby ? "Loading..." : "Рядом со мной"}
      </button>
      <EventsMap items={items} onSelect={setSelected} />
      <SearchCard selected={selected} />
    </div>
  );
}
