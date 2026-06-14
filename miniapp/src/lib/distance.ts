// Great-circle distance helpers — power the "рядом" proximity labels that make
// the Окрест promise (events around you) tangible.

export type LatLon = [number, number];

export function distanceMeters(a: LatLon, b: LatLon): number {
  const R = 6371000; // Earth radius, metres
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLon = toRad(b[1] - a[1]);
  const lat1 = toRad(a[0]);
  const lat2 = toRad(b[0]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// "480 м" / "1,2 км" — rounded, Russian decimal comma.
export function formatDistance(m: number): string {
  if (m < 950) return `${Math.round(m / 10) * 10} м`;
  return `${(m / 1000).toFixed(m < 9500 ? 1 : 0).replace(".", ",")} км`;
}

// Rough walking time at ~80 m/min.
export function walkMinutes(m: number): number {
  return Math.max(1, Math.round(m / 80));
}

// Short distance label for compact rows ("480 м"), or null if unavailable.
export function distanceLabel(from: LatLon | null | undefined, to: LatLon | null | undefined): string | null {
  if (!from || !to || to[0] == null || to[1] == null) return null;
  return formatDistance(distanceMeters(from, to));
}

// Full proximity label for the event sheet ("480 м · 6 мин пешком"); drops the
// walking time once it stops being a reasonable walk.
export function nearLabel(from: LatLon | null | undefined, to: LatLon | null | undefined): string | null {
  if (!from || !to || to[0] == null || to[1] == null) return null;
  const m = distanceMeters(from, to);
  const dist = formatDistance(m);
  return m <= 2500 ? `${dist} · ${walkMinutes(m)} мин пешком` : dist;
}

// Nearest point (by metres) from a list of {lat, lon, …} to a target.
export function nearestOf<T extends { lat: number; lon: number }>(
  to: LatLon,
  list: T[],
): { item: T; meters: number } | null {
  let best: T | null = null;
  let bestM = Infinity;
  for (const s of list) {
    const m = distanceMeters(to, [s.lat, s.lon]);
    if (m < bestM) {
      bestM = m;
      best = s;
    }
  }
  return best ? { item: best, meters: bestM } : null;
}
