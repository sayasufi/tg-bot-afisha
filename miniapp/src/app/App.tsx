import { useEffect, useMemo, useRef, useState } from "react";

import { fetchMapEvents, type EventItem } from "../api/client";
import { Filters, type FilterState } from "../features/filters/Filters";
import { EventsMap } from "../features/map/EventsMap";
import { ProfilePanel, RecommendationsPanel, Sidebar, type View } from "../features/panel/panels";
import { EventSheet } from "../features/sheet/EventSheet";
import { getUser, getWebApp, haptic, initTelegram } from "../lib/telegram";

const initialFilters: FilterState = { q: "", category: "", dateFrom: "", dateTo: "", priceMax: "" };
const CITY = "Москва";

export function App() {
  useState(() => initTelegram()); // dark-only theme bootstrap (runs once)
  const [tgUser] = useState(() => getUser());
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [items, setItems] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [view, setView] = useState<View>("map");
  const [locating, setLocating] = useState(false);
  const [locateNonce, setLocateNonce] = useState(0);
  const [userPos, setUserPos] = useState<[number, number] | null>(null);
  const [heading, setHeading] = useState<number | null>(null);
  const watchId = useRef<number | null>(null);
  const wantCenter = useRef(false);
  const orientHandler = useRef<((e: any) => void) | null>(null);

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

  // Telegram back button closes whatever is on top (sheet → panel → drawer).
  useEffect(() => {
    const back = getWebApp()?.BackButton;
    if (!back) return;
    const stacked = selected || drawerOpen || view !== "map";
    const pop = () => {
      if (selected) setSelected(null);
      else if (drawerOpen) setDrawerOpen(false);
      else setView("map");
    };
    if (stacked) {
      back.show();
      back.onClick(pop);
    } else {
      back.hide();
    }
    return () => back.offClick(pop);
  }, [selected, drawerOpen, view]);

  // Single continuous geolocation watch — prompts once, then the live position
  // streams in without re-asking on every tap.
  const startWatch = () => {
    if (watchId.current != null || !navigator.geolocation) return;
    watchId.current = navigator.geolocation.watchPosition(
      (p) => setUserPos([p.coords.latitude, p.coords.longitude]),
      () => setLocating(false),
      { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 },
    );
  };

  // Compass heading (where the phone points). iOS needs an explicit permission
  // grant triggered from a user gesture, so we kick this off on the locate tap.
  const startOrientation = async () => {
    if (orientHandler.current) return;
    const DOE: any = (window as any).DeviceOrientationEvent;
    if (!DOE) return;
    try {
      if (typeof DOE.requestPermission === "function") {
        const res = await DOE.requestPermission();
        if (res !== "granted") return;
      }
    } catch {
      return;
    }
    const handler = (e: any) => {
      let h: number | null = null;
      if (typeof e.webkitCompassHeading === "number") h = e.webkitCompassHeading; // iOS: clockwise from north
      else if (e.absolute && e.alpha != null) h = (360 - e.alpha) % 360;
      if (h != null && !Number.isNaN(h)) setHeading(Math.round(h));
    };
    orientHandler.current = handler;
    const evt = "ondeviceorientationabsolute" in window ? "deviceorientationabsolute" : "deviceorientation";
    window.addEventListener(evt, handler, true);
  };

  useEffect(() => {
    return () => {
      if (watchId.current != null) navigator.geolocation.clearWatch(watchId.current);
      if (orientHandler.current) {
        window.removeEventListener("deviceorientationabsolute", orientHandler.current, true);
        window.removeEventListener("deviceorientation", orientHandler.current, true);
      }
    };
  }, []);

  // When the first fix lands after a locate tap, recentre on the user.
  useEffect(() => {
    if (userPos && wantCenter.current) {
      wantCenter.current = false;
      setLocating(false);
      setLocateNonce((n) => n + 1);
    }
  }, [userPos]);

  // Centre the map on the user (and start showing the live position + heading).
  // It never replaces the events on the map — all of them stay put.
  const onLocate = () => {
    haptic("medium");
    void startOrientation();
    if (userPos) {
      setLocateNonce((n) => n + 1);
    } else {
      wantCenter.current = true;
      setLocating(true);
      startWatch();
    }
  };

  const openEvent = (i: EventItem) => {
    haptic("light");
    setView("map");
    setSelected(i);
  };

  return (
    <div className="app">
      <Filters value={filters} total={total} onChange={setFilters} onMenu={() => setDrawerOpen(true)} />

      <EventsMap
        items={items}
        selected={selected}
        userPos={userPos}
        heading={heading}
        locateNonce={locateNonce}
        onSelect={openEvent}
      />

      <button
        type="button"
        className={`fab${locating ? " fab--busy" : ""}`}
        onClick={onLocate}
        aria-label="Моё местоположение"
      >
        <svg className="fab__icon" viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" fill="currentColor" />
          <circle cx="12" cy="12" r="7.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <line x1="12" y1="1.5" x2="12" y2="5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="12" y1="19" x2="12" y2="22.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="1.5" y1="12" x2="5" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="19" y1="12" x2="22.5" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>

      <EventSheet selected={selected} onClose={() => setSelected(null)} />

      {view === "recs" && (
        <RecommendationsPanel items={items} onSelect={openEvent} onClose={() => setView("map")} />
      )}
      {view === "profile" && (
        <ProfilePanel user={tgUser} total={total} city={CITY} onClose={() => setView("map")} />
      )}

      <Sidebar
        open={drawerOpen}
        view={view}
        onClose={() => setDrawerOpen(false)}
        onSelect={(v) => {
          haptic("light");
          setView(v);
          setDrawerOpen(false);
        }}
      />
    </div>
  );
}
