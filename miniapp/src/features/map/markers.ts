import L from "leaflet";

import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";
import { categorySvg } from "../../lib/icons";

// User location — a clean acid "you" dot with a soft live pulse. When a heading
// is known (phone compass), dot + pointer are drawn as ONE SVG shape so a single
// shared outline wraps the whole marker (no seam between dot and arrow).
export function userIcon(heading: number | null): L.DivIcon {
  const pulse = `<span class="vyou__pulse"></span>`;
  let inner: string;
  if (heading == null) {
    inner = `${pulse}<span class="vyou__dot"></span>`;
  } else {
    // Union of the dot (r=8 @ 23,23) and a slim pointer: apex up, base corners
    // sitting on the circle, then the major arc around the bottom — one closed
    // path, so the outline never cuts across where the two meet.
    const d = "M23 8 L16.45 18.41 A8 8 0 1 0 29.55 18.41 Z";
    inner =
      `${pulse}` +
      `<svg class="vyou__nav" viewBox="0 0 46 46" style="transform:rotate(${heading}deg)" aria-hidden="true">` +
      `<path class="vyou__nav-edge" d="${d}"/>` +
      `<path class="vyou__nav-face" d="${d}"/>` +
      `</svg>`;
  }
  return L.divIcon({
    className: "vyou-wrap",
    html: `<div class="vyou">${inner}</div>`,
    iconSize: [46, 46],
    iconAnchor: [23, 23],
  });
}

// Pin = a gallery nameplate: a white plate with a 1px frame, the category's
// vinyl-cut icon, and a thin category-colour rail along the bottom edge (a
// gallery label's colour code); a soft drop shadow lifts it off the map, and a
// nail + dot drops to the geo point. Active flips to acid AND drops its catalogue
// code on a mono plate below (the focused exhibit's accession number); a live
// event gets a cinnabar pulse; a friend-saved event gets a thin acid ring.
export function pinIcon(item: EventItem, active: boolean, live = false, friend = false): L.DivIcon {
  const cls = `vpin${active ? " vpin--active" : ""}${live ? " vpin--live" : ""}${friend ? " vpin--friend" : ""}`;
  const liveDot = live ? '<span class="vpin__live"></span>' : "";
  const { color } = categoryMeta(item.category);
  // The catalogue code, only on the focused pin (no clutter on the dense map). Rendered ABOVE the plate so
  // the plate still sits exactly where the unselected pin's plate is — the taller active overlay then fully
  // covers the cluster's own (shorter) pin for this event, instead of letting it peek out below.
  const codeText = active && item.code ? String(item.code).replace(/[<>&"]/g, "") : "";
  // Floated ABSOLUTELY above the plate (out of the grid flow), so the active marker keeps the EXACT same
  // box + anchor as the unselected pin — it covers the cluster's own pin for this event perfectly, and the
  // wide code can't grow the grid column and shove the centred plate sideways.
  const code = codeText ? `<div class="vpin__code">${codeText}</div>` : "";
  const plate = `<div class="vpin__plate" style="--cat:${color}">${categorySvg(item.category, 18)}<i class="vpin__rail"></i>${liveDot}</div>`;
  return L.divIcon({
    className: "vpin-wrap",
    html: `<div class="${cls}">${plate}<div class="vpin__nail"></div><div class="vpin__dot"></div>${code}</div>`,
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
