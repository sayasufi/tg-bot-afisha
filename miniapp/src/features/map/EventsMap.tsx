import L from "leaflet";
import maplibregl from "maplibre-gl";
import { useEffect, useRef } from "react";
import { AttributionControl, MapContainer, Marker, useMap } from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import "maplibre-gl/dist/maplibre-gl.css";
import "@maplibre/maplibre-gl-leaflet";

import type { EventItem } from "../../api/client";
import { categoryMeta } from "../../lib/categories";

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

// User location marker — a blue dot, plus a fanned "beam" pointing where the
// phone is facing when a compass heading is available.
function userIcon(heading: number | null): L.DivIcon {
  const beam = heading == null ? "" : `<span class="user-loc__beam" style="--h:${heading}deg"></span>`;
  return L.divIcon({
    className: "user-loc-wrap",
    html: `<div class="user-loc">${beam}<span class="user-loc__core"></span></div>`,
    iconSize: [56, 56],
    iconAnchor: [28, 28],
  });
}

// OpenFreeMap "Fiord" — a keyless vector (MapLibre GL) slate-blue style. Crisp
// labels at every zoom; we deepen the palette and green the parks so coloured
// category pins and metro pop. Dark-only (the light theme was removed).
const OFM_FIORD = "https://tiles.openfreemap.org/styles/fiord";
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
          mlMap.setPaintProperty(id, prop, val);
        } catch {
          /* layer id may shift if OFM updates the style */
        }
      };
      repaint("background", "background-color", "#222a3d");
      repaint("water", "fill-color", "#1d3c6b"); // clearer blue lakes/rivers
      repaint("waterway", "line-color", "#3f72ad"); // river lines read as blue
      repaint("park", "fill-color", "#22472f"); // parks → green
      repaint("park_outline", "line-color", "#3c7e54");
      repaint("landcover_wood", "fill-color", "rgba(30,64,43,0.6)"); // forests → green
      const layers = mlMap.getStyle()?.layers || [];
      const font = layers.map((l: any) => l.layout && l.layout["text-font"]).find(Boolean) || ["Noto Sans Regular"];
      for (const layer of layers) {
        if (layer.type !== "symbol" || !layer.layout || layer.layout["text-field"] == null) continue;
        if (layer.id === "ofm-housenumbers" || layer["source-layer"] === "housenumber") continue;
        try {
          mlMap.setLayoutProperty(layer.id, "text-field", cyrillic);
          // Brighter text + denser halo so street/place names read clearly on the dark canvas.
          mlMap.setPaintProperty(layer.id, "text-color", "#eaf0fb");
          mlMap.setPaintProperty(layer.id, "text-halo-color", "#121826");
          mlMap.setPaintProperty(layer.id, "text-halo-width", 1.5);
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
          paint: { "fill-color": "#1e3f2b", "fill-opacity": 0.45 },
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
        paint: { "text-color": "#8fd3a8", "text-halo-color": "#0e1a14", "text-halo-width": 1.6 },
      });

      addLayer({
        id: "ofm-housenumbers",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "housenumber",
        minzoom: 16,
        layout: { "text-field": ["get", "housenumber"], "text-font": font, "text-size": 10, "text-padding": 2 },
        paint: { "text-color": "#9aa6bd", "text-halo-color": "#141a28", "text-halo-width": 1 },
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
        paint: { "text-color": "#767f95", "text-halo-color": "#0f1320", "text-halo-width": 1.1 },
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
          "circle-stroke-color": "#ffffff",
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
        paint: { "text-color": ["get", "color"], "text-halo-color": "#0b0e16", "text-halo-width": 1.9 },
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

function pinIcon(item: EventItem, active: boolean): L.DivIcon {
  const meta = categoryMeta(item.category);
  return L.divIcon({
    className: "pin-wrap",
    html: `<div class="pin${active ? " pin--active" : ""}" style="--c:${meta.color}"><span class="pin__glyph">${meta.glyph}</span></div>`,
    iconSize: [40, 48],
    iconAnchor: [20, 46],
    popupAnchor: [0, -44],
  });
}

function clusterIcon(cluster: any): L.DivIcon {
  const count = cluster.getChildCount();
  const size = count < 10 ? 42 : count < 40 ? 50 : 60;
  return L.divIcon({
    className: "cluster-wrap",
    html: `<div class="cluster" style="--s:${size}px"><span>${count}</span></div>`,
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
  const pins = items.filter((i) => i.lat != null && i.lon != null);

  return (
    <div className="map-wrap">
      <MapContainer center={MOSCOW} zoom={11} minZoom={3} maxZoom={19} zoomControl={false} attributionControl={false} style={{ height: "100%", width: "100%" }}>
        <AttributionControl position="bottomright" prefix={false} />
        <Basemap />
        <MarkerClusterGroup
          chunkedLoading
          showCoverageOnHover={false}
          spiderfyOnMaxZoom
          maxClusterRadius={48}
          iconCreateFunction={clusterIcon}
        >
          {pins.map((item) => (
            <Marker
              key={item.event_id}
              position={[item.lat as number, item.lon as number]}
              icon={pinIcon(item, selected?.event_id === item.event_id)}
              eventHandlers={{ click: () => onSelect(item) }}
            />
          ))}
        </MarkerClusterGroup>
        {userPos && <Marker position={userPos} icon={userIcon(heading)} zIndexOffset={1000} interactive={false} />}
        <MapController selected={selected} locateNonce={locateNonce} userPos={userPos} />
      </MapContainer>
    </div>
  );
}
