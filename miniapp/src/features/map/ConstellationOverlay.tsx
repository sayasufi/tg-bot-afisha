import type L from "leaflet";
import { useEffect, useReducer } from "react";

import type { EventItem } from "../../api/client";
import { distanceMeters } from "../../lib/distance";

// Hairline "constellation" — when an event is open, faint lines link it to its
// nearest neighbours (variant.com network diagrams). Bounded to ~5 links so it
// never clutters; redrawn on pan/zoom via container-pixel projection. Rendered
// as a sibling SVG over the map (Leaflet won't host arbitrary child DOM).
const MAX_LINKS = 6;
const MAX_DIST_M = 6000;

export function ConstellationOverlay({ map, items, selected }: { map: L.Map | null; items: EventItem[]; selected: EventItem | null }) {
  const [, redraw] = useReducer((x) => x + 1, 0);

  useEffect(() => {
    if (!map) return;
    const onMove = () => redraw();
    map.on("move zoom viewreset resize zoomanim", onMove);
    return () => {
      map.off("move zoom viewreset resize zoomanim", onMove);
    };
  }, [map]);

  if (!map || !selected || selected.lat == null || selected.lon == null) return null;

  const origin: [number, number] = [selected.lat, selected.lon];
  const neighbours = items
    .filter((i) => i.event_id !== selected.event_id && i.lat != null && i.lon != null)
    .map((i) => ({ i, d: distanceMeters(origin, [i.lat as number, i.lon as number]) }))
    .filter((n) => n.d > 0 && n.d <= MAX_DIST_M)
    .sort((a, b) => a.d - b.d)
    .slice(0, MAX_LINKS);

  const p0 = map.latLngToContainerPoint(origin);
  const { x: w, y: h } = map.getSize();

  return (
    <svg key={selected.event_id} className="constellation" data-n={neighbours.length} data-items={items.length} width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      {neighbours.map(({ i }) => {
        const p = map.latLngToContainerPoint([i.lat as number, i.lon as number]);
        return <line key={i.event_id} className="constellation__line" x1={p0.x} y1={p0.y} x2={p.x} y2={p.y} />;
      })}
      {neighbours.map(({ i }) => {
        const p = map.latLngToContainerPoint([i.lat as number, i.lon as number]);
        return <circle key={`n-${i.event_id}`} className="constellation__node" cx={p.x} cy={p.y} r={2.4} />;
      })}
    </svg>
  );
}
