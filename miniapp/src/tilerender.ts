import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { STYLE_URL, tuneMaplibreStyle } from "./features/map/tuneStyle";
import type { ThemeName } from "./lib/telegram";

// Серверный рендер растровых тайлов из НАШЕГО векторного стиля (см. apps/tiles). Страница
// держит один maplibre-инстанс; сервис дёргает window.__renderTile(z,x,y) и получает PNG
// data-URL ровно одного OSM-тайла (256 css-px, физически 512 — @2x чёткость).
//
// Геометрия: вьюпорт 512×512 css = тайл 256 + буфер 128 с каждой стороны. Буфер даёт
// подписям у краёв тайла полноценный контекст коллизий — соседние тайлы рисуют одну и ту же
// подпись согласованно, швов почти нет. Центральные 256 css вырезаются в PNG.
// Зум: мир при gl-зуме G = 512·2^G css px → тайл OSM-зума z занимает 256 css при G = z-1
// (это же соотношение у Leaflet и maplibre-gl-leaflet на живой карте — размер шрифтов совпадает).
const TILE = 256; // css px итогового тайла
const BUF = 128; // буфер коллизий вокруг тайла
const RATIO = 2; // физический DPR канваса — тайлы @2x, чёткие и на ретине, и после даунскейла

const params = new URLSearchParams(location.search);
const theme: ThemeName = params.get("theme") === "dark" ? "dark" : "light";
// /v1/places (метро/парки) — страница живёт на внутреннем origin (miniapp:5173), поэтому
// источникам нужен абсолютный публичный базовый URL; переопределяется ?places=.
const placesBase = params.get("places") || "https://okrestmap.ru";

const el = document.getElementById("map") as HTMLDivElement;
el.style.width = `${TILE + BUF * 2}px`;
el.style.height = `${TILE + BUF * 2}px`;

const map = new maplibregl.Map({
  container: el,
  style: STYLE_URL[theme],
  interactive: false,
  attributionControl: false,
  fadeDuration: 0, // без анимаций появления подписей — снимок должен быть финальным
  pixelRatio: RATIO,
  preserveDrawingBuffer: true, // иначе drawImage с WebGL-канваса читает пустоту
});

map.on("load", () => {
  tuneMaplibreStyle(map, theme, { placesBase });
  (window as any).__ready = true;
});
map.on("error", (e) => {
  // Ошибки отдельных тайлов/глифов не фатальны — логируем для диагностики через consoleMessage.
  console.warn("[tilerender]", (e as any)?.error?.message || "map error");
});

(window as any).__renderTile = async (z: number, x: number, y: number): Promise<string> => {
  const n = 2 ** z;
  const lon = ((x + 0.5) / n) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + 0.5)) / n))) * 180) / Math.PI;
  map.jumpTo({ center: [lon, lat], zoom: z - 1 });
  // ВСЕГДА форсируем кадр и ждём честный idle: «быстрые пути» через areTilesLoaded()
  // стреляли ДО перерисовки (тайлы уже в кэше maplibre → пустой снимок фона).
  // idle после triggerRepaint гарантирован даже для no-op jumpTo на тот же вид.
  const idle = new Promise<void>((resolve) => map.once("idle", () => resolve()));
  map.triggerRepaint();
  await idle;
  const src = map.getCanvas();
  const out = document.createElement("canvas");
  out.width = TILE * RATIO;
  out.height = TILE * RATIO;
  const ctx = out.getContext("2d")!;
  ctx.drawImage(src, BUF * RATIO, BUF * RATIO, TILE * RATIO, TILE * RATIO, 0, 0, TILE * RATIO, TILE * RATIO);
  return out.toDataURL("image/png");
};
