// Тайл-сервер «как у Яндекса» для слабых машин: отдаёт готовые PNG-тайлы НАШЕЙ векторной
// карты. Рендерит headless-chromium'ом страницу miniapp /tilerender.html (тот же maplibre +
// tuneStyle, что видят GPU-клиенты) МЕТАТАЙЛАМИ 2×2 — один рендер даёт 4 соседних тайла.
// Кэш: диск НАВСЕГДА (инвалидация — очисткой тома) + nginx proxy_cache сверху.
// GET /tiles/{light|dark}/{z}/{x}/{y}.png · GET /healthz
//
// Прод-заметки (тысячи юзеров): закэшированные тайлы раздаёт nginx БЕЗ этого сервиса —
// рендерер греет только холодные области. Защита: LIFO-очередь (на экране юзера — вперёд),
// кап очереди (503 + Retry-After при лавине), рецикл страниц от утечек chromium,
// z ≤ 17 (клиент выше и не просит: maxNativeZoom 17).
import { createServer } from "node:http";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { chromium } from "playwright";

const PORT = Number(process.env.PORT || 8787);
const RENDER_BASE = process.env.RENDER_BASE || "http://miniapp:5173";
// Метро/парки (/v1/places) страница просит с публичного домена — из контейнера это упирается
// в CORS/hairpin-NAT. Перехватываем и отвечаем данными из внутренней сети (api:8000).
const API_BASE = process.env.API_BASE || "http://api:8000";
const CACHE_DIR = process.env.CACHE_DIR || "/cache";
const META = 2; // синхронно с tilerender.ts
const MIN_Z = 1; // glZoom = z-1 ≥ 0
const MAX_Z = 17; // клиент дальше растягивает z17 (maxNativeZoom)
// Страниц-рендереров на тему: каждая держит свой maplibre-инстанс (~200-300МБ chromium).
const PAGES_PER_THEME = Number(process.env.PAGES_PER_THEME || 4);
const RENDER_TIMEOUT_MS = 30_000;
const QUEUE_CAP = 600; // дальше — 503: лучше быстрый отказ, чем минуты ожидания
const PAGE_RECYCLE_RENDERS = 400; // профилактика утечек длинных страниц

const THEMES = new Set(["light", "dark"]);
const TILE_RE = /^\/tiles\/(light|dark)\/(\d{1,2})\/(\d+)\/(\d+)\.png$/;

let browser = null;
async function getBrowser() {
  if (browser && browser.isConnected()) return browser;
  browser = await chromium.launch({
    args: [
      "--disable-dev-shm-usage",
      // ANGLE→EGL: вместо дефолтного SwiftShader берётся системный Mesa **llvmpipe** —
      // многопоточный растеризатор на всех ядрах: метатайл 4000мс → 100-350мс (замерено).
      // (NVIDIA L40S хоста занята соседним voice-api — не подселяемся; если EGL-стек
      // недоступен, chromium сам молча падает обратно на SwiftShader.)
      "--use-angle=gl-egl",
      "--ignore-gpu-blocklist",
      "--enable-gpu",
    ],
  });
  browser.on("disconnected", () => {
    browser = null;
    pool.clear(); // страницы умерли вместе с браузером — пересоздадутся лениво
  });
  return browser;
}
// Диагностика: чем реально рендерим (NVIDIA vs SwiftShader) — один раз в лог.
let rendererLogged = false;
async function logRenderer(page) {
  if (rendererLogged) return;
  rendererLogged = true;
  try {
    const r = await page.evaluate(() => {
      const gl = document.createElement("canvas").getContext("webgl");
      const ext = gl && gl.getExtension("WEBGL_debug_renderer_info");
      return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "unknown";
    });
    console.log(`webgl renderer: ${r}`);
  } catch {
    /* не критично */
  }
}

// Пул страниц: { theme → [{page, busy, renders}] }; LIFO-стек ожидающих на тему.
const pool = new Map();
const waiters = { light: [], dark: [] };

async function newPage(theme) {
  const b = await getBrowser();
  const page = await b.newPage({ viewport: { width: 768, height: 768 } });
  page.on("console", (m) => {
    if (m.type() === "warning" || m.type() === "error") console.log(`[page:${theme}]`, m.text());
  });
  await page.route("**/v1/places*", async (route) => {
    try {
      const u = new URL(route.request().url());
      const r = await fetch(`${API_BASE}${u.pathname}${u.search}`);
      const body = Buffer.from(await r.arrayBuffer());
      await route.fulfill({ status: r.status, contentType: r.headers.get("content-type") || "application/json", body });
    } catch {
      await route.abort();
    }
  });
  await page.goto(`${RENDER_BASE}/tilerender.html?theme=${theme}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
  await page.waitForFunction("window.__ready === true", null, { timeout: 60_000 });
  await logRenderer(page);
  return page;
}

async function acquirePage(theme) {
  let slots = pool.get(theme);
  if (!slots) {
    slots = [];
    pool.set(theme, slots);
  }
  const free = slots.find((s) => !s.busy);
  if (free) {
    free.busy = true;
    return free;
  }
  if (slots.length < PAGES_PER_THEME) {
    const slot = { page: null, busy: true, renders: 0 };
    slots.push(slot);
    try {
      slot.page = await newPage(theme);
    } catch (e) {
      slots.splice(slots.indexOf(slot), 1);
      throw e;
    }
    return slot;
  }
  if (waiters[theme].length >= QUEUE_CAP) throw Object.assign(new Error("queue full"), { code: 503 });
  return new Promise((resolve) => waiters[theme].push(resolve));
}

function releasePage(theme, slot) {
  slot.renders++;
  if (slot.renders >= PAGE_RECYCLE_RENDERS) {
    // профилактический рецикл: выбрасываем страницу, ждущий получит свежую
    dropPage(theme, slot);
    return;
  }
  // LIFO: при лавине запросов (каскад зумов у юзера) свежезапрошенные тайлы — те, что
  // сейчас на экране — обгоняют устаревшие промежуточные.
  const next = waiters[theme].pop();
  if (next) next(slot); // передаём занятый слот следующему
  else slot.busy = false;
}

async function dropPage(theme, slot) {
  const slots = pool.get(theme) || [];
  const i = slots.indexOf(slot);
  if (i >= 0) slots.splice(i, 1);
  try {
    await slot.page?.close();
  } catch {
    /* уже мёртв */
  }
  const next = waiters[theme].pop();
  if (next) {
    // очередь ждёт слот — создаём свежий взамен выброшенного
    acquirePage(theme).then(next, () => next(null));
  }
}

const tilePath = (theme, z, x, y) => join(CACHE_DIR, theme, String(z), String(x), `${y}.png`);

async function writeTile(file, buf) {
  await mkdir(dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
  await writeFile(tmp, buf);
  await rename(tmp, file); // параллельные писатели не рвут файл
}

// Дедуп одновременных рендеров одного МЕТАтайла (4 запроса соседей → один рендер).
const inflight = new Map();

async function renderMeta(theme, z, mx, my) {
  const key = `${theme}/${z}/${mx}/${my}`;
  const running = inflight.get(key);
  if (running) return running;
  const p = (async () => {
    // одна повторная попытка на свежей странице — chromium-страницы иногда умирают
    for (let attempt = 0; ; attempt++) {
      const slot = await acquirePage(theme);
      if (!slot) throw new Error("no page available");
      try {
        const dataUrls = await Promise.race([
          slot.page.evaluate(([zz, xx, yy]) => window.__renderMeta(zz, xx, yy), [z, mx, my]),
          new Promise((_, rej) => setTimeout(() => rej(new Error("render timeout")), RENDER_TIMEOUT_MS)),
        ]);
        releasePage(theme, slot);
        const tiles = new Map(); // "x/y" → Buffer
        for (let qy = 0; qy < META; qy++) {
          for (let qx = 0; qx < META; qx++) {
            const d = dataUrls[qy * META + qx];
            if (d) tiles.set(`${mx + qx}/${my + qy}`, Buffer.from(d.slice("data:image/png;base64,".length), "base64"));
          }
        }
        // кэшируем все квадранты сразу — соседние запросы юзера попадут в диск
        await Promise.all([...tiles].map(([k, buf]) => writeTile(tilePath(theme, z, ...k.split("/")), buf).catch((e) => console.error("cache write failed:", e.message))));
        return tiles;
      } catch (e) {
        if (e.code === 503) throw e;
        await dropPage(theme, slot);
        if (attempt >= 1) throw e;
      }
    }
  })();
  inflight.set(key, p);
  try {
    return await p;
  } finally {
    inflight.delete(key);
  }
}

const server = createServer(async (req, res) => {
  if (req.url === "/healthz") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(
      JSON.stringify({
        ok: true,
        queue: { light: waiters.light.length, dark: waiters.dark.length },
        pages: { light: (pool.get("light") || []).length, dark: (pool.get("dark") || []).length },
      }),
    );
    return;
  }
  const m = TILE_RE.exec(req.url || "");
  if (!m) {
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("not found");
    return;
  }
  const [, theme, zs, xs, ys] = m;
  const z = Number(zs);
  const x = Number(xs);
  const y = Number(ys);
  const n = 2 ** z;
  if (!THEMES.has(theme) || z < MIN_Z || z > MAX_Z || x >= n || y >= n) {
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("bad tile");
    return;
  }
  const headers = {
    "content-type": "image/png",
    // Браузеру — неделя; вечная валидность живёт в дисковом кэше и nginx.
    "cache-control": "public, max-age=604800",
  };
  try {
    const cached = await readFile(tilePath(theme, z, x, y));
    res.writeHead(200, headers);
    res.end(cached);
    return;
  } catch {
    /* мимо кэша — рендерим */
  }
  try {
    const t0 = Date.now();
    const mx = x - (x % META);
    const my = y - (y % META);
    const tiles = await renderMeta(theme, z, mx, my);
    const png = tiles.get(`${x}/${y}`);
    if (!png) throw new Error("quadrant missing");
    res.writeHead(200, headers);
    res.end(png);
    console.log(`render ${theme}/${z}/${mx}/${my} (+${tiles.size - 1} sib) ${Date.now() - t0}ms`);
  } catch (e) {
    console.error(`render failed ${theme}/${z}/${x}/${y}:`, e.message);
    res.writeHead(503, { "content-type": "text/plain", "retry-after": "2" });
    res.end("render failed");
  }
});

server.listen(PORT, () => {
  console.log(`tiles on :${PORT} → ${RENDER_BASE}, cache ${CACHE_DIR}, ${PAGES_PER_THEME} pages/theme, meta ${META}×${META}`);
  prewarm().catch((e) => console.error("prewarm crashed:", e.message));
});

// --- Фоновый прогрев кэша ---
// PREWARM=all → cities.json (16 городов: весь город z10-14, центр z15-16, ядро z17 у Москвы).
// Последовательно, по одному тайлу; пауза только после РЕАЛЬНОГО рендера (кэш-хиты скипаются
// на полной скорости — рестарт сервиса не повторяет работу). Юзеры важнее: LIFO ставит их
// запросы вперёд, а прогрев ждёт в хвосте.
const PREWARM = process.env.PREWARM || "";
const deg2rad = (d) => (d * Math.PI) / 180;
function tileXY(lat, lon, z) {
  const n = 2 ** z;
  const x = Math.floor(((lon + 180) / 360) * n);
  const y = Math.floor(((1 - Math.log(Math.tan(deg2rad(lat)) + 1 / Math.cos(deg2rad(lat))) / Math.PI) / 2) * n);
  return [Math.min(Math.max(x, 0), n - 1), Math.min(Math.max(y, 0), n - 1)];
}
async function prewarm() {
  if (!PREWARM) return;
  let cities;
  try {
    cities = JSON.parse(readFileSync(new URL("./cities.json", import.meta.url), "utf8"));
  } catch (e) {
    console.error("prewarm: cities.json unreadable:", e.message);
    return;
  }
  let done = 0;
  let rendered = 0;
  const t0 = Date.now();
  for (const theme of ["light", "dark"]) {
    for (const city of cities) {
      for (const area of city.areas) {
        const [minLat, minLon, maxLat, maxLon] = area.box;
        const [zMin, zMax] = area.z;
        for (let z = zMin; z <= Math.min(zMax, MAX_Z); z++) {
          const [x0, y0] = tileXY(maxLat, minLon, z); // север-запад
          const [x1, y1] = tileXY(minLat, maxLon, z); // юг-восток
          for (let x = x0; x <= x1; x++) {
            for (let y = y0; y <= y1; y++) {
              const t = Date.now();
              try {
                await fetch(`http://127.0.0.1:${PORT}/tiles/${theme}/${z}/${x}/${y}.png`);
              } catch {
                /* сервис перегружен/рестартует — прогрев не критичен */
              }
              done++;
              if (Date.now() - t > 60) {
                rendered++;
                await new Promise((r) => setTimeout(r, 40)); // юзеры важнее прогрева
              }
              if (done % 1000 === 0) console.log(`prewarm: ${done} checked, ${rendered} rendered, ${Math.round((Date.now() - t0) / 1000)}s`);
            }
          }
        }
      }
    }
  }
  console.log(`prewarm finished: ${done} tiles (${rendered} rendered) in ${Math.round((Date.now() - t0) / 1000)}s`);
}

// Мягкое завершение — docker stop не должен ждать таймаута.
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, async () => {
    try {
      await browser?.close();
    } finally {
      process.exit(0);
    }
  });
}
