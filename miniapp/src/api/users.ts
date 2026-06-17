import { API_BASE } from "./http";

function initData(): string | undefined {
  return (window as any)?.Telegram?.WebApp?.initData as string | undefined;
}

// Persist the user's home city from their first map geolocation (replaces the
// old in-bot city picker). Best-effort: never blocks the UI, ignores failures,
// and does nothing outside Telegram (no signed initData to authenticate with).
export async function saveUserLocation(lat: number, lon: number): Promise<void> {
  const init = initData();
  if (!init) return;
  try {
    await fetch(`${API_BASE}/v1/users/location`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, lat, lon }),
      keepalive: true,
    });
  } catch {
    /* saving the city is non-critical */
  }
}

// Favourites are stored per Telegram account so they sync across devices. `add` is this
// device's local favourites to merge in on its first sync (one-time migration from the
// old localStorage-only storage). Returns the account's full id list, or null when we
// can't sync (outside Telegram / network error) so callers keep the local set.
export async function syncFavorites(add: string[] = []): Promise<string[] | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/favorites/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, add }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { ids?: string[] };
    return Array.isArray(j.ids) ? j.ids : null;
  } catch {
    return null;
  }
}

export async function toggleFavoriteRemote(eventId: string, on: boolean): Promise<string[] | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/favorites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, event_id: eventId, on }),
      keepalive: true,
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { ids?: string[] };
    return Array.isArray(j.ids) ? j.ids : null;
  } catch {
    return null;
  }
}
