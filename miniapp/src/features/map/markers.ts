import L from "leaflet";

import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
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

// Pin = a gallery nameplate: a white plate with a 1px frame, the category's
// vinyl-cut icon, and a thin category-colour rail along the bottom edge (a
// gallery label's colour code); a nail + dot drops to the geo point. Active
// flips to acid; a live (happening-now) event gets a cinnabar pulse.
export function pinIcon(item: EventItem, active: boolean, live = false): L.DivIcon {
  const cls = `vpin${active ? " vpin--active" : ""}${live ? " vpin--live" : ""}`;
  const liveDot = live ? '<span class="vpin__live"></span>' : "";
  const { color } = categoryMeta(item.category);
  return L.divIcon({
    className: "vpin-wrap",
    html: `<div class="${cls}"><div class="vpin__plate" style="--cat:${color}">${categorySvg(item.category, 18)}<i class="vpin__rail"></i></div>${liveDot}<div class="vpin__nail"></div><div class="vpin__dot"></div></div>`,
    iconSize: [30, 40],
    iconAnchor: [15, 40],
    popupAnchor: [0, -40],
  });
}

// Highlight ring for the metro station nearest the open event — a pulsing
// target so the eye finds it without competing with the event pin.
export function metroIcon(): L.DivIcon {
  return L.divIcon({
    className: "vmetro-wrap",
    html: '<div class="vmetro"><span class="vmetro__ring"></span><span class="vmetro__core">M</span></div>',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
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
