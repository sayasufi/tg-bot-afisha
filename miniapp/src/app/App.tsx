import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchEventDetail, fetchMapEvents, fetchMetro, type EventItem, type MetroStation } from "../api/client";
import { EMPTY_FILTERS, Filters, type FilterState } from "../features/filters/Filters";
import { ClusterPeek } from "../features/map/ClusterPeek";
import { EventsMap } from "../features/map/EventsMap";
import { Coach, EmptyState, LoadingBar, MapShimmer, RadarPing } from "../features/map/MapOverlays";
import { FavoritesPanel, ProfilePanel, RecommendationsPanel, Sidebar, type View } from "../features/panel";
import { ProofFrame, Ticker } from "../features/proof/Proof";
import { EventSheet } from "../features/sheet/EventSheet";
import { categoryMeta } from "../lib/categories";
import { isLiveNow } from "../lib/datetime";
import { distanceMeters, nearestOf } from "../lib/distance";
import { useFavorites } from "../lib/favorites";
import { applyTheme, getUser, getWebApp, haptic, hapticNotify, initTelegram, type ThemeName } from "../lib/telegram";
import { useGeolocation } from "../lib/useGeolocation";

const CITY = "Москва";

export function App() {
  const [theme, setTheme] = useState<ThemeName>(() => initTelegram()); // applies saved theme once
  const [tgUser] = useState(() => getUser());
  const fav = useFavorites();
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [items, setItems] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [metro, setMetro] = useState<MetroStation[]>([]);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [peek, setPeek] = useState<EventItem[] | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [view, setView] = useState<View>("map");
  const [sheetReady, setSheetReady] = useState(false);
  const [loading, setLoading] = useState(true);
  const [radarNonce, setRadarNonce] = useState(0);
  const [refreshNonce, setRefreshNonce] = useState(0);
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
    for (const c of filters.categories) params.append("categories", c);
    if (filters.dateFrom) params.set("date_from", new Date(filters.dateFrom).toISOString());
    if (filters.dateTo) params.set("date_to", new Date(filters.dateTo).toISOString());
    if (filters.priceMax) params.set("price_max", filters.priceMax);
    return params;
  }, [filters]);

  // Distance filter ("Рядом") is applied client-side over the fetched set, so
  // the radius slider responds instantly without a round-trip.
  const shownItems = useMemo(() => {
    if (!filters.radiusKm || !userPos) return items;
    const limit = filters.radiusKm * 1000;
    return items.filter((i) => i.lat != null && i.lon != null && distanceMeters(userPos, [i.lat, i.lon]) <= limit);
  }, [items, filters.radiusKm, userPos]);
  const shownTotal = filters.radiusKm && userPos ? shownItems.length : total;

  // Favourite categories drive the "Для тебя" boost in recommendations.
  const favCategories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const it of items) if (fav.ids.has(it.event_id)) counts.set(it.category, (counts.get(it.category) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  }, [items, fav.ids]);

  // Nearest metro to the open event — shown in the sheet and pinged on the map.
  const nearMetro = useMemo(() => {
    if (!selected || selected.lat == null || selected.lon == null || metro.length === 0) return null;
    const hit = nearestOf([selected.lat, selected.lon], metro);
    return hit ? { ...hit.item, meters: hit.meters } : null;
  }, [selected, metro]);

  // Count events happening right now — drives a "live" pulse on the ticker.
  const liveCount = useMemo(() => shownItems.filter((i) => isLiveNow(i.date_start, i.date_end)).length, [shownItems]);

  // Gallery ticker line: total + city + live-now + the busiest categories.
  const tickerText = useMemo(() => {
    const segs = [`${shownTotal} СОБЫТИЙ`, "МОСКВА", "ОКРЕСТ"];
    if (liveCount > 0) segs.push(`ИДЁТ СЕЙЧАС ${liveCount}`);
    const counts: Record<string, number> = {};
    for (const it of shownItems) counts[it.category] = (counts[it.category] || 0) + 1;
    Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .forEach(([k, n]) => segs.push(`${categoryMeta(k).label.toUpperCase()} ${n}`));
    return segs.join(" ● ");
  }, [shownItems, shownTotal, liveCount]);

  // Load metro stations once (for the nearest-station label + map ping).
  useEffect(() => {
    const ctrl = new AbortController();
    fetchMetro(ctrl.signal)
      .then(setMetro)
      .catch(() => undefined);
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    setLoading(true);
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchMapEvents(query, ctrl.signal)
        .then((res) => {
          setItems(res.items);
          setTotal(res.total);
          setLoading(false);
          if (refreshNonce > 0) hapticNotify("success");
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
    // refreshNonce forces a re-fetch on pull-to-refresh even when the query is
    // unchanged; it is intentionally part of the dependency list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, refreshNonce]);

  // Telegram back button closes whatever is on top (sheet → panel → drawer).
  useEffect(() => {
    const back = getWebApp()?.BackButton;
    if (!back) return;
    const stacked = selected || peek || filtersOpen || drawerOpen || view !== "map";
    const pop = () => {
      if (selected) setSelected(null);
      else if (peek) setPeek(null);
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
  }, [selected, peek, filtersOpen, drawerOpen, view]);

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
    setPeek(null);
    setSelected(i);
  }, []);

  // Hold the event sheet back briefly after a selection so the pin→sheet spark,
  // the camera fly and the constellation play out on the open map before the
  // card rises to cover it. Closing is instant.
  useEffect(() => {
    if (!selected) {
      setSheetReady(false);
      return;
    }
    const t = setTimeout(() => setSheetReady(true), 360);
    return () => clearTimeout(t);
  }, [selected]);

  const onCluster = useCallback((evs: EventItem[]) => {
    haptic("light");
    setPeek(evs);
  }, []);

  const onRefresh = useCallback(() => {
    haptic("medium");
    setRefreshNonce((n) => n + 1);
  }, []);

  const toggleTheme = useCallback(() => {
    haptic("light");
    setTheme((t) => {
      const next: ThemeName = t === "dark" ? "light" : "dark";
      applyTheme(next);
      return next;
    });
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
        total={shownTotal}
        open={filtersOpen}
        hasLocation={!!userPos}
        onOpenChange={setFiltersOpen}
        onChange={setFilters}
        onMenu={() => setDrawerOpen(true)}
      />
      {view === "map" && !selected && !filtersOpen && (
        <Ticker
          text={tickerText}
          live={liveCount > 0}
          onClick={() => {
            haptic("light");
            setView("recs");
          }}
        />
      )}

      <EventsMap
        items={shownItems}
        selected={selected}
        userPos={userPos}
        heading={heading}
        locateNonce={locateNonce}
        theme={theme}
        metro={nearMetro}
        onSelect={openEvent}
        onCluster={onCluster}
      />

      <ClusterPeek events={selected ? null : peek} userPos={userPos} onSelect={openEvent} onClose={() => setPeek(null)} />

      <RadarPing key={radarNonce} nonce={radarNonce} />

      <LoadingBar show={loading && view === "map"} />
      <MapShimmer show={loading && items.length === 0 && view === "map" && !selected} />

      {view === "map" && !selected && !filtersOpen && !drawerOpen && !loading && shownItems.length === 0 && (
        <EmptyState
          filters={filters}
          radiusActive={!!filters.radiusKm && !!userPos}
          onReset={() => setFilters(EMPTY_FILTERS)}
          onWiden={() => setFilters({ ...filters, radiusKm: 0, categories: [], priceMax: "" })}
        />
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
        selected={sheetReady ? selected : null}
        query={filters.q}
        userPos={userPos}
        items={shownItems}
        metro={nearMetro}
        isFav={!!selected && fav.has(selected.event_id)}
        onToggleFav={() => selected && fav.toggle(selected.event_id)}
        onSelect={openEvent}
        onClose={() => setSelected(null)}
      />

      {view === "recs" && (
        <RecommendationsPanel items={shownItems} query={filters.q} userPos={userPos} favCategories={favCategories} loading={loading} onRefresh={onRefresh} onSelect={openEvent} onClose={() => setView("map")} />
      )}
      {view === "favorites" && (
        <FavoritesPanel items={items} favIds={fav.ids} query={filters.q} userPos={userPos} loading={loading} onRefresh={onRefresh} onSelect={openEvent} onClose={() => setView("map")} />
      )}
      {view === "profile" && (
        <ProfilePanel user={tgUser} total={total} city={CITY} items={items} favIds={fav.ids} onClose={() => setView("map")} />
      )}

      <Sidebar
        open={drawerOpen}
        view={view}
        favCount={fav.ids.size}
        theme={theme}
        onToggleTheme={toggleTheme}
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
