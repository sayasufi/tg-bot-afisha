import { useEffect, useMemo, useRef, useState } from "react";

import { fetchMapEvents, fetchNearby, type EventItem } from "../api/client";
import { Filters, type FilterState } from "../features/filters/Filters";
import { EventsMap } from "../features/map/EventsMap";
import { EventSheet } from "../features/sheet/EventSheet";
import { getWebApp, haptic, initTelegram } from "../lib/telegram";

const initialFilters: FilterState = { q: "", category: "", dateFrom: "", dateTo: "", priceMax: "" };

export function App() {
  useState(() => initTelegram()); // dark-only theme bootstrap (runs once)
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [items, setItems] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [loadingNearby, setLoadingNearby] = useState(false);
  const [fitNonce, setFitNonce] = useState(0);
  const [userPos, setUserPos] = useState<[number, number] | null>(null);
  const watchId = useRef<number | null>(null);
  const wantNearby = useRef(false);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", "300");
    if (filters.q) params.set("q", filters.q);
    if (filters.category) params.append("categories", filters.category);
    if (filters.dateFrom) params.set("date_from", new Date(filters.dateFrom).toISOString());
    if (filters.dateTo) params.set("date_to", new Date(filters.dateTo).toISOString());
    if (filters.priceMax) params.set("price_max", filters.priceMax);
    return params;
  }, [filters]);

  useEffect(() => {
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchMapEvents(query, ctrl.signal)
        .then((res) => {
          setItems(res.items);
          setTotal(res.total);
        })
        .catch((e) => {
          if (e?.name !== "AbortError") {
            setItems([]);
            setTotal(0);
          }
        });
    }, 280);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query]);

  // Telegram back button closes the sheet.
  useEffect(() => {
    const back = getWebApp()?.BackButton;
    if (!back) return;
    const close = () => setSelected(null);
    if (selected) {
      back.show();
      back.onClick(close);
    } else {
      back.hide();
    }
    return () => back.offClick(close);
  }, [selected]);

  const doNearby = (lat: number, lon: number) => {
    setLoadingNearby(true);
    fetchNearby(lat, lon, 5000)
      .then((res) => {
        setItems(res.items);
        setTotal(res.total);
        setFitNonce((n) => n + 1);
      })
      .catch(() => undefined)
      .finally(() => setLoadingNearby(false));
  };

  // Start a single continuous geolocation watch — Telegram/browsers prompt once,
  // then the live position updates without re-asking on every tap.
  const startWatch = () => {
    if (watchId.current != null || !navigator.geolocation) return;
    watchId.current = navigator.geolocation.watchPosition(
      (p) => setUserPos([p.coords.latitude, p.coords.longitude]),
      () => setLoadingNearby(false),
      { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 },
    );
  };

  useEffect(() => {
    return () => {
      if (watchId.current != null) navigator.geolocation.clearWatch(watchId.current);
    };
  }, []);

  // When the watch yields a fix after a "locate" tap, load nearby once.
  useEffect(() => {
    if (userPos && wantNearby.current) {
      wantNearby.current = false;
      doNearby(userPos[0], userPos[1]);
    }
  }, [userPos]);

  const onLocate = () => {
    haptic("medium");
    if (userPos) {
      doNearby(userPos[0], userPos[1]);
    } else {
      wantNearby.current = true;
      startWatch();
    }
  };

  return (
    <div className="app">
      <Filters value={filters} total={total} onChange={setFilters} />
      <EventsMap
        items={items}
        selected={selected}
        userPos={userPos}
        fitNonce={fitNonce}
        onSelect={(i) => {
          haptic("light");
          setSelected(i);
        }}
      />
      <button type="button" className={`fab${loadingNearby ? " fab--busy" : ""}`} onClick={onLocate} aria-label="События рядом">
        <span className="fab__glyph">{loadingNearby ? "…" : "📍"}</span>
      </button>
      <EventSheet selected={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
