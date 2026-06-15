import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";

import type { EventItem } from "../../api/client";

// Imperative camera moves: fly to a selected event, and recentre on the user
// when the locate button bumps `locateNonce` (without touching the event pins).
export function MapController({
  selected,
  locateNonce,
  userPos,
}: {
  selected: EventItem | null;
  locateNonce: number;
  userPos: [number, number] | null;
}) {
  const map = useMap();
  const lastLocate = useRef(0);

  useEffect(() => {
    if (selected && selected.lat != null && selected.lon != null) {
      // Offset the camera so the pin lands in the visible strip ABOVE the sheet
      // (which covers the lower ~82%) — keeps the pin + its constellation in view.
      const z = Math.max(map.getZoom(), 16);
      const p = map.project([selected.lat, selected.lon], z).add([0, map.getSize().y * 0.34]);
      map.flyTo(map.unproject(p, z), z, { duration: 0.7 });
    }
  }, [selected, map]);

  // A "locate" tap bumps locateNonce; recentre on the user without touching pins.
  useEffect(() => {
    if (locateNonce === 0 || locateNonce === lastLocate.current) return;
    lastLocate.current = locateNonce;
    if (userPos) map.flyTo(userPos, Math.max(map.getZoom(), 15), { duration: 0.6 });
  }, [locateNonce, map, userPos]);

  return null;
}
