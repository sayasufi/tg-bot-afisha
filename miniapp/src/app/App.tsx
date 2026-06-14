import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchEventDetail, fetchMapEvents, type EventItem } from "../api/client";
import { Filters, type FilterState } from "../features/filters/Filters";
import { EventsMap } from "../features/map/EventsMap";
import { Coach, EmptyState, LoadingBar, RadarPing } from "../features/map/MapOverlays";
import { ProfilePanel, RecommendationsPanel, Sidebar, type View } from "../features/panel";
import { ProofFrame, Ticker } from "../features/proof/Proof";
import { EventSheet } from "../features/sheet/EventSheet";
import { categoryMeta } from "../lib/categories";
import { useFavorites } from "../lib/favorites";
import { getUser, getWebApp, haptic, initTelegram } from "../lib/telegram";
import { useGeolocation } from "../lib/useGeolocation";

const initialFilters: FilterState = { q: "", category: "", dateFrom: "", dateTo: "", priceMax: "" };
const CITY = "Москва";

export function App() {
  useState(() => initTelegram()); // dark-only theme bootstrap (runs once)
  const [tgUser] = useState(() => getUser());
  const fav = useFavorites();
  const [filters, setFilters] = useState<FilterState>(initialFilters);
  const [items, setItems] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [view, setView] = useState<View>("map");
  const [loading, setLoading] = useState(true);
  const [radarNonce, setRadarNonce] = useState(0);
  const [coachSeen, setCoachSeen] = useState(() => {
    try {
      return localStorage.getItem("okrest_coach") === "1";
    } catch {
      return true;
    }
  });
  const { userPos, heading, locating, locateNonce, onLocate } = useGeolocation();

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

  // Gallery ticker line: total + city + the busiest categories.
  const tickerText = useMemo(() => {
    const segs = [`${total} СОБЫТИЙ`, "МОСКВА", "ОКРЕСТ"];
    const counts: Record<string, number> = {};
    for (const it of items) counts[it.category] = (counts[it.category] || 0) + 1;
    Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .forEach(([k, n]) => segs.push(`${categoryMeta(k).label.toUpperCase()} ${n}`));
    return segs.join(" ● ");
  }, [items, total]);

  useEffect(() => {
    setLoading(true);
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchMapEvents(query, ctrl.signal)
        .then((res) => {
          setItems(res.items);
          setTotal(res.total);
          setLoading(false);
        })
        .catch((e) => {
          if (e?.name !== "AbortError") {
            setItems([]);
            setTotal(0);
            setLoading(false);
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
    const stacked = selected || filtersOpen || drawerOpen || view !== "map";
    const pop = () => {
      if (selected) setSelected(null);
      else if (filtersOpen) setFiltersOpen(false);
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
  }, [selected, filtersOpen, drawerOpen, view]);

  const dismissCoach = useCallback(() => {
    setCoachSeen(true);
    try {
      localStorage.setItem("okrest_coach", "1");
    } catch {
      /* ignore */
    }
  }, []);

  // Auto-dismiss the first-run coach if untouched.
  useEffect(() => {
    if (coachSeen) return;
    const t = setTimeout(dismissCoach, 9000);
    return () => clearTimeout(t);
  }, [coachSeen, dismissCoach]);

  // Locate sequence: the map recenters on locateNonce; once it has settled,
  // give a short buzz and only THEN play the radar rings from the user.
  useEffect(() => {
    if (locateNonce === 0) return;
    const t = setTimeout(() => {
      haptic("medium");
      setRadarNonce((n) => n + 1);
    }, 650);
    return () => clearTimeout(t);
  }, [locateNonce]);

  const openEvent = useCallback((i: EventItem) => {
    haptic("light");
    setView("map");
    setSelected(i);
  }, []);

  // Deep link: open a specific event passed via startapp (?startapp=<id>) or a
  // ?event=<id> query — e.g. when a shared card is tapped.
  useEffect(() => {
    const wa = getWebApp() as any;
    const param: string | undefined =
      wa?.initDataUnsafe?.start_param || new URLSearchParams(window.location.search).get("event") || undefined;
    if (!param) return;
    fetchEventDetail(param)
      .then((d) => {
        const occ = d.occurrences?.[0];
        openEvent({
          event_id: d.event_id,
          title: d.canonical_title,
          category: d.category,
          date_start: occ?.date_start ?? "",
          date_end: occ?.date_end ?? null,
          price_min: occ?.price_min ?? null,
          venue: occ?.venue ?? null,
          lat: occ?.lat ?? null,
          lon: occ?.lon ?? null,
          primary_image_url: d.primary_image_url,
        });
      })
      .catch(() => undefined);
  }, [openEvent]);

  return (
    <div className="app">
      <Filters
        value={filters}
        total={total}
        open={filtersOpen}
        onOpenChange={setFiltersOpen}
        onChange={setFilters}
        onMenu={() => setDrawerOpen(true)}
      />
      {view === "map" && !selected && !filtersOpen && (
        <Ticker
          text={tickerText}
          onClick={() => {
            haptic("light");
            setView("recs");
          }}
        />
      )}

      <EventsMap
        items={items}
        selected={selected}
        userPos={userPos}
        heading={heading}
        locateNonce={locateNonce}
        onSelect={openEvent}
      />

      <RadarPing key={radarNonce} nonce={radarNonce} />

      <LoadingBar show={loading && view === "map"} />

      {view === "map" && !selected && !filtersOpen && !drawerOpen && !loading && items.length === 0 && (
        <EmptyState onReset={() => setFilters(initialFilters)} />
      )}

      {view === "map" && !selected && !filtersOpen && !drawerOpen && !coachSeen && !userPos && (
        <Coach onDismiss={dismissCoach} />
      )}

      <button
        type="button"
        className={`fab${locating ? " fab--busy" : ""}`}
        onClick={() => {
          dismissCoach();
          onLocate();
        }}
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

      <EventSheet
        selected={selected}
        query={filters.q}
        userPos={userPos}
        items={items}
        isFav={!!selected && fav.has(selected.event_id)}
        onToggleFav={() => selected && fav.toggle(selected.event_id)}
        onSelect={openEvent}
        onClose={() => setSelected(null)}
      />

      {view === "recs" && (
        <RecommendationsPanel items={items} query={filters.q} userPos={userPos} loading={loading} onSelect={openEvent} onClose={() => setView("map")} />
      )}
      {view === "profile" && (
        <ProfilePanel user={tgUser} total={total} city={CITY} items={items} favIds={fav.ids} query={filters.q} userPos={userPos} onSelect={openEvent} onClose={() => setView("map")} />
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

      <ProofFrame />
    </div>
  );
}
