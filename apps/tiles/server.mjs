// Тайл-сервер «как у Яндекса» для слабых машин: отдаёт готовые PNG-тайлы НАШЕЙ векторной
// карты. Рендерит headless-chromium'ом страницу miniapp /tilerender.html (тот же maplibre +
// tuneStyle, что видят GPU-клиенты), результат кэшируется на диске НАВСЕГДА (инвалидация —
// очисткой тома; перед сервером ещё nginx proxy_cache). GET /tiles/{light|dark}/{z}/{x}/{y}.png
import { createServer } from "node:http";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { chromium } from "playwright";

const PORT = Number(process.env.PORT || 8787);
const RENDER_BASE = process.env.RENDER_BASE || "http://miniapp:5173";
// Метро/парки (/v1/places) страница просит с публичного домена — из контейнера это упирается
// в CORS/hairpin-NAT. Перехватываем и отвечаем данными из внутренней сети (api:8000).
const API_BASE = process.env.API_BASE || "http://api:8000";
const CACHE_DIR = process.env.CACHE_DIR || "/cache";
const MAX_Z = 19;
// Страниц-рендереров на тему: каждая держит свой maplibre-инстанс. 3 — компромисс
// «скорость холодного прогрева ↔ память chromium» (~150МБ на страницу).
const PAGES_PER_THEME = Number(process.env.PAGES_PER_THEME || 3);
const RENDER_TIMEOUT_MS = 30_000;

const THEMES = new Set(["light", "dark"]);
const TILE_RE = /^\/tiles\/(light|dark)\/(\d{1,2})\/(\d+)\/(\d+)\.png$/;

let browser = null;
async function getBrowser() {
  if (browser && browser.isConnected()) return browser;
  browser = await chromium.launch({
    // SwiftShader: серверу GPU не нужен, 512×512 рендерится за десятки-сотни мс.
    args: ["--disable-dev-shm-usage"],
  });
  browser.on("disconnected", () => {
    browser = null;
    pool.clear(); // страницы умерли вместе с браузером — пересоздадутся лениво
  });
  return browser;
}

// Пул страниц: { theme → [{page, busy}] }; очередь задач FIFO на тему.
const pool = new Map();
const waiters = { light: [], dark: [] };

async function newPage(theme) {
  const b = await getBrowser();
  const page = await b.newPage({ viewport: { width: 512, height: 512 } });
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
    const slot = { page: null, busy: true };
    slots.push(slot);
    try {
      slot.page = await newPage(theme);
    } catch (e) {
      slots.splice(slots.indexOf(slot), 1);
      throw e;
    }
    return slot;
  }
  return new Promise((resolve) => waiters[theme].push(resolve));
}

function releasePage(theme, slot) {
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

// Дедуп одновременных запросов одного тайла (нагрузка приходит квадратами вьюпорта).
const inflight = new Map();

async function renderTile(theme, z, x, y) {
  const key = `${theme}/${z}/${x}/${y}`;
  const running = inflight.get(key);
  if (running) return running;
  const p = (async () => {
    // одна повторная попытка на свежей странице — chromium-страницы иногда умирают
    for (let attempt = 0; ; attempt++) {
      const slot = await acquirePage(theme);
      if (!slot) throw new Error("no page available");
      try {
        const dataUrl = await Promise.race([
          slot.page.evaluate(([zz, xx, yy]) => window.__renderTile(zz, xx, yy), [z, x, y]),
          new Promise((_, rej) => setTimeout(() => rej(new Error("render timeout")), RENDER_TIMEOUT_MS)),
        ]);
        releasePage(theme, slot);
        return Buffer.from(dataUrl.slice("data:image/png;base64,".length), "base64");
      } catch (e) {
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
    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
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
  if (!THEMES.has(theme) || z > MAX_Z || x >= n || y >= n) {
    res.writeHead(400, { "content-type": "text/plain" });
    res.end("bad tile");
    return;
  }
  const file = join(CACHE_DIR, theme, String(z), String(x), `${y}.png`);
  const headers = {
    "content-type": "image/png",
    // Браузеру — неделя; вечная валидность живёт в дисковом кэше и nginx.
    "cache-control": "public, max-age=604800",
  };
  try {
    const cached = await readFile(file);
    res.writeHead(200, headers);
    res.end(cached);
    return;
  } catch {
    /* мимо кэша — рендерим */
  }
  try {
    const t0 = Date.now();
    const png = await renderTile(theme, z, x, y);
    res.writeHead(200, headers);
    res.end(png);
    console.log(`render ${theme}/${z}/${x}/${y} ${Date.now() - t0}ms ${png.length}b`);
    // запись в кэш — после ответа, best-effort (tmp+rename: параллельные писатели не рвут файл)
    try {
      await mkdir(dirname(file), { recursive: true });
      const tmp = `${file}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
      await writeFile(tmp, png);
      await rename(tmp, file);
    } catch (e) {
      console.error("cache write failed:", e.message);
    }
  } catch (e) {
    console.error(`render failed ${theme}/${z}/${x}/${y}:`, e.message);
    res.writeHead(503, { "content-type": "text/plain", "retry-after": "2" });
    res.end("render failed");
  }
});

server.listen(PORT, () => {
  console.log(`tiles on :${PORT} → ${RENDER_BASE}, cache ${CACHE_DIR}`);
  prewarm().catch((e) => console.error("prewarm crashed:", e.message));
});

// --- Фоновый прогрев кэша ---
// PREWARM="minLat,minLon,maxLat,maxLon,zMin,zMax;…" — последовательно, по одному тайлу,
// с паузой: юзерские запросы всегда важнее (плюс LIFO-очередь). Кэш вечный → прогрев
// одноразовый; уже готовые тайлы пропускаются мгновенно (HTTP-путь читает диск).
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
  const boxes = PREWARM.split(";").map((b) => b.split(",").map(Number));
  let done = 0;
  for (const theme of ["light", "dark"]) {
    for (const [minLat, minLon, maxLat, maxLon, zMin, zMax] of boxes) {
      for (let z = zMin; z <= zMax; z++) {
        const [x0, y0] = tileXY(maxLat, minLon, z); // север-запад
        const [x1, y1] = tileXY(minLat, maxLon, z); // юг-восток
        for (let x = x0; x <= x1; x++) {
          for (let y = y0; y <= y1; y++) {
            try {
              await fetch(`http://127.0.0.1:${PORT}/tiles/${theme}/${z}/${x}/${y}.png`);
            } catch {
              /* сервис перегружен/рестартует — прогрев не критичен */
            }
            if (++done % 250 === 0) console.log(`prewarm: ${done} tiles`);
            await new Promise((r) => setTimeout(r, 40)); // юзеры важнее прогрева
          }
        }
      }
    }
  }
  console.log(`prewarm finished: ${done} tiles`);
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
