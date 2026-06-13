import L from "leaflet";
import maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef } from "react";
import { AttributionControl, MapContainer, Marker, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import "maplibre-gl/dist/maplibre-gl.css";
import "@maplibre/maplibre-gl-leaflet";

import type { EventItem } from "../../api/client";
import { categorySvg } from "../../lib/icons";

// maplibre-gl-leaflet 0.1.x looks up maplibre-gl on the global scope.
(window as any).maplibregl = maplibregl;

type Props = {
  items: EventItem[];
  selected: EventItem | null;
  userPos: [number, number] | null;
  heading: number | null;
  locateNonce: number;
  onSelect: (item: EventItem) => void;
};

const MOSCOW: [number, number] = [55.751244, 37.618423];

// User location — a surveyor's crosshair (the map-maker's instrument), with a
// single black needle for the compass heading when available.
function userIcon(heading: number | null): L.DivIcon {
  const needle = heading == null ? "" : `<span class="vyou__needle" style="--h:${heading}deg"></span>`;
  return L.divIcon({
    className: "vyou-wrap",
    html: `<div class="vyou"><span class="vyou__ch"></span><span class="vyou__cv"></span>${needle}<span class="vyou__ring"></span><span class="vyou__core"></span></div>`,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
  });
}

// OpenFreeMap "Positron" — a keyless light vector (MapLibre GL) style: pale
// grey land, white road channels, minimal labels. We push it to a stark
// white-plaster "architectural plan" so the black nameplate pins (and the one
// acid pin) are the only objects on a clean gallery wall.
const OFM_FIORD = "https://tiles.openfreemap.org/styles/positron";
// Only the legally-required data credit (OpenStreetMap / ODbL). The non-required
// "Leaflet" prefix, "OpenFreeMap" and "OpenMapTiles" credits are dropped.
function VectorBasemap() {
  const map = useMap();
  useEffect(() => {
    const gl = (L as any).maplibreGL({ style: OFM_FIORD}).addTo(map);
    const mlMap = gl.getMaplibreMap();
    // Cyrillic-only labels (drop the Latin transliteration the OMT style adds).
    const cyrillic = ["coalesce", ["get", "name:ru"], ["get", "name:nonlatin"], ["get", "name"]];
    const tune = () => {
      const repaint = (id: string, prop: string, val: any) => {
        try {
          if (!mlMap.getLayer(id)) return; // layer absent in this style — skip quietly
          mlMap.setPaintProperty(id, prop, val);
        } catch {
          /* layer id may shift if OFM updates the style */
        }
      };
      // White-cube plaster: pale land, recessive water, near-black ink labels.
      repaint("background", "background-color", "#f4f4ef");
      repaint("water", "fill-color", "#e2e2da");
      repaint("waterway", "line-color", "#c9c9bf");
      repaint("park", "fill-color", "#e9ece0");
      repaint("park_outline", "line-color", "#d6d8c8");
      repaint("landcover_wood", "fill-color", "rgba(220,224,206,0.6)");
      const layers = mlMap.getStyle()?.layers || [];
      const font = layers.map((l: any) => l.layout && l.layout["text-font"]).find(Boolean) || ["Noto Sans Regular"];
      // Roads → white channels on plaster, with a pale grey casing.
      for (const layer of layers) {
        if (layer.type === "line" && (layer["source-layer"] === "transportation" || /road|highway|street|bridge|tunnel/i.test(layer.id))) {
          repaint(layer.id, "line-color", "#ffffff");
        }
        if (layer.type === "fill" && (layer["source-layer"] === "building" || /building/i.test(layer.id))) {
          repaint(layer.id, "fill-color", "#eaeae2");
          repaint(layer.id, "fill-outline-color", "#d8d8ce");
        }
      }
      for (const layer of layers) {
        if (layer.type !== "symbol" || !layer.layout || layer.layout["text-field"] == null) continue;
        if (layer.id === "ofm-housenumbers" || layer["source-layer"] === "housenumber") continue;
        try {
          mlMap.setLayoutProperty(layer.id, "text-field", cyrillic);
          // Near-black "vinyl" labels with a paper halo — gallery wall-text on plaster.
          mlMap.setPaintProperty(layer.id, "text-color", "#0b0b0b");
          mlMap.setPaintProperty(layer.id, "text-halo-color", "#f4f4ef");
          mlMap.setPaintProperty(layer.id, "text-halo-width", 1.4);
        } catch {
          /* skip layers that reject the override */
        }
      }
      // The fiord style omits house numbers and POIs entirely (the data exists in
      // the openmaptiles source), so add the layers ourselves.
      const addLayer = (spec: any, beforeId?: string) => {
        try {
          if (!mlMap.getLayer(spec.id)) mlMap.addLayer(spec, beforeId);
        } catch {
          /* source-layer unavailable — ignore */
        }
      };
      const rank = ["coalesce", ["get", "rank"], 99];

      // Tint city greenery green UNDER roads/labels (fiord leaves it grey).
      const beforeId = (layers.find((l: any) => l["source-layer"] === "transportation") || layers.find((l: any) => l.type === "symbol"))?.id;
      addLayer(
        {
          id: "ofm-grass",
          type: "fill",
          source: "openmaptiles",
          "source-layer": "landcover",
          filter: ["in", ["get", "class"], ["literal", ["grass", "wetland", "scrub"]]],
          paint: { "fill-color": "#e7ead9", "fill-opacity": 0.6 },
        },
        beforeId,
      );
      // Major Moscow parks labelled in green. OSM/OMT doesn't tag big complexes like
      // ВДНХ or the Botanical Garden as named parks, so we use a curated GeoJSON
      // (names + Yandex-geocoded coords) instead of the spotty OMT `park` layer.
      try {
        if (!mlMap.getSource("parks")) {
          mlMap.addSource("parks", { type: "geojson", data: "/v1/places?kind=park&city=Moscow" });
        }
      } catch {
        /* ignore */
      }
      addLayer({
        id: "parks-label",
        type: "symbol",
        source: "parks",
        minzoom: 10,
        // Each park carries a size-based minzoom: big parks appear from far out,
        // tiny squares only once you zoom right in. Bigger parks (lower minzoom)
        // also win label collisions.
        filter: [">=", ["zoom"], ["coalesce", ["get", "minzoom"], 13]],
        layout: {
          "text-field": ["get", "name"],
          "text-font": font,
          "text-size": ["interpolate", ["linear"], ["zoom"], 11, 11, 15, 14],
          "text-max-width": 8,
          "text-padding": 4,
          "symbol-sort-key": ["coalesce", ["get", "minzoom"], 13],
        },
        paint: { "text-color": "#6e6e66", "text-halo-color": "#f4f4ef", "text-halo-width": 1.6 },
      });

      addLayer({
        id: "ofm-housenumbers",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "housenumber",
        minzoom: 16,
        layout: { "text-field": ["get", "housenumber"], "text-font": font, "text-size": 10, "text-padding": 2 },
        paint: { "text-color": "#a8a89e", "text-halo-color": "#f4f4ef", "text-halo-width": 1 },
      });

      // Named POIs (parks, shops, venues…) — deliberately subordinate to streets:
      // smaller, dimmer, fewer (only the more notable ranks), and only when zoomed in.
      addLayer({
        id: "ofm-poi-label",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "poi",
        filter: ["all", ["!=", ["get", "class"], "railway"], ["<=", rank, 20]],
        minzoom: 16,
        layout: {
          "text-field": cyrillic,
          "text-font": font,
          "text-size": 9,
          "text-optional": true,
          "text-padding": 3,
          "text-max-width": 7,
        },
        paint: { "text-color": "#a8a89e", "text-halo-color": "#f4f4ef", "text-halo-width": 1.1 },
      });

      // Metro stations coloured by their official line (ветка) colour — data baked
      // from Wikidata into a static GeoJSON (one dot per station, property `color`).
      try {
        if (!mlMap.getSource("metro")) {
          mlMap.addSource("metro", { type: "geojson", data: "/v1/places?kind=metro&city=Moscow" });
        }
      } catch {
        /* ignore */
      }
      addLayer({
        id: "metro-dot",
        type: "circle",
        source: "metro",
        minzoom: 12,
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 12, 3, 14, 5, 16, 7],
          "circle-color": ["get", "color"],
          "circle-stroke-color": "#f4f4ef",
          "circle-stroke-width": 1.4,
        },
      });
      addLayer({
        id: "metro-label",
        type: "symbol",
        source: "metro",
        minzoom: 13,
        layout: {
          "text-field": ["get", "name"],
          "text-font": font,
          "text-size": 11,
          "text-anchor": "top",
          "text-offset": [0, 0.85],
          "text-optional": true,
        },
        paint: { "text-color": ["get", "color"], "text-halo-color": "#f4f4ef", "text-halo-width": 1.9 },
      });

      // The tile source injects its own "OpenFreeMap …" credit into Leaflet's
      // attribution control; reset it to just the licence-required minimum.
      try {
        const ac = (map as any).attributionControl;
        if (ac) {
          ac._attributions = {};
          ac._update?.();
          // Collapse to a faint "ⓘ" that expands the credit on tap.
          const cont = ac.getContainer ? ac.getContainer() : ac._container;
          if (cont && !cont.dataset.toggleBound) {
            cont.dataset.toggleBound = "1";
            cont.title = "Источники карты";
            cont.addEventListener("click", (e: Event) => {
              e.stopPropagation();
              cont.classList.toggle("attr-open");
            });
          }
        }
      } catch {
        /* attribution control internals changed — leave default */
      }
    };
    if (mlMap.isStyleLoaded()) tune();
    else mlMap.on("load", tune);
    return () => {
      map.removeLayer(gl);
    };
  }, [map]);
  return null;
}

function Basemap() {
  return <VectorBasemap />;
}

// Pin = a gallery nameplate: a white plate with a 1px frame and the category's
// vinyl-cut icon; a nail + dot drops to the geo point. Active flips to acid.
function pinIcon(item: EventItem, active: boolean): L.DivIcon {
  return L.divIcon({
    className: "vpin-wrap",
    html: `<div class="vpin${active ? " vpin--active" : ""}"><div class="vpin__plate">${categorySvg(item.category, 17)}</div><div class="vpin__nail"></div><div class="vpin__dot"></div></div>`,
    iconSize: [30, 40],
    iconAnchor: [15, 40],
    popupAnchor: [0, -40],
  });
}

// Cluster = stacked frames with a mono count; inverts to black past 40.
function clusterIcon(cluster: any): L.DivIcon {
  const count = cluster.getChildCount();
  const size = count < 10 ? 34 : count < 40 ? 40 : 46;
  const big = count >= 40 ? " vcluster--big" : "";
  return L.divIcon({
    className: "vcluster-wrap",
    html: `<div class="vcluster${big}" style="--s:${size}px"><span class="vcluster__face">${count}</span></div>`,
    iconSize: [size, size],
  });
}

function MapController({
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
      map.flyTo([selected.lat, selected.lon], Math.max(map.getZoom(), 16), { duration: 0.7 });
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

export function EventsMap({ items, selected, userPos, heading, locateNonce, onSelect }: Props) {
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
    <div className="map-wrap">
      <MapContainer center={MOSCOW} zoom={11} minZoom={3} maxZoom={19} zoomControl={false} attributionControl={false} style={{ height: "100%", width: "100%" }}>
        <AttributionControl position="bottomright" prefix={false} />
        <Basemap />
        {cluster}
        {userPos && <Marker position={userPos} icon={userIco} zIndexOffset={1000} interactive={false} />}
        <MapController selected={selected} locateNonce={locateNonce} userPos={userPos} />
      </MapContainer>
    </div>
  );
}
