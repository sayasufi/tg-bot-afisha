import { useMemo } from "react";
import { AttributionControl, MapContainer, Marker } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import type { EventItem } from "../../api/client";
import { isLiveNow } from "../../lib/datetime";
import type { ThemeName } from "../../lib/telegram";
import { Basemap } from "./basemap";
import { MapController } from "./MapController";
import { clusterIcon, pinIcon, userIcon } from "./markers";

type Props = {
  items: EventItem[];
  selected: EventItem | null;
  userPos: [number, number] | null;
  heading: number | null;
  locateNonce: number;
  theme: ThemeName;
  onSelect: (item: EventItem) => void;
  onCluster: (events: EventItem[]) => void;
};

const MOSCOW: [number, number] = [55.751244, 37.618423];

const coordKey = (lat: number, lon: number) => `${lat.toFixed(6)},${lon.toFixed(6)}`;

export function EventsMap({ items, selected, userPos, heading, locateNonce, theme, onSelect, onCluster }: Props) {
  const selectedId = selected?.event_id ?? null;

  // Index events by exact coordinate so a cluster click can resolve its child
  // markers back to events (many events can share a single venue point).
  const coordIndex = useMemo(() => {
    const m = new Map<string, EventItem[]>();
    for (const it of items) {
      if (it.lat == null || it.lon == null) continue;
      const k = coordKey(it.lat, it.lon);
      const arr = m.get(k);
      if (arr) arr.push(it);
      else m.set(k, [it]);
    }
    return m;
  }, [items]);

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
  // "blink" on a static screen. Only item/selection/handler changes regenerate.
  const cluster = useMemo(() => {
    const pins = items.filter((i) => i.lat != null && i.lon != null);
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
            icon={pinIcon(item, item.event_id === selectedId, isLiveNow(item.date_start, item.date_end))}
            eventHandlers={{ click: () => onSelect(item) }}
          />
        ))}
      </MarkerClusterGroup>
    );
  }, [items, selectedId, onSelect, clusterHandlers]);

  // Rebuild the user icon only when the (throttled) heading changes, so the
  // user marker doesn't get a fresh divIcon — and replay its pulse — on every
  // unrelated re-render.
  const userIco = useMemo(() => userIcon(heading), [heading]);

  return (
    <div className={`map-wrap${selected ? " map-wrap--has-selected" : ""}`}>
      <MapContainer center={MOSCOW} zoom={11} minZoom={3} maxZoom={19} zoomControl={false} attributionControl={false} style={{ height: "100%", width: "100%" }}>
        <AttributionControl position="bottomright" prefix={false} />
        <Basemap theme={theme} />
        {cluster}
        {userPos && <Marker position={userPos} icon={userIco} zIndexOffset={1000} interactive={false} />}
        <MapController selected={selected} locateNonce={locateNonce} userPos={userPos} />
      </MapContainer>
    </div>
  );
}
