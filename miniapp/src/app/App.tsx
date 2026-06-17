import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchEventDetail, fetchMapEvents, fetchMetro, type EventItem, type MapCluster, type MetroStation } from "../api/client";
import { logEventSeen } from "../api/recommend";
import { recordOpen } from "../lib/affinity";
import { EMPTY_FILTERS, Filters, type FilterState } from "../features/filters/Filters";
import { ClusterPeek } from "../features/map/ClusterPeek";

// The map pulls in maplibre-gl (~1 MB) + leaflet; lazy-load it so the app shell
// and the instant splash render without waiting on that bundle to parse.
const EventsMap = lazy(() => import("../features/map/EventsMap").then((m) => ({ default: m.EventsMap })));
import { FocusBar } from "../features/map/FocusBar";
import { Coach, EmptyState, LoadingBar, MapShimmer, RadarPing } from "../features/map/MapOverlays";
import { FavoritesPanel, ListView, ProfilePanel, RecommendationsPanel, Sidebar, type View } from "../features/panel";
import { IconList } from "../lib/icons";
import { Onboarding } from "../features/onboarding/Onboarding";
import { ProofFrame, Ticker } from "../features/proof/Proof";
import { EventSheet } from "../features/sheet/EventSheet";
import { categoryMeta } from "../lib/categories";
import { goNowState } from "../lib/datetime";
import { distanceMeters, nearestOf } from "../lib/distance";
import { syncFavorites, useFavorites } from "../lib/favorites";
import { applyTheme, getUser, getWebApp, haptic, hapticNotify, initTelegram, type ThemeName } from "../lib/telegram";
import { CitySwitcher } from "../features/map/CitySwitcher";
import { SearchOverlay } from "../features/search/SearchOverlay";
import { loadSettings, pushSetting } from "../lib/settings";
import { useCities } from "../lib/useCities";
import { useGeolocation } from "../lib/useGeolocation";

const CITY = "Москва";

// At/below this zoom the map shows server-aggregated clusters instead of pins.
// Keep in sync with DETAIL_ZOOM in EventsMap / _DETAIL_ZOOM in the API service.
const DETAIL_ZOOM = 14;

export function App() {
  const [theme, setTheme] = useState<ThemeName>(() => initTelegram()); // applies saved theme once
  const [tgUser] = useState(() => getUser());
  const fav = useFavorites();
  // Pull this account's favourites from the server once on open (and merge this device's
  // local hearts in on first run) so they sync across devices instead of per-device.
  useEffect(() => {
    void syncFavorites();
  }, []);
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS);
  const [items, setItems] = useState<EventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [clusters, setClusters] = useState<MapCluster[]>([]);
  const [zoom, setZoom] = useState<number | null>(null);
  // Warmed cluster payloads keyed by request params (filters + zoom), so changing
  // zoom swaps clusters synchronously from memory instead of waiting on the network.
  const clusterCache = useRef<Map<string, MapCluster[]>>(new Map());
  const [metro, setMetro] = useState<MetroStation[]>([]);
  const [selected, setSelected] = useState<EventItem | null>(null);
  // The marker that stays highlighted (acid) on the map — persists after the sheet
  // closes and at any zoom, until you focus another event. `focusOut` plays the
  // dismiss animation before it's actually cleared.
  const [focused, setFocused] = useState<EventItem | null>(null);
  const [focusOut, setFocusOut] = useState(false);
  const focusedRef = useRef<EventItem | null>(null);
  focusedRef.current = focused;
  const [peek, setPeek] = useState<EventItem[] | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  // List view ("Списком"): the current map bbox (reported by EventsMap) + the bbox
  // frozen when the list was opened, so the list reflects the area you were looking at.
  const [mapBbox, setMapBbox] = useState<[number, number, number, number] | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [listBbox, setListBbox] = useState<[number, number, number, number] | null>(null);
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
  // First-run guide — shown once over the loaded map (default true on storage failure
  // so it never blocks).
  const [onboarded, setOnboarded] = useState(() => {
    try {
      return localStorage.getItem("okrest_onboarded") === "1";
    } catch {
      return true;
    }
  });
  const { userPos, heading, locating, locateNonce, onLocate } = useGeolocation();
  // Current city (nearest by geolocation, or an explicit pick) drives the map `city`
  // scope param and the map centre — no hardcoded city on the client. The switcher shows
  // only when more than one city is active.
  const { cities, current: currentCity, select: selectCity, seed: seedCity } = useCities(userPos);
  // Pull account-scoped settings (theme, city) on open so they match across devices,
  // overriding this device's local cache when the account has a saved value.
  useEffect(() => {
    void loadSettings().then((prefs) => {
      if (!prefs) return;
      if (prefs.theme === "dark" || prefs.theme === "light") {
        applyTheme(prefs.theme);
        setTheme(prefs.theme);
      }
      if (typeof prefs.city === "string" && prefs.city) seedCity(prefs.city);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A coarse clock that ticks once a minute — drives the "можно пойти сейчас"
  // set (countdowns, which events are still catchable) without re-rendering the
  // map on every frame. One minute is plenty: the window is hours, labels are in
  // minutes.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);

  const query = useMemo(() => {
    const params = new URLSearchParams();
    // No limit: fetch every event matching the filters so the map shows exactly the
    // "Показать N" count (and the client-side radius filter works over the full set).
    // Rendering is optimised by clustering (react-leaflet-cluster + chunkedLoading),
    // which keeps thousands of markers smooth without capping the data.
    if (filters.q) params.set("q", filters.q);
    for (const c of filters.categories) params.append("categories", c);
    // Span the WHOLE Moscow day. The dates are Moscow-anchored (see datePresets), so
    // pin the bounds to Moscow's UTC+3 — NOT the client's tz. `new Date("…T00:00:00")`
    // alone parses in the device timezone, which shifts the window by hours for any
    // non-MSK client and drops/adds a band of events. (All current cities are UTC+3,
    // no DST since 2014; generalise per-city tz when a non-UTC+3 city goes live.)
    if (filters.dateFrom) params.set("date_from", new Date(`${filters.dateFrom}T00:00:00+03:00`).toISOString());
    if (filters.dateTo) params.set("date_to", new Date(`${filters.dateTo}T23:59:59+03:00`).toISOString());
    if (filters.priceMax) params.set("price_max", filters.priceMax);
    // Scope the map to the current city (multi-city). Absent until /v1/cities resolves;
    // the server treats "no city" as all-active, so the first frame is still correct.
    if (currentCity) params.set("city", currentCity.slug);
    return params;
  }, [filters, currentCity?.slug]);

  // Distance filter ("Рядом") is applied client-side over the fetched set, so
  // the radius slider responds instantly without a round-trip.
  const radiusItems = useMemo(() => {
    if (!filters.radiusKm || !userPos) return items;
    const limit = filters.radiusKm * 1000;
    return items.filter((i) => i.lat != null && i.lon != null && distanceMeters(userPos, [i.lat, i.lon]) <= limit);
  }, [items, filters.radiusKm, userPos]);

  // "Можно пойти сейчас": the event_ids you can realistically still go to right
  // now — timed events starting within the next 3 hours (not yet begun), plus
  // ongoing venues open at this moment. Computed ONCE here and reused by the
  // filter, the ticker count and the map highlight, so the three can never
  // disagree at a minute boundary.
  const goNowIds = useMemo(() => {
    const at = new Date(now);
    const ids = new Set<string>();
    for (const i of radiusItems) {
      if (goNowState(i.date_start, i.date_end, i.open_now, at).eligible) ids.add(i.event_id);
    }
    return ids;
  }, [radiusItems, now]);

  const shownItems = useMemo(
    () => (filters.goNow ? radiusItems.filter((i) => goNowIds.has(i.event_id)) : radiusItems),
    [radiusItems, filters.goNow, goNowIds],
  );
  const shownTotal = (filters.radiusKm && userPos) || filters.goNow ? shownItems.length : total;

  // Server clustering is used unless a client-side set is in play (radius or
  // "можно пойти") — those sets are small and filtered client-side, so we pin
  // them directly instead of asking the server to grid them.
  const clusterMode = !((filters.radiusKm > 0 && !!userPos) || filters.goNow);
  // Only the integer zoom drives clustering; the map reports it on zoomend.
  // Reporting the same value is a no-op (React bails), so panning never refetches.
  const onZoom = useCallback((z: number) => {
    setZoom(z);
  }, []);

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

  // How many events you can still get to right now — drives the ticker's pulse.
  // Same Set the filter and the map highlight use, so the counts never diverge.
  const liveCount = goNowIds.size;

  // Gallery ticker line: total + city + can-go-now + the busiest categories.
  const tickerText = useMemo(() => {
    const segs = [`${shownTotal} СОБЫТИЙ`, "МОСКВА", "ОКРЕСТ"];
    if (liveCount > 0) segs.push(`МОЖНО ПОЙТИ ${liveCount}`);
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

  // Pull-to-refresh invalidates the warmed clusters so they refetch fresh.
  useEffect(() => {
    clusterCache.current.clear();
  }, [refreshNonce]);

  // Current zoom's clusters: served INSTANTLY from the in-memory cache when warm
  // (a synchronous swap, no network/debounce), otherwise fetched once and cached.
  // Keyed on zoom + filters only (not the panning bbox) — clusters are whole-city.
  useEffect(() => {
    if (zoom == null || !clusterMode || zoom >= DETAIL_ZOOM) {
      setClusters([]);
      return;
    }
    const p = new URLSearchParams(query);
    p.set("zoom", String(zoom));
    const key = p.toString();
    const warm = clusterCache.current.get(key);
    if (warm) {
      setClusters(warm);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      fetchMapEvents(p, ctrl.signal)
        .then((res) => {
          clusterCache.current.set(key, res.clusters);
          setClusters(res.clusters);
        })
        .catch((e) => {
          if (e?.name !== "AbortError") setClusters([]);
        });
    }, 200);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [zoom, query, clusterMode, refreshNonce]);

  // Prefetch the whole cluster-zoom band for the current filters in the background,
  // so the FIRST visit to any zoom is already warm → zooming feels instant. Tiny
  // payloads (a few dozen points each), deduped against the cache, served from the
  // server's short Redis cache.
  useEffect(() => {
    if (!clusterMode) return;
    const ctrl = new AbortController();
    const t = setTimeout(() => {
      for (let z = 7; z < DETAIL_ZOOM; z++) {
        const p = new URLSearchParams(query);
        p.set("zoom", String(z));
        const key = p.toString();
        if (clusterCache.current.has(key)) continue;
        fetchMapEvents(p, ctrl.signal)
          .then((res) => clusterCache.current.set(key, res.clusters))
          .catch(() => undefined);
      }
    }, 700);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [query, clusterMode, refreshNonce]);

  const dismissOnboarding = useCallback(() => {
    haptic("light");
    try {
      localStorage.setItem("okrest_onboarded", "1");
    } catch {
      /* ignore */
    }
    setOnboarded(true);
  }, []);

  // Close whatever is on top, most-modal first — shared by the Telegram BackButton and
  // the keyboard Escape, so both behave like tapping the visible × . Returns true if it
  // closed something.
  const closeTop = useCallback((): boolean => {
    if (searchOpen) setSearchOpen(false);
    else if (selected) setSelected(null);
    else if (peek) setPeek(null);
    else if (filtersOpen) setFiltersOpen(false);
    else if (drawerOpen) setDrawerOpen(false);
    else if (listOpen) setListOpen(false);
    else if (view !== "map") setView("map");
    else return false;
    // Drop focus from the trigger so it doesn't keep a focus ring after closing
    // (a keyboard Escape otherwise leaves the pill button looking "highlighted").
    (document.activeElement as HTMLElement | null)?.blur?.();
    return true;
  }, [searchOpen, selected, peek, filtersOpen, drawerOpen, listOpen, view]);

  // Telegram back button closes whatever is on top (search → sheet → peek → filters →
  // drawer → panel).
  useEffect(() => {
    const back = getWebApp()?.BackButton;
    if (!back) return;
    const stacked = selected || peek || filtersOpen || drawerOpen || searchOpen || listOpen || view !== "map";
    const pop = () => closeTop();
    if (stacked) {
      back.show();
      back.onClick(pop);
    } else {
      back.hide();
    }
    return () => back.offClick(pop);
  }, [selected, peek, filtersOpen, drawerOpen, searchOpen, listOpen, view, closeTop]);

  // Esc behaves like tapping the visible × — closes the first-run guide, then the
  // top overlay.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (!onboarded) {
        dismissOnboarding();
        (document.activeElement as HTMLElement | null)?.blur?.();
        return;
      }
      closeTop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onboarded, dismissOnboarding, closeTop]);

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
    // Keep the cluster peek behind the sheet ONLY while it still contains this event
    // (so closing returns you to the same point's list + swipe siblings). Opening an
    // event from elsewhere (a "Рядом" card, a different pin) drops the stale peek so it
    // can't reappear out of sync with the map.
    setPeek((p) => (p && p.some((e) => e.event_id === i.event_id) ? p : null));
    setSelected(i);
    setFocused(i); // keep this marker highlighted on the map even after closing
    setFocusOut(false); // cancel any pending dismiss animation
    logEventSeen(i.event_id); // engagement signal for recommendations
    recordOpen(i.category); // behavioural profile for personalised ranking
  }, []);

  // The peek is a map-only overlay: drop it when leaving the map (recs/favorites/
  // profile) so it never lingers behind a panel.
  useEffect(() => {
    if (view !== "map") setPeek(null);
  }, [view]);

  // Hold the event sheet back briefly after a selection so the pin→sheet spark,
  // the camera fly and the constellation play out on the open map before the
  // card rises to cover it. Closing is instant.
  useEffect(() => {
    if (!selected) {
      setSheetReady(false);
      return;
    }
    // Opened from a panel (recs/favorites) → no map choreography to wait for, so
    // the sheet rises immediately over the panel.
    if (view !== "map") {
      setSheetReady(true);
      return;
    }
    const t = setTimeout(() => setSheetReady(true), 560);
    return () => clearTimeout(t);
  }, [selected, view]);

  const onCluster = useCallback((evs: EventItem[]) => {
    haptic("light");
    setPeek(evs);
  }, []);

  // "На карте" from the sheet: drop to the map (the camera already flew to the
  // event when it was opened) and close everything that covers it so the pin is in view.
  const showOnMap = useCallback(() => {
    haptic("light");
    setView("map"); // closes recs/favorites/profile panels
    setListOpen(false); // the list is a separate overlay — close it too (was the bug)
    setSelected(null);
    setPeek(null); // "На карте" wants the pin in view, not the peek list over it
  }, []);

  // Dismiss the highlight WITH an exit animation: flag it out, then clear after the
  // animation. Tapping the empty map does the same (only when something is focused).
  const dismissFocus = useCallback(() => {
    haptic("light");
    setFocusOut(true);
  }, []);
  const clearFocus = useCallback(() => {
    if (focusedRef.current) setFocusOut(true);
  }, []);
  useEffect(() => {
    if (!focusOut) return;
    const t = setTimeout(() => {
      setFocused(null);
      setFocusOut(false);
    }, 230);
    return () => clearTimeout(t);
  }, [focusOut]);

  const handleLocate = useCallback(() => {
    dismissCoach();
    onLocate();
  }, [dismissCoach, onLocate]);
  // The slim "marked exhibit" bar shows on the map when a marker is highlighted
  // and no card is open.
  const focusBarVisible = view === "map" && !!focused && !selected && !peek;

  const onRefresh = useCallback(() => {
    haptic("medium");
    setRefreshNonce((n) => n + 1);
  }, []);

  // Drop the instant splash only once the basemap has actually rendered, so the
  // user never sees a blank/initialising map (and no layout shift behind it).
  const handleMapReady = useCallback(() => {
    const splash = document.getElementById("splash");
    if (!splash || splash.dataset.lifting) return;
    splash.dataset.lifting = "1";
    // Let the first tiles + pins settle behind the splash, then lift — so the
    // user sees a finished map, not the tail of its layout settling.
    window.setTimeout(() => {
      splash.classList.add("hide");
      window.setTimeout(() => splash.remove(), 400);
    }, 300);
  }, []);

  const toggleTheme = useCallback(() => {
    haptic("light");
    setTheme((t) => {
      const next: ThemeName = t === "dark" ? "light" : "dark";
      applyTheme(next);
      pushSetting("theme", next); // sync the choice to the account, not this device
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
          code: d.code,
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
    <div className={`app${focusBarVisible ? " app--focusbar" : ""}`}>
      <Filters
        value={filters}
        total={shownTotal}
        open={filtersOpen}
        hasLocation={!!userPos}
        onOpenChange={setFiltersOpen}
        onChange={setFilters}
        onMenu={() => setDrawerOpen(true)}
        onOpenSearch={() => setSearchOpen(true)}
        favCount={fav.ids.size}
      />
      <SearchOverlay
        open={searchOpen}
        city={currentCity?.slug ?? null}
        userPos={userPos}
        onSelect={openEvent}
        onClose={() => setSearchOpen(false)}
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
      {view === "map" && !selected && !filtersOpen && (
        <CitySwitcher cities={cities} current={currentCity} onSelect={selectCity} />
      )}

      <Suspense fallback={null}>
        <EventsMap
          items={shownItems}
          clusters={clusters}
          clusterMode={clusterMode}
          goNowIds={goNowIds}
          selected={selected}
          focused={focused}
          focusOut={focusOut}
          userPos={userPos}
          heading={heading}
          locateNonce={locateNonce}
          theme={theme}
          center={currentCity ? [currentCity.lat, currentCity.lon] : null}
          metro={nearMetro}
          onSelect={openEvent}
          onCluster={onCluster}
          onZoom={onZoom}
          onClearFocus={clearFocus}
          onLocate={handleLocate}
          locating={locating}
          onReady={handleMapReady}
          onViewport={(bbox) => setMapBbox(bbox)}
        />
      </Suspense>

      <ClusterPeek events={selected ? null : peek} userPos={userPos} now={now} onSelect={openEvent} onClose={() => setPeek(null)} />

      <RadarPing key={radarNonce} nonce={radarNonce} />

      <LoadingBar show={loading && view === "map"} />
      <MapShimmer show={loading && items.length === 0 && view === "map" && !selected} />

      {view === "map" && !selected && !filtersOpen && !drawerOpen && !loading && shownItems.length === 0 && (
        <EmptyState
          filters={filters}
          radiusActive={!!filters.radiusKm && !!userPos}
          onReset={() => setFilters(EMPTY_FILTERS)}
          onWiden={() => setFilters({ ...filters, radiusKm: 0, categories: [], priceMax: "", goNow: false })}
        />
      )}

      {view === "map" && !selected && !filtersOpen && !drawerOpen && !coachSeen && !userPos && (
        <Coach onDismiss={dismissCoach} />
      )}

      {focusBarVisible && focused && <FocusBar event={focused} out={focusOut} now={now} onOpen={openEvent} onClose={dismissFocus} />}

      {/* Map↔list toggle — opens the current map area as a sortable list. */}
      {view === "map" && !selected && !peek && !filtersOpen && !drawerOpen && !searchOpen && !listOpen && !focusBarVisible && !loading && (
        <button
          type="button"
          className="listfab"
          aria-label="Показать списком"
          onClick={() => {
            haptic("light");
            setListBbox(mapBbox);
            setListOpen(true);
          }}
        >
          <IconList size={20} />
        </button>
      )}

      <ListView
        open={listOpen}
        baseParams={query}
        bbox={listBbox}
        userPos={userPos}
        radiusKm={filters.radiusKm}
        onSelect={openEvent}
        onClose={() => setListOpen(false)}
      />

      <EventSheet
        selected={sheetReady ? selected : null}
        query={filters.q}
        userPos={userPos}
        items={shownItems}
        siblings={peek ?? undefined}
        metro={nearMetro}
        isFav={!!selected && fav.has(selected.event_id)}
        onToggleFav={() => selected && fav.toggle(selected.event_id)}
        onSelect={openEvent}
        onShowMap={showOnMap}
        onClose={() => setSelected(null)}
      />

      {view === "recs" && (
        <RecommendationsPanel userPos={userPos} favCategories={favCategories} refreshNonce={refreshNonce} city={currentCity?.slug ?? null} onSelect={openEvent} onClose={() => setView("map")} />
      )}
      {view === "favorites" && (
        <FavoritesPanel items={items} favIds={fav.ids} userPos={userPos} loading={loading} onRefresh={onRefresh} onSelect={openEvent} onClose={() => setView("map")} />
      )}
      {view === "profile" && (
        <ProfilePanel user={tgUser} total={total} city={currentCity?.name ?? CITY} items={items} favIds={fav.ids} onClose={() => setView("map")} />
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

      {!onboarded && <Onboarding onClose={dismissOnboarding} />}
    </div>
  );
}
