// Geolocation that asks ONCE and stays granted across opens.
//
// Inside the Telegram WebView, navigator.geolocation re-prompts on every open
// (the WebView doesn't persist the per-origin grant). Telegram's own
// LocationManager (Bot API 8.0+) stores the grant per-bot, so the user grants
// once and is never asked again. We prefer it and fall back to the browser API
// on older clients.

export interface Coords {
  latitude: number;
  longitude: number;
  accuracy?: number | null;
}

interface LocationData {
  latitude: number;
  longitude: number;
  altitude: number | null;
  course: number | null;
  speed: number | null;
  horizontal_accuracy: number | null;
  vertical_accuracy: number | null;
  course_accuracy: number | null;
  speed_accuracy: number | null;
}

interface LocationManager {
  isInited: boolean;
  isLocationAvailable: boolean;
  isAccessRequested: boolean;
  isAccessGranted: boolean;
  init(cb?: () => void): LocationManager;
  getLocation(cb: (data: LocationData | null) => void): LocationManager;
  openSettings(): LocationManager;
}

interface TgWebApp {
  version: string;
  platform: string;
  isVersionAtLeast(v: string): boolean;
  LocationManager?: LocationManager;
}

function tg(): TgWebApp | undefined {
  return (window as any)?.Telegram?.WebApp as TgWebApp | undefined;
}

// True only when the running client actually supports the 8.0 LocationManager.
export function hasTelegramLocation(): boolean {
  const w = tg();
  return !!w && typeof w.isVersionAtLeast === "function" && w.isVersionAtLeast("8.0") && !!w.LocationManager;
}

let initPromise: Promise<LocationManager | null> | null = null;

// init() once; resolves to the manager only if location services are available.
function ensureInited(): Promise<LocationManager | null> {
  if (initPromise) return initPromise;
  const lm = tg()?.LocationManager;
  if (!hasTelegramLocation() || !lm) return (initPromise = Promise.resolve(null));
  initPromise = new Promise((resolve) => {
    const done = () => resolve(lm.isLocationAvailable ? lm : null);
    if (lm.isInited) done();
    else lm.init(done);
  });
  return initPromise;
}

// True if location access is already granted, so the app can start watching on
// open without triggering a permission prompt.
export async function isLocationGranted(): Promise<boolean> {
  const lm = await ensureInited();
  if (lm) return !!lm.isAccessGranted;
  try {
    const status = await (navigator as any).permissions?.query({ name: "geolocation" });
    return status?.state === "granted";
  } catch {
    return false;
  }
}

// Call from a user gesture when access was previously denied. Returns true if it
// could open Telegram's native settings screen.
export function openLocationSettings(): boolean {
  const lm = tg()?.LocationManager;
  if (lm && lm.isAccessRequested && !lm.isAccessGranted) {
    lm.openSettings();
    return true;
  }
  return false;
}

// Live position. Telegram's getLocation is one-shot, so we poll it; the browser
// path uses native watchPosition. Returns a stop() function.
export function watchLocation(
  onUpdate: (c: Coords) => void,
  opts: { intervalMs?: number; onDenied?: () => void } = {},
): () => void {
  const interval = opts.intervalMs ?? 5000;
  let stopped = false;
  let timer: ReturnType<typeof setInterval> | null = null;
  let browserId: number | null = null;

  ensureInited().then((lm) => {
    if (stopped) return;
    if (lm) {
      const tick = () =>
        lm.getLocation((d) => {
          if (stopped) return;
          if (!d) {
            opts.onDenied?.();
            return;
          }
          onUpdate({ latitude: d.latitude, longitude: d.longitude, accuracy: d.horizontal_accuracy });
        });
      tick();
      timer = setInterval(tick, interval);
    } else if (navigator.geolocation) {
      browserId = navigator.geolocation.watchPosition(
        (p) => onUpdate({ latitude: p.coords.latitude, longitude: p.coords.longitude, accuracy: p.coords.accuracy }),
        () => opts.onDenied?.(),
        { enableHighAccuracy: true, maximumAge: 4000, timeout: 15000 },
      );
    }
  });

  return () => {
    stopped = true;
    if (timer) clearInterval(timer);
    if (browserId != null) navigator.geolocation.clearWatch(browserId);
  };
}
