import L from "leaflet";
import maplibregl from "maplibre-gl";
import { useEffect } from "react";
import { useMap } from "react-leaflet";
import "maplibre-gl/dist/maplibre-gl.css";
import "@maplibre/maplibre-gl-leaflet";

import type { ThemeName } from "../../lib/telegram";

// maplibre-gl-leaflet 0.1.x looks up maplibre-gl on the global scope.
(window as any).maplibregl = maplibregl;

const STYLE: Record<ThemeName, string> = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
};

// Per-theme palette: the white-cube by day, warm-ink gallery after dark. Every
// repaint below reads from this object so one switch re-skins the whole map.
type MapPalette = {
  bg: string;
  water: string;
  waterway: string;
  park: string;
  parkOutline: string;
  wood: string;
  road: string;
  building: string;
  buildingOutline: string;
  label: string;
  halo: string;
  grass: string;
  grassOutline: string;
  parksLabel: string;
  housenum: string;
  poi: string;
  hillshade: string; // far-zoom relief shadow colour (mountains)
  border: string; // emphasised Russia national border at far zoom
};

const PALETTE: Record<ThemeName, MapPalette> = {
  light: {
    bg: "#f4f4ef",
    water: "#cddfeb",
    waterway: "#a3c3db",
    park: "#dce9cf",
    parkOutline: "#bfd4a6",
    wood: "#d0e1bd",
    road: "#ffffff",
    building: "#eaeae2",
    buildingOutline: "#d8d8ce",
    label: "#0b0b0b",
    halo: "#f4f4ef",
    grass: "#dcebcc",
    grassOutline: "#b6cf99",
    parksLabel: "#6e6e66",
    housenum: "#a8a89e",
    poi: "#a8a89e",
    hillshade: "#b0a890",
    border: "#4f4a40",
  },
  dark: {
    bg: "#14130e",
    water: "#0e1418",
    waterway: "#243038",
    park: "#172019",
    parkOutline: "#26331f",
    wood: "#19231a",
    road: "#2c2b25",
    building: "#1d1c16",
    buildingOutline: "#2a2820",
    label: "#e9e4d6",
    halo: "#14130e",
    grass: "#18231a",
    grassOutline: "#2c3a2a",
    parksLabel: "#8a8576",
    housenum: "#55534a",
    poi: "#6a675c",
    hillshade: "#060500",
    border: "#c8c2b2",
  },
};

// Only the legally-required data credit (OpenStreetMap / ODbL). The non-required
// "Leaflet" prefix, "OpenFreeMap" and "OpenMapTiles" credits are dropped.
function VectorBasemap({ theme, onReady }: { theme: ThemeName; onReady?: () => void }) {
  const map = useMap();
  useEffect(() => {
    const pal = PALETTE[theme];
    const gl = (L as any).maplibreGL({ style: STYLE[theme] }).addTo(map);
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
      repaint("background", "background-color", pal.bg);
      repaint("water", "fill-color", pal.water);
      repaint("waterway", "line-color", pal.waterway);
      repaint("park", "fill-color", pal.park);
      repaint("park_outline", "line-color", pal.parkOutline);
      repaint("landcover_wood", "fill-color", pal.wood);
      const layers = mlMap.getStyle()?.layers || [];
      const font = layers.map((l: any) => l.layout && l.layout["text-font"]).find(Boolean) || ["Noto Sans Regular"];
      // Roads → bright channels by day, muted grey after dark.
      for (const layer of layers) {
        if (layer.type === "line" && (layer["source-layer"] === "transportation" || /road|highway|street|bridge|tunnel/i.test(layer.id))) {
          repaint(layer.id, "line-color", pal.road);
        }
        if (layer.type === "fill" && (layer["source-layer"] === "building" || /building/i.test(layer.id))) {
          repaint(layer.id, "fill-color", pal.building);
          repaint(layer.id, "fill-outline-color", pal.buildingOutline);
        }
      }
      for (const layer of layers) {
        if (layer.type !== "symbol" || !layer.layout || layer.layout["text-field"] == null) continue;
        if (layer.id === "ofm-housenumbers" || layer["source-layer"] === "housenumber") continue;
        // Drop the basemap's own settlement + country/region NAME labels. At the far-zoom city picker our
        // pins already carry the city name + count (so the tile's "Москва"/"Казань" doubles up under them),
        // and the foreign country/region labels ("Финляндия"/"Турция"/oblasts) just clutter a Russia-only
        // picker and collide with the city labels. Districts (suburb/neighbourhood) stay for street-zoom context.
        if (layer["source-layer"] === "place" && /country|continent|state|province|region|city|town|village|hamlet|capital/i.test(layer.id)) {
          try {
            mlMap.setLayoutProperty(layer.id, "visibility", "none");
          } catch {
            /* layer rejects the override — leave it */
          }
          continue;
        }
        // Road-ref SHIELDS draw a sprite badge (a white box) + the road number as text. Re-pointing
        // their text-field to the cyrillic NAME — which a shield doesn't have (it carries `ref`) —
        // blanks the number and leaves an empty white badge scattered along the roads (the "пустые
        // белые прямоугольники"). The gallery basemap is pure text, so drop the shields entirely.
        if (layer.layout["icon-image"] != null && JSON.stringify(layer.layout["text-field"]).includes('"ref"')) {
          try {
            mlMap.setLayoutProperty(layer.id, "visibility", "none");
          } catch {
            /* layer rejects the override — leave it */
          }
          continue;
        }
        try {
          mlMap.setLayoutProperty(layer.id, "text-field", cyrillic);
          // "Vinyl" labels with a paper halo — gallery wall-text, inverted after dark.
          mlMap.setPaintProperty(layer.id, "text-color", pal.label);
          mlMap.setPaintProperty(layer.id, "text-halo-color", pal.halo);
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
          paint: { "fill-color": pal.grass, "fill-opacity": 0.7 },
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
          paint: { "line-color": pal.grassOutline, "line-width": 0.8, "line-opacity": 0.7 },
        },
        beforeId,
      );
      // --- Far-zoom "atlas" texture: forests, mountain relief and major rivers so the country isn't a blank
      // field at the city-picker zoom. All gated to FAR zoom (the street-level white-cube view stays clean),
      // inserted LOW (under roads + labels). ---
      const waterId =
        layers.find((l: any) => l.id === "water")?.id ||
        layers.find((l: any) => l["source-layer"] === "water" && l.type === "fill")?.id;
      // Mountains — a subtle hillshade from a free terrarium DEM, UNDER water so flat seas aren't shaded.
      // (Urals/Caucasus/Altai pick up quiet relief.) Best-effort: if the DEM tiles fail it just renders blank.
      try {
        if (!mlMap.getSource("dem")) {
          mlMap.addSource("dem", {
            type: "raster-dem",
            tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
            encoding: "terrarium",
            tileSize: 256,
            maxzoom: 12,
            attribution: "Terrain © Mapzen / AWS",
          });
        }
      } catch {
        /* DEM source unavailable — skip relief */
      }
      addLayer(
        {
          id: "ofm-hillshade",
          type: "hillshade",
          source: "dem",
          maxzoom: 8,
          paint: {
            "hillshade-exaggeration": 0.5,
            "hillshade-shadow-color": pal.hillshade,
            "hillshade-highlight-color": pal.halo,
            "hillshade-accent-color": pal.hillshade,
          },
        },
        waterId,
      );
      // Forests — faint green from the LOW-zoom generalised landcover (globallandcover covers z0-8), so the
      // taiga belt / empty north fills in green at the picker. Fades out as the detailed city greenery starts.
      addLayer(
        {
          id: "ofm-forest-far",
          type: "fill",
          source: "openmaptiles",
          "source-layer": "landcover",
          filter: ["in", ["get", "class"], ["literal", ["wood", "forest"]]],
          maxzoom: 10,
          paint: {
            "fill-color": pal.wood,
            "fill-opacity": ["interpolate", ["linear"], ["zoom"], 3, 0.6, 7, 0.42, 10, 0],
          },
        },
        beforeId,
      );
      // Major rivers — thin blue lines where the tiles carry them at far zoom (the biggest rivers are wide
      // water polygons already). Harmless no-op where low-zoom waterways are absent.
      addLayer(
        {
          id: "ofm-rivers-far",
          type: "line",
          source: "openmaptiles",
          "source-layer": "waterway",
          filter: ["==", ["get", "class"], "river"],
          maxzoom: 12,
          paint: {
            "line-color": pal.waterway,
            "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.9, 6, 1.7, 9, 2.4],
            "line-opacity": 0.9,
          },
        },
        beforeId,
      );

      // Crisp COUNTRY outlines at far zoom — draw admin_level-2 borders BOLDER than the basemap's faint
      // hairlines, so the map reads as defined countries (Russia, the big central shape, dominates the
      // picker) instead of a blank field. The tile's adm0_l/adm0_r are empty in this build, so a strict
      // Russia-only filter matched nothing; land borders only (maritime excluded). Far/mid zoom only.
      addLayer(
        {
          id: "ru-border",
          type: "line",
          source: "openmaptiles",
          "source-layer": "boundary",
          filter: [
            "all",
            ["==", ["to-number", ["get", "admin_level"]], 2],
            ["!=", ["get", "maritime"], 1],
            ["!=", ["get", "maritime"], "1"],
          ],
          maxzoom: 9,
          layout: { "line-join": "round", "line-cap": "round" },
          paint: {
            "line-color": pal.border,
            "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1.1, 6, 1.9, 9, 2.6],
            "line-opacity": 0.82,
          },
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
        paint: { "text-color": pal.parksLabel, "text-halo-color": pal.halo, "text-halo-width": 1.6 },
      });

      addLayer({
        id: "ofm-housenumbers",
        type: "symbol",
        source: "openmaptiles",
        "source-layer": "housenumber",
        minzoom: 16,
        layout: { "text-field": ["get", "housenumber"], "text-font": font, "text-size": 10, "text-padding": 2 },
        paint: { "text-color": pal.housenum, "text-halo-color": pal.halo, "text-halo-width": 1 },
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
        paint: { "text-color": pal.poi, "text-halo-color": pal.halo, "text-halo-width": 1.1 },
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
          "circle-stroke-color": pal.halo,
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
        paint: { "text-color": ["get", "color"], "text-halo-color": pal.halo, "text-halo-width": 1.9 },
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
    const ready = () => {
      tune();
      onReady?.();
    };
    if (mlMap.isStyleLoaded()) ready();
    else mlMap.on("load", ready);
    return () => {
      map.removeLayer(gl);
    };
    // Recreate the GL layer when the theme flips — the simplest correct way to
    // re-skin every base layer (tile style + all custom repaints) at once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, theme]);
  return null;
}

export function Basemap({ theme, onReady }: { theme: ThemeName; onReady?: () => void }) {
  return <VectorBasemap theme={theme} onReady={onReady} />;
}
