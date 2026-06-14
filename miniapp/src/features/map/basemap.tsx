import L from "leaflet";
import maplibregl from "maplibre-gl";
import { useEffect } from "react";
import { useMap } from "react-leaflet";
import "maplibre-gl/dist/maplibre-gl.css";
import "@maplibre/maplibre-gl-leaflet";

// maplibre-gl-leaflet 0.1.x looks up maplibre-gl on the global scope.
(window as any).maplibregl = maplibregl;

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
      // White-cube plaster: pale land, near-black ink labels — with a touch of
      // colour so parks read green and water reads blue (kept muted/pastel).
      repaint("background", "background-color", "#f4f4ef");
      repaint("water", "fill-color", "#cddfeb"); // soft pale blue
      repaint("waterway", "line-color", "#a3c3db"); // rivers read blue
      repaint("park", "fill-color", "#dce9cf"); // parks & gardens → soft sage
      repaint("park_outline", "line-color", "#bfd4a6");
      repaint("landcover_wood", "fill-color", "#d0e1bd"); // forests a touch deeper green
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
          paint: { "fill-color": "#dcebcc", "fill-opacity": 0.7 },
        },
        beforeId,
      );
      // Positron has no park outline; add a faint green one so park edges read crisp.
      addLayer(
        {
          id: "ofm-park-outline",
          type: "line",
          source: "openmaptiles",
          "source-layer": "park",
          minzoom: 11,
          paint: { "line-color": "#b6cf99", "line-width": 0.8, "line-opacity": 0.7 },
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

      // Tap a metro station to spotlight its whole line (dim the rest). Purely
      // map-side; degrades to a no-op when the seed lacks line data.
      let activeLine: string | null = null;
      const lineKey: any = ["coalesce", ["get", "line_id"], ["get", "line"]];
      const applyMetro = (id: string | null) => {
        if (!mlMap.getLayer("metro-dot")) return;
        try {
          if (id == null) {
            mlMap.setPaintProperty("metro-dot", "circle-opacity", 1);
            mlMap.setPaintProperty("metro-dot", "circle-stroke-width", 1.4);
            mlMap.setPaintProperty("metro-label", "text-opacity", 1);
          } else {
            const on: any = ["==", lineKey, id];
            mlMap.setPaintProperty("metro-dot", "circle-opacity", ["case", on, 1, 0.16]);
            mlMap.setPaintProperty("metro-dot", "circle-stroke-width", ["case", on, 2.6, 1.4]);
            mlMap.setPaintProperty("metro-label", "text-opacity", ["case", on, 1, 0.1]);
          }
        } catch {
          /* paint prop unavailable — ignore */
        }
      };
      mlMap.on("click", "metro-dot", (e: any) => {
        const f = e.features && e.features[0];
        const id = f && (f.properties.line_id || f.properties.line);
        if (!id) return;
        activeLine = activeLine === id ? null : id;
        applyMetro(activeLine);
      });
      mlMap.on("click", (e: any) => {
        if (activeLine == null) return;
        const hit = mlMap.queryRenderedFeatures(e.point, { layers: ["metro-dot"] });
        if (!hit.length) {
          activeLine = null;
          applyMetro(null);
        }
      });
      mlMap.on("mouseenter", "metro-dot", () => {
        mlMap.getCanvas().style.cursor = "pointer";
      });
      mlMap.on("mouseleave", "metro-dot", () => {
        mlMap.getCanvas().style.cursor = "";
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

export function Basemap() {
  return <VectorBasemap />;
}
