import L from "leaflet";

import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { categorySvg } from "../../lib/icons";

// User location — a surveyor's crosshair (the map-maker's instrument), with a
// User location — a clean acid "you" dot with a soft live pulse and, when a
// heading is known, a flashlight cone fanning out in the facing direction.
export function userIcon(heading: number | null): L.DivIcon {
  const cone = heading == null ? "" : `<span class="vyou__cone" style="--h:${heading}deg"></span>`;
  return L.divIcon({
    className: "vyou-wrap",
    html: `<div class="vyou">${cone}<span class="vyou__pulse"></span><span class="vyou__dot"></span></div>`,
    iconSize: [46, 46],
    iconAnchor: [23, 23],
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
  return countCluster(cluster.getChildCount());
}

// Server-aggregated cluster (low zoom): same gallery-frame face, but the count
// is the backend's event total for that grid cell, not a client child-count.
// Scales the frame across more buckets since these counts run much larger.
export function serverClusterIcon(count: number): L.DivIcon {
  return countCluster(count);
}

function countCluster(count: number): L.DivIcon {
  const size = count < 10 ? 34 : count < 40 ? 40 : count < 150 ? 46 : 54;
  const big = count >= 40 ? " vcluster--big" : "";
  const label = count >= 1000 ? `${Math.round(count / 100) / 10}k` : String(count);
  return L.divIcon({
    className: "vcluster-wrap",
    html: `<div class="vcluster${big}" style="--s:${size}px"><span class="vcluster__face">${label}</span></div>`,
    iconSize: [size, size],
  });
}
