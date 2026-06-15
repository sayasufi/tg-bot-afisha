import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { AttributionControl, MapContainer, Marker, useMap, useMapEvents } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import type { EventItem, MapCluster } from "../../api/client";
import { isLiveNow } from "../../lib/datetime";
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
  onReady?: () => void;
};

const MOSCOW: [number, number] = [55.751244, 37.618423];

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

// Click-to-zoom +/- buttons (like every map app), styled to match the FAB.
function ZoomButtons() {
  const map = useMap();
  const ref = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(map.getZoom());
  useEffect(() => {
    const el = ref.current;
    if (el) {
      L.DomEvent.disableClickPropagation(el);
      L.DomEvent.disableScrollPropagation(el);
    }
    const on = () => setZoom(map.getZoom());
    map.on("zoomend", on);
    return () => {
      map.off("zoomend", on);
    };
  }, [map]);
  return (
    <div className="zoombtns" ref={ref}>
      <button type="button" className="zoombtn" aria-label="Приблизить" disabled={zoom >= map.getMaxZoom()} onClick={() => map.zoomIn()}>
        +
      </button>
      <button type="button" className="zoombtn" aria-label="Отдалить" disabled={zoom <= map.getMinZoom()} onClick={() => map.zoomOut()}>
        −
      </button>
    </div>
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
function inBbox(lat: number, lon: number, b: Bbox): boolean {
  const [w, s, e, n] = b;
  const px = (e - w) * 0.3;
  const py = (n - s) * 0.3;
  return lon >= w - px && lon <= e + px && lat >= s - py && lat <= n + py;
}

export function EventsMap({
  items,
  clusters,
  clusterMode,
  selected,
  focused,
  focusOut,
  userPos,
  heading,
  locateNonce,
  theme,
  metro,
  onSelect,
  onCluster,
  onZoom,
  onClearFocus,
  onReady,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const revealedRef = useRef(false);
  const metroIco = useMemo(() => metroIcon(), []);
  const [view, setView] = useState<{ bbox: Bbox; zoom: number } | null>(null);

  // At/above detail zoom we draw real pins; below it (when clustering is allowed)
  // the server clusters carry the load. The radius filter ("Рядом") disables
  // server clustering — its set is small, so we just pin it directly.
  const detail = view != null && view.zoom >= DETAIL_ZOOM;
  const useServerClusters = clusterMode && !detail;

  const onZoomRef = useRef(onZoom);
  onZoomRef.current = onZoom;
  const handleViewport = useMemo(
    () => (bbox: Bbox, zoom: number) => {
      onZoomRef.current(zoom);
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
  const pins = useMemo(() => {
    if (useServerClusters) return [] as EventItem[];
    const inView = items.filter((i) => i.lat != null && i.lon != null);
    return view ? inView.filter((i) => inBbox(i.lat as number, i.lon as number, view.bbox)) : inView;
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
        const stacked = bounds.getNorthEast().equals(bounds.getSouthWest());
        const maxed = map && map.getZoom() >= map.getMaxZoom();
        if (stacked || maxed) {
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
        chunkedLoading
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
            icon={pinIcon(item, false, isLiveNow(item.date_start, item.date_end, item.venue_hours))}
            eventHandlers={{ click: () => onSelect(item) }}
          />
        ))}
      </MarkerClusterGroup>
    );
  }, [pins, onSelect, clusterHandlers]);

  // The FOCUSED event's highlighted (acid) pin, drawn once on top of everything.
  // It tracks `focused` — which persists after the sheet is closed and at any zoom
  // (even over clusters) — so the marker you tapped stays marked until you pick
  // another. Drawn as one overlay marker, so it never rebuilds the whole set.
  const focusedIco = useMemo(
    () =>
      focused && focused.lat != null && focused.lon != null
        ? pinIcon(focused, true, isLiveNow(focused.date_start, focused.date_end, focused.venue_hours))
        : null,
    [focused],
  );

  // Rebuild the user icon only when the (throttled) heading changes, so the
  // user marker doesn't get a fresh divIcon — and replay its pulse — on every
  // unrelated re-render.
  const userIco = useMemo(() => userIcon(heading), [heading]);

  return (
    <div ref={wrapRef} className={`map-wrap${selected ? " map-wrap--has-selected" : ""}${focusOut ? " map-wrap--focus-out" : ""}`}>
      <MapContainer center={MOSCOW} zoom={11} minZoom={3} maxZoom={19} zoomControl={false} attributionControl={false} style={{ height: "100%", width: "100%" }}>
        <AttributionControl position="bottomright" prefix={false} />
        <Basemap theme={theme} onReady={onReady} />
        <ViewportReporter onChange={handleViewport} />
        <MapClickClear onClear={onClearFocus} />
        <ZoomButtons />
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
      </MapContainer>
    </div>
  );
}
