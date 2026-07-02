import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { STYLE_URL, tuneMaplibreStyle } from "./features/map/tuneStyle";
import type { ThemeName } from "./lib/telegram";

// Серверный рендер растровых тайлов из НАШЕГО векторного стиля (см. apps/tiles). Страница
// держит один maplibre-инстанс; сервис дёргает window.__renderMeta(z,mx,my) и получает
// МЕТАТАЙЛ — 4 PNG data-URL квадрата 2×2 OSM-тайлов (256 css-px каждый, физически 512 @2x).
// Один рендер → 4 тайла: холодная область прогревается в ~2 раза дешевле на тайл, и подписи
// внутри метатайла согласованы по построению.
//
// Геометрия: вьюпорт 768×768 css = метатайл 512 (2×256) + буфер 128 с каждой стороны. Буфер
// даёт подписям у краёв полноценный контекст коллизий — соседние метатайлы рисуют одну и ту же
// подпись согласованно, швов почти нет.
// Зум: мир при gl-зуме G = 512·2^G css px → тайл OSM-зума z занимает 256 css при G = z-1
// (это же соотношение у Leaflet и maplibre-gl-leaflet на живой карте — размер шрифтов совпадает).
const TILE = 256; // css px итогового тайла
const META = 2; // метатайл META×META OSM-тайлов за один рендер
const BUF = 128; // буфер коллизий вокруг метатайла
const RATIO = 2; // физический DPR канваса — тайлы @2x, чёткие и на ретине, и после даунскейла

const params = new URLSearchParams(location.search);
const theme: ThemeName = params.get("theme") === "dark" ? "dark" : "light";
// /v1/places (метро/парки) — страница живёт на внутреннем origin (miniapp:5173), поэтому
// источникам нужен абсолютный публичный базовый URL; переопределяется ?places=.
const placesBase = params.get("places") || "https://okrestmap.ru";

const el = document.getElementById("map") as HTMLDivElement;
el.style.width = `${TILE * META + BUF * 2}px`;
el.style.height = `${TILE * META + BUF * 2}px`;

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

// Рендер метатайла (mx,my — координаты левого-верхнего тайла, всегда чётные). Возвращает
// массив длиной META², индекс qy*META+qx; за границей мира (нижний край) — null.
(window as any).__renderMeta = async (z: number, mx: number, my: number): Promise<(string | null)[]> => {
  const n = 2 ** z;
  const lon = ((mx + META / 2) / n) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * (my + META / 2)) / n))) * 180) / Math.PI;
  map.jumpTo({ center: [lon, lat], zoom: z - 1 });
  // ВСЕГДА форсируем кадр и ждём честный idle: «быстрые пути» через areTilesLoaded()
  // стреляли ДО перерисовки (тайлы уже в кэше maplibre → пустой снимок фона).
  // idle после triggerRepaint гарантирован даже для no-op jumpTo на тот же вид.
  const idle = new Promise<void>((resolve) => map.once("idle", () => resolve()));
  map.triggerRepaint();
  await idle;
  const src = map.getCanvas();
  const out: (string | null)[] = [];
  for (let qy = 0; qy < META; qy++) {
    for (let qx = 0; qx < META; qx++) {
      if (mx + qx >= n || my + qy >= n) {
        out.push(null);
        continue;
      }
      const c = document.createElement("canvas");
      c.width = TILE * RATIO;
      c.height = TILE * RATIO;
      const ctx = c.getContext("2d")!;
      ctx.drawImage(
        src,
        (BUF + qx * TILE) * RATIO,
        (BUF + qy * TILE) * RATIO,
        TILE * RATIO,
        TILE * RATIO,
        0,
        0,
        TILE * RATIO,
        TILE * RATIO,
      );
      out.push(c.toDataURL("image/png"));
    }
  }
  return out;
};
