import { useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import L from "leaflet";
import { AttributionControl, MapContainer, Marker, useMap, useMapEvents } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import type { EventItem, MapCluster } from "../../api/client";
import type { ThemeName } from "../../lib/telegram";
import { Basemap } from "./basemap";
import { MapController } from "./MapController";
import { clusterIcon, metroIcon, pinIcon, serverClusterIcon, userIcon } from "./markers";

type MetroPing = { name: string; lat: number; lon: number; meters: number };
type Bbox = [number, number, number, number]; // [west, south, east, north]

// At/above this zoom the map shows individual pins; below it the server returns
// grid-aggregated clusters. MUST match `_DETAIL_ZOOM` in the API service.
export const DETAIL_ZOOM = 14;

type Props = {
  items: EventItem[];
  clusters: MapCluster[];
  clusterMode: boolean;
  goNowIds: Set<string>;
  friendCounts: Map<string, number>; // event_id → #friends who saved it → corner badge (detail zoom only)
  selected: EventItem | null;
  focused: EventItem | null;
  focusOut: boolean;
  userPos: [number, number] | null;
  heading: number | null;
  locateNonce: number;
  theme: ThemeName;
  metro: MetroPing | null;
  onSelect: (item: EventItem) => void;
  onCluster: (events: EventItem[]) => void;
  onZoom: (zoom: number) => void;
  onClearFocus: () => void;
  onLocate: () => void;
  locating: boolean;
  center?: [number, number] | null;
  onReady?: () => void;
  onViewport?: (bbox: Bbox, zoom: number) => void; // reports the bbox to the parent (list view)
};

// Last-resort initial centre only (before /v1/cities resolves); the real centre comes
// from the active city via the `center` prop.
const MOSCOW: [number, number] = [55.751244, 37.618423];

// Centre the map on the active city: snap instantly the first time (the city resolved
// after mount, so MapContainer's initial centre may be the fallback), then animate when
// the user switches city.
function CityRecenter({ center }: { center: [number, number] | null }) {
  const map = useMap();
  const seen = useRef<string | null>(null);
  useEffect(() => {
    if (!center) return;
    const key = `${center[0].toFixed(5)},${center[1].toFixed(5)}`;
    if (seen.current === key) return;
    if (seen.current === null) {
      seen.current = key;
      map.setView(center, map.getZoom()); // first resolve → snap, no animation
      return;
    }
    seen.current = key;
    map.flyTo(center, Math.max(map.getZoom(), 11), { duration: 0.8 }); // city switch → glide
  }, [center, map]);
  return null;
}

const coordKey = (lat: number, lon: number) => `${lat.toFixed(6)},${lon.toFixed(6)}`;

// Reports the map's bbox+zoom to the parent on every settle (moveend/zoomend)
// and once on mount, so the parent can fetch the right clusters/pins.
function ViewportReporter({ onChange }: { onChange: (bbox: Bbox, zoom: number) => void }) {
  const map = useMap();
  useEffect(() => {
    const emit = () => {
      const b = map.getBounds();
      onChange([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], Math.round(map.getZoom()));
    };
    emit();
    map.on("moveend zoomend", emit);
    return () => {
      map.off("moveend zoomend", emit);
    };
  }, [map, onChange]);
  return null;
}

// A tap on the EMPTY map (not a marker — Leaflet doesn't bubble marker clicks
// here) clears the persistent highlight.
function MapClickClear({ onClear }: { onClear: () => void }) {
  useMapEvents({ click: () => onClear() });
  return null;
}

// Map controls in the native-app pattern (Yandex / 2GIS / Google): the zoom +/-
// pair is one connected unit parked mid-right; the locate button is a separate
// control dropped to the bottom-right corner. The +/- support press-and-hold to
// auto-repeat the zoom, so you can run through several levels in one gesture.
function MapControls({ onLocate, locating }: { onLocate: () => void; locating: boolean }) {
  const map = useMap();
  const zoomRef = useRef<HTMLDivElement>(null);
  const locRef = useRef<HTMLButtonElement>(null);
  const holdRef = useRef<number | null>(null);
  const [zoom, setZoom] = useState(map.getZoom());

  const stopHold = () => {
    if (holdRef.current != null) {
      clearTimeout(holdRef.current);
      holdRef.current = null;
    }
    // Drop BOTH gesture listeners, not just the one that fired. A normal press ends
    // with pointerup (which {once} self-removes), leaving the paired pointercancel
    // dangling forever — one leaked listener per zoom tap. Removing both here (also
    // called from the effect cleanup) keeps it from accumulating across presses.
    window.removeEventListener("pointerup", stopHold);
    window.removeEventListener("pointercancel", stopHold);
  };

  useEffect(() => {
    for (const el of [zoomRef.current, locRef.current]) {
      if (!el) continue;
      L.DomEvent.disableClickPropagation(el);
      L.DomEvent.disableScrollPropagation(el);
    }
    const on = () => setZoom(map.getZoom());
    map.on("zoomend", on);
    return () => {
      map.off("zoomend", on);
      stopHold();
    };
  }, [map]);

  // One zoom step; returns false at the min/max so a running hold stops itself.
  const step = (dir: 1 | -1) => {
    const next = Math.round(map.getZoom()) + dir;
    if (next < map.getMinZoom() || next > map.getMaxZoom()) return false;
    map.setZoom(next);
    return true;
  };

  // Zoom once immediately, then auto-repeat while the button stays pressed.
  const startHold = (dir: 1 | -1) => (e: ReactPointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    stopHold();
    if (!step(dir)) return;
    const tick = () => {
      if (step(dir)) holdRef.current = window.setTimeout(tick, 230);
      else stopHold();
    };
    holdRef.current = window.setTimeout(tick, 340);
    window.addEventListener("pointerup", stopHold, { once: true });
    window.addEventListener("pointercancel", stopHold, { once: true });
  };

  const onKey = (dir: 1 | -1) => (e: ReactKeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      step(dir);
    }
  };

  return (
    <>
      <div className="mapctl" ref={zoomRef}>
        <button type="button" className="mapctl__btn--zoom" aria-label="Приблизить" disabled={zoom >= map.getMaxZoom()} onPointerDown={startHold(1)} onKeyDown={onKey(1)}>
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <line x1="12" y1="4.5" x2="12" y2="19.5" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
            <line x1="4.5" y1="12" x2="19.5" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
          </svg>
        </button>
        <button type="button" className="mapctl__btn--zoom" aria-label="Отдалить" disabled={zoom <= map.getMinZoom()} onPointerDown={startHold(-1)} onKeyDown={onKey(-1)}>
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
            <line x1="4.5" y1="12" x2="19.5" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="square" />
          </svg>
        </button>
      </div>
      <button ref={locRef} type="button" className={`mapctl-locate${locating ? " mapctl-locate--busy" : ""}`} aria-label="Моё местоположение" onClick={onLocate}>
        <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">
          <circle cx="12" cy="12" r="3.6" fill="currentColor" />
          <circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" strokeWidth="1.6" />
          <line x1="12" y1="2" x2="12" y2="5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="12" y1="19" x2="12" y2="22" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="2" y1="12" x2="5" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <line x1="19" y1="12" x2="22" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
    </>
  );
}

// Server-aggregated clusters (low zoom): one tap drills in toward detail zoom,
// where the map switches to individual pins. Markers are memoised by the cluster
// array so unrelated re-renders (pan, user-location ticks) never rebuild them —
// rebuilding recreates each divIcon and makes the squares visibly flicker.
function ServerClusters({ clusters }: { clusters: MapCluster[] }) {
  const map = useMap();
  const markers = useMemo(
    () =>
      clusters.map((c) => (
        <Marker
          key={c.id}
          position={[c.lat, c.lon]}
          icon={serverClusterIcon(c.count)}
          eventHandlers={{
            click: () =>
              map.flyTo([c.lat, c.lon], Math.min(map.getMaxZoom(), Math.max(DETAIL_ZOOM, map.getZoom() + 3)), {
                duration: 0.6,
              }),
          }}
        />
      )),
    [clusters, map],
  );
  return <>{markers}</>;
}

// Keep pins whose point falls in the viewport, padded by 30% so markers near the
// edge appear before they scroll fully into view.
// Pins are pre-rendered for a margin BEYOND the viewport (not just what's on screen) so they're already
// there when you pan, instead of popping in after the gesture settles. 0.6 = a 60%-of-viewport buffer on
// each side (the set updates on moveend; this covers a typical drag before the edge runs dry).
const _BBOX_PAD = 0.6;
function inBbox(lat: number, lon: number, b: Bbox): boolean {
  const [w, s, e, n] = b;
  const px = (e - w) * _BBOX_PAD;
  const py = (n - s) * _BBOX_PAD;
  return lon >= w - px && lon <= e + px && lat >= s - py && lat <= n + py;
}

export function EventsMap({
  items,
  clusters,
  clusterMode,
  goNowIds,
  friendCounts,
  selected,
  focused,
  focusOut,
  userPos,
  heading,
  locateNonce,
  theme,
  metro,
  center,
  onSelect,
  onCluster,
  onZoom,
  onClearFocus,
  onLocate,
  locating,
  onReady,
  onViewport,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const revealedRef = useRef(false);
  const metroIco = useMemo(() => metroIcon(), []);
  // Catchable-now ids, read at pin-build time (kept in a ref so the minute-ticking
  // Set doesn't rebuild every marker each minute — that recreates each divIcon and
  // replays its entrance animation, the old "blinking pins" bug). The highlight
  // refreshes exactly when pins rebuild (pan/zoom/data), same cadence as before.
  const goNowRef = useRef(goNowIds);
  goNowRef.current = goNowIds;
  const [view, setView] = useState<{ bbox: Bbox; zoom: number } | null>(null);

  // At/above detail zoom we draw real pins; below it (when clustering is allowed)
  // the server clusters carry the load. The radius filter ("Рядом") disables
  // server clustering — its set is small, so we just pin it directly.
  const detail = view != null && view.zoom >= DETAIL_ZOOM;
  const useServerClusters = clusterMode && !detail;

  const onZoomRef = useRef(onZoom);
  onZoomRef.current = onZoom;
  const onViewportRef = useRef(onViewport);
  onViewportRef.current = onViewport;
  const handleViewport = useMemo(
    () => (bbox: Bbox, zoom: number) => {
      onZoomRef.current(zoom);
      onViewportRef.current?.(bbox, zoom);
      // Skip the re-render when only the bbox changed at cluster zoom: clusters
      // are whole-city, so panning needs no redraw. At detail zoom the bbox drives
      // which pins render, so update there (and on any zoom change).
      setView((prev) => (prev && prev.zoom === zoom && zoom < DETAIL_ZOOM ? prev : { bbox, zoom }));
    },
    [],
  );

  // First-load reveal: once the first markers are in the DOM, stagger their
  // entrance by distance from the map centre — pins ripple outward from the
  // middle. Runs exactly once so zoom/pan never replays it.
  useEffect(() => {
    if (revealedRef.current) return;
    const el = wrapRef.current;
    if (!el) return;
    const t = setTimeout(() => {
      const icons = el.querySelectorAll<HTMLElement>(".leaflet-marker-icon");
      if (icons.length === 0) return;
      revealedRef.current = true;
      // After the first reveal, stop the per-pin grow-in (vpinIn) from replaying every time
      // MarkerClusterGroup rebuilds the markers on pan/zoom — that replay was the «blink».
      el.classList.add("map-wrap--revealed");
      const box = el.getBoundingClientRect();
      const cx = box.width / 2;
      const cy = box.height / 2;
      const maxR = Math.hypot(cx, cy) || 1;
      icons.forEach((ic) => {
        const r = ic.getBoundingClientRect();
        const dx = r.left - box.left + r.width / 2 - cx;
        const dy = r.top - box.top + r.height / 2 - cy;
        ic.style.animationDelay = `${Math.min(Math.hypot(dx, dy) / maxR, 1) * 460}ms`;
        ic.classList.add("reveal");
      });
    }, 180);
    return () => clearTimeout(t);
  }, [clusters.length, items.length]);

  // Pins to draw: only when NOT showing server clusters, and only those within
  // the current viewport — so we never instantiate thousands of Leaflet markers.
  const pinsRef = useRef<EventItem[]>([]);
  const pins = useMemo(() => {
    if (useServerClusters) {
      if (pinsRef.current.length) pinsRef.current = [];
      return pinsRef.current;
    }
    const inView = items.filter((i) => i.lat != null && i.lon != null);
    const next = view ? inView.filter((i) => inBbox(i.lat as number, i.lon as number, view.bbox)) : inView;
    // Reuse the SAME array when the visible event SET is unchanged (a pan within the bbox pad). The cluster
    // memo + coordIndex + handlers all derive from `pins`, so a stable reference means MarkerClusterGroup
    // is NOT torn down and re-added on every pan — Leaflet just repositions the existing markers. That
    // clear+re-add of every divIcon was the flicker. (Order is stable: `items` is stable, filter preserves
    // it.) Event objects rarely change for a given id, and the divIcon depends only on category + goNow +
    // friend count (the latter two are passed separately), so reusing prior objects is visually identical.
    const prev = pinsRef.current;
    if (prev.length === next.length && next.every((p, i) => prev[i].event_id === p.event_id)) {
      return prev;
    }
    pinsRef.current = next;
    return next;
  }, [useServerClusters, items, view]);

  // Index events by exact coordinate so a cluster click can resolve its child
  // markers back to events (many events can share a single venue point).
  const coordIndex = useMemo(() => {
    const m = new Map<string, EventItem[]>();
    for (const it of pins) {
      if (it.lat == null || it.lon == null) continue;
      const k = coordKey(it.lat, it.lon);
      const arr = m.get(k);
      if (arr) arr.push(it);
      else m.set(k, [it]);
    }
    return m;
  }, [pins]);

  // Tapping a cluster that's spread out zooms to fit it (the familiar gesture).
  // But when every event sits on one point (a single venue stacked, or we're
  // already at max zoom), zooming does nothing useful — so peek a mini-list.
  const clusterHandlers = useMemo(
    () => ({
      clusterclick: (e: any) => {
        const cl = e.layer ?? e.sourceTarget ?? e.propagatedFrom;
        if (!cl?.getAllChildMarkers) return;
        const map = e.target?._map ?? cl._group?._map ?? cl._map;
        const bounds = cl.getBounds();
        // "One place": all pins sit within a venue-sized knot (~one building), where
        // zooming in won't meaningfully separate them — so peek the list on the FIRST
        // tap instead of making the user zoom to the max before it opens. The peek
        // lists each event with its venue, so a few adjacent venues are fine too.
        const tight = bounds.getNorthEast().distanceTo(bounds.getSouthWest()) < 150;
        const maxed = map && map.getZoom() >= map.getMaxZoom();
        if (tight || maxed) {
          const keys = new Set<string>(
            cl.getAllChildMarkers().map((m2: any) => {
              const ll = m2.getLatLng();
              return coordKey(ll.lat, ll.lng);
            }),
          );
          const evs: EventItem[] = [];
          keys.forEach((k) => {
            const arr = coordIndex.get(k);
            if (arr) evs.push(...arr);
          });
          if (evs.length) onCluster(evs);
        } else if (map) {
          map.flyToBounds(bounds, { padding: [60, 60], maxZoom: 17 });
        }
      },
    }),
    [coordIndex, onCluster],
  );

  // Memoise the clustered markers so frequent re-renders (live heading/userPos
  // updates, locate taps) don't rebuild every pin. Rebuilding recreates each
  // divIcon and replays its entrance animation — which is what made markers
  // "blink" on a static screen. Build the pins WITHOUT the selected/active
  // state, so tapping a pin does NOT rebuild all markers; the active highlight
  // is a separate overlay marker (below).
  const cluster = useMemo(() => {
    return (
      <MarkerClusterGroup
        showCoverageOnHover={false}
        spiderfyOnMaxZoom={false}
        zoomToBoundsOnClick={false}
        maxClusterRadius={48}
        iconCreateFunction={clusterIcon}
        animate={false}
        eventHandlers={clusterHandlers}
      >
        {pins.map((item) => (
          <Marker
            key={item.event_id}
            position={[item.lat as number, item.lon as number]}
            icon={pinIcon(item, false, goNowRef.current.has(item.event_id), friendCounts.get(item.event_id) ?? 0)}
            eventHandlers={{ click: () => onSelect(item) }}
          />
        ))}
      </MarkerClusterGroup>
    );
    // friendCounts in deps: the friend badge appears once the (async) friends-favorited fetch lands,
    // not just on the next pan. goNow stays on the ref (refreshes on rebuild) — it's the minute tick.
  }, [pins, friendCounts, onSelect, clusterHandlers]);

  // The FOCUSED event's highlighted (acid) pin, drawn once on top of everything.
  // It tracks `focused` — which persists after the sheet is closed and at any zoom
  // (even over clusters) — so the marker you tapped stays marked until you pick
  // another. Drawn as one overlay marker, so it never rebuilds the whole set.
  const focusedIco = useMemo(
    () =>
      focused && focused.lat != null && focused.lon != null
        ? pinIcon(focused, true, goNowRef.current.has(focused.event_id))
        : null,
    [focused],
  );

  // Rebuild the user icon only when the (throttled) heading changes, so the
  // user marker doesn't get a fresh divIcon — and replay its pulse — on every
  // unrelated re-render.
  const userIco = useMemo(() => userIcon(heading), [heading]);

  return (
    <div ref={wrapRef} className={`map-wrap${selected ? " map-wrap--has-selected" : ""}${focusOut ? " map-wrap--focus-out" : ""}`}>
      <MapContainer center={center ?? MOSCOW} zoom={11} minZoom={3} maxZoom={19} zoomControl={false} attributionControl={false} style={{ height: "100%", width: "100%" }}>
        <AttributionControl position="bottomright" prefix={false} />
        <Basemap theme={theme} onReady={onReady} />
        <ViewportReporter onChange={handleViewport} />
        <MapClickClear onClear={onClearFocus} />
        <MapControls onLocate={onLocate} locating={locating} />
        {useServerClusters ? <ServerClusters clusters={clusters} /> : cluster}
        {focused && focused.lat != null && focused.lon != null && focusedIco && (
          <Marker
            position={[focused.lat, focused.lon]}
            icon={focusedIco}
            zIndexOffset={800}
            eventHandlers={{ click: () => onSelect(focused) }}
          />
        )}
        {selected && metro && (
          <Marker position={[metro.lat, metro.lon]} icon={metroIco} zIndexOffset={900} interactive={false} />
        )}
        {userPos && <Marker position={userPos} icon={userIco} pane="shadowPane" interactive={false} />}
        <MapController selected={selected} locateNonce={locateNonce} userPos={userPos} />
        <CityRecenter center={center ?? null} />
      </MapContainer>
    </div>
  );
}
