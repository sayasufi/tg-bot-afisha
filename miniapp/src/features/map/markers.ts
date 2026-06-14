import L from "leaflet";

import type { EventItem } from "../../api/client";
import { categorySvg } from "../../lib/icons";

// User location — a surveyor's crosshair (the map-maker's instrument), with a
// single black needle for the compass heading when available.
export function userIcon(heading: number | null): L.DivIcon {
  const needle = heading == null ? "" : `<span class="vyou__needle" style="--h:${heading}deg"></span>`;
  return L.divIcon({
    className: "vyou-wrap",
    html: `<div class="vyou"><span class="vyou__ch"></span><span class="vyou__cv"></span>${needle}<span class="vyou__ring"></span><span class="vyou__core"></span></div>`,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
  });
}

// Pin = a gallery nameplate: a white plate with a 1px frame and the category's
// vinyl-cut icon; a nail + dot drops to the geo point. Active flips to acid.
export function pinIcon(item: EventItem, active: boolean): L.DivIcon {
  return L.divIcon({
    className: "vpin-wrap",
    html: `<div class="vpin${active ? " vpin--active" : ""}"><div class="vpin__plate">${categorySvg(item.category, 18)}</div><div class="vpin__nail"></div><div class="vpin__dot"></div></div>`,
    iconSize: [30, 40],
    iconAnchor: [15, 40],
    popupAnchor: [0, -40],
  });
}

// Cluster = stacked frames with a mono count; inverts to black past 40.
export function clusterIcon(cluster: any): L.DivIcon {
  const count = cluster.getChildCount();
  const size = count < 10 ? 34 : count < 40 ? 40 : 46;
  const big = count >= 40 ? " vcluster--big" : "";
  return L.divIcon({
    className: "vcluster-wrap",
    html: `<div class="vcluster${big}" style="--s:${size}px"><span class="vcluster__face">${count}</span></div>`,
    iconSize: [size, size],
  });
}
