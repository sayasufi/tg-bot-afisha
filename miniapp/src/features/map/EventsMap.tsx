import { useMemo } from "react";
import { AttributionControl, MapContainer, Marker } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";

import type { EventItem } from "../../api/client";
import { Basemap } from "./basemap";
import { HeatLayer } from "./HeatLayer";
import { MapController } from "./MapController";
import { clusterIcon, pinIcon, userIcon } from "./markers";

type Props = {
  items: EventItem[];
  selected: EventItem | null;
  userPos: [number, number] | null;
  heading: number | null;
  locateNonce: number;
  heatOn: boolean;
  onSelect: (item: EventItem) => void;
};

const MOSCOW: [number, number] = [55.751244, 37.618423];

export function EventsMap({ items, selected, userPos, heading, locateNonce, heatOn, onSelect }: Props) {
  const selectedId = selected?.event_id ?? null;

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
        spiderfyOnMaxZoom
        maxClusterRadius={48}
        iconCreateFunction={clusterIcon}
        animate={false}
      >
        {pins.map((item) => (
          <Marker
            key={item.event_id}
            position={[item.lat as number, item.lon as number]}
            icon={pinIcon(item, item.event_id === selectedId)}
            eventHandlers={{ click: () => onSelect(item) }}
          />
        ))}
      </MarkerClusterGroup>
    );
  }, [items, selectedId, onSelect]);

  // Rebuild the user icon only when the (throttled) heading changes, so the
  // user marker doesn't get a fresh divIcon — and replay its pulse — on every
  // unrelated re-render.
  const userIco = useMemo(() => userIcon(heading), [heading]);

  return (
    <div className={`map-wrap${heatOn ? " map-wrap--heat" : ""}`}>
      <MapContainer center={MOSCOW} zoom={11} minZoom={3} maxZoom={19} zoomControl={false} attributionControl={false} style={{ height: "100%", width: "100%" }}>
        <AttributionControl position="bottomright" prefix={false} />
        <Basemap />
        {heatOn && <HeatLayer items={items} />}
        {cluster}
        {userPos && <Marker position={userPos} icon={userIco} zIndexOffset={1000} interactive={false} />}
        <MapController selected={selected} locateNonce={locateNonce} userPos={userPos} />
      </MapContainer>
    </div>
  );
}
