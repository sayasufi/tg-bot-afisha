import L from "leaflet";
import maplibregl from "maplibre-gl";
import { isDesktopNow } from "../../lib/useIsDesktop";
import { useEffect } from "react";
import { useMap } from "react-leaflet";
import "maplibre-gl/dist/maplibre-gl.css";
import "@maplibre/maplibre-gl-leaflet";

import type { ThemeName } from "../../lib/telegram";
import { STYLE_URL, tuneMaplibreStyle } from "./tuneStyle";

// maplibre-gl-leaflet 0.1.x looks up maplibre-gl on the global scope.
(window as any).maplibregl = maplibregl;

// Растровые тайлы для машин БЕЗ аппаратного WebGL: софт-растеризация векторной карты — это
// 14 FPS (замерено; у владельца WARP давал ровно это). Готовые PNG процессор только блитит —
// быстро даже на CPU. Основной источник — НАШ рендерер (apps/tiles): та же векторная карта,
// что у GPU-пользователей, впечатанная в PNG на сервере (кириллица, номера домов, метро,
// парки, палитра). «Как у Яндекса»: слабым клиентам — готовые картинки собственного стиля.
const SELF_TILES: Record<ThemeName, string> = {
  light: "/tiles/light/{z}/{x}/{y}.png",
  dark: "/tiles/dark/{z}/{x}/{y}.png",
};
// Аварийный резерв, если наш рендерер недоступен: Carto. *_nolabels — у Carto подписи
// ГОРОДОВ/районов латиницей («KHIMKI»), поэтому база чистая, а с z14 добавляется слой
// «только подписи»: там уже названия УЛИЦ (у улиц в OSM нет name:en → локальный name =
// кириллица, проверено тайлами z14-16).
const CARTO: Record<ThemeName, string> = {
  light: "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
  dark: "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
};
const CARTO_LABELS: Record<ThemeName, string> = {
  light: "https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}.png",
  dark: "https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png",
};
const CARTO_LABELS_MINZOOM = 14;

// Один раз за сессию: рендерит ли WebGL железо или программный растеризатор (WARP/SwiftShader/
// llvmpipe). Нет контекста вообще → тоже растровый фолбэк. Неизвестный рендерер (скрыт
// приватностью) считаем железом — не даунгрейдим зря.
let _softGL: boolean | null = null;
function isSoftwareGL(): boolean {
  if (_softGL !== null) return _softGL;
  try {
    const canvas = document.createElement("canvas");
    const gl = (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")) as WebGLRenderingContext | null;
    if (!gl) return (_softGL = true);
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) || "") : "";
    _softGL = /swiftshader|llvmpipe|software|basic render|warp/i.test(renderer);
  } catch {
    _softGL = true;
  }
  return _softGL;
}

// Лёгкая подложка для софт-GL: обычный Leaflet-тайллейер (без ретины — меньше пикселей на CPU).
// Наши тайлы; если рендерер отдаёт ошибки и ни один тайл не загрузился — молча пересаживаемся
// на Carto, чтобы карта не осталась пустой.
// Плавность: тайлы догружаются ВО ВРЕМЯ панорамирования (на мобиле Leaflet по умолчанию ждёт
// конца жеста — выглядит как лаг), и вокруг вьюпорта держится запас в 4 ряда, чтобы драг не
// открывал дыры. Во время зум-анимации сетку не трогаем (updateWhenZooming:false).
const SMOOTH_TILES = { updateWhenIdle: false, updateWhenZooming: false, keepBuffer: 4 } as const;
function RasterBasemap({ theme, onReady }: { theme: ThemeName; onReady?: () => void }) {
  const map = useMap();
  useEffect(() => {
    const added: L.TileLayer[] = [];
    let readyFired = false;
    const fire = () => {
      if (!readyFired) {
        readyFired = true;
        onReady?.();
      }
    };
    let loads = 0;
    let errors = 0;
    let swapped = false;
    const addCarto = () => {
      const base = L.tileLayer(CARTO[theme], {
        subdomains: "abcd",
        maxZoom: 19,
        detectRetina: false,
        attribution: "© OpenStreetMap · © CARTO",
        ...SMOOTH_TILES,
      });
      base.addTo(map);
      base.once("load", fire);
      added.push(base);
      const labels = L.tileLayer(CARTO_LABELS[theme], {
        subdomains: "abcd",
        minZoom: CARTO_LABELS_MINZOOM,
        maxZoom: 19,
        detectRetina: false,
        ...SMOOTH_TILES,
      });
      labels.addTo(map);
      added.push(labels);
    };
    const self = L.tileLayer(SELF_TILES[theme], {
      maxZoom: 19,
      // z18-19 — растянутый z17 (номера домов там уже есть): в 16 раз меньше серверных
      // рендеров на сверхблизких зумах, чёткость приемлемая.
      maxNativeZoom: 17,
      detectRetina: false,
      attribution: "© OpenStreetMap",
      ...SMOOTH_TILES,
    });
    self.on("tileload", () => {
      loads++;
    });
    self.on("tileerror", () => {
      errors++;
      // Сервис лежит целиком (ни одного успешного тайла) — аварийный Carto.
      if (!swapped && loads === 0 && errors >= 4) {
        swapped = true;
        map.removeLayer(self);
        addCarto();
      }
    });
    self.addTo(map);
    added.push(self);
    self.once("load", fire);
    const t = window.setTimeout(fire, 4000); // сеть тормозит — апп всё равно оживает
    return () => {
      window.clearTimeout(t);
      for (const l of added) map.removeLayer(l);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, theme]);
  return null;
}

// Only the legally-required data credit (OpenStreetMap / ODbL). The non-required
// "Leaflet" prefix, "OpenFreeMap" and "OpenMapTiles" credits are dropped.
function VectorBasemap({ theme, onReady }: { theme: ThemeName; onReady?: () => void }) {
  const map = useMap();
  useEffect(() => {
    const gl = (L as any).maplibreGL({
      style: STYLE_URL[theme],
      // ПК: кап пиксель-рейшо канваса. На HiDPI и/или ПРОГРАММНОМ WebGL (выключенное аппаратное
      // ускорение — замерено: софт-GL даёт 14 FPS против 100 на GPU) рендер в полном DPR
      // умножает работу растеризатора в 2-4×. 1.5 визуально неотличим на подложке.
      // Мобайл не трогаем (там DPR 3 важен для чёткости лейблов).
      ...(isDesktopNow() ? { pixelRatio: Math.min(window.devicePixelRatio || 1, 1.5) } : {}),
    }).addTo(map);
    const mlMap = gl.getMaplibreMap();
    const tune = () => {
      // Всё оформление стиля (палитра, кириллица, номера домов, метро, парки, дальний
      // «атлас») — в общем tuneStyle.ts: его же выполняет серверный рендерер тайлов.
      tuneMaplibreStyle(mlMap, theme);
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
  // Софт-WebGL (WARP/SwiftShader/нет контекста) → растровые тайлы: плавность важнее тюнинга.
  if (isSoftwareGL()) return <RasterBasemap theme={theme} onReady={onReady} />;
  return <VectorBasemap theme={theme} onReady={onReady} />;
}
