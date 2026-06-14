import L from "leaflet";
import "leaflet.heat";
import { useEffect } from "react";
import { useMap } from "react-leaflet";

import type { EventItem } from "../../api/client";

// "Где кипит" — event-density heat overlay, acid (few) → cinnabar (many),
// so the busiest parts of the city glow. Rendered only while the toggle is on.
export function HeatLayer({ items }: { items: EventItem[] }) {
  const map = useMap();
  useEffect(() => {
    const points = items
      .filter((i) => i.lat != null && i.lon != null)
      .map((i) => [i.lat as number, i.lon as number, 0.7] as [number, number, number]);
    const layer = (L as any).heatLayer(points, {
      radius: 30,
      blur: 24,
      maxZoom: 16,
      minOpacity: 0.3,
      gradient: { 0.2: "#ccff00", 0.5: "#a8d400", 0.75: "#e6a312", 1: "#e63312" },
    });
    layer.addTo(map);
    return () => {
      map.removeLayer(layer);
    };
  }, [map, items]);
  return null;
}
