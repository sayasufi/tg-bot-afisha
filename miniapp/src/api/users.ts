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

// Account-scoped app settings (explicit fields). Pass a partial to set those fields;
// omit to just read. Returns the full settings, or null outside Telegram / on error
// (callers then keep their local values).
export type UserSettings = {
  theme?: string | null;
  city?: string | null;
  onboarded?: boolean;
  coach?: boolean;
  swipe_seen?: boolean;
  interests?: string[]; // categories picked at onboarding — warms the "Для тебя" feed
  notify_digest?: boolean; // opt-in to the weekly digest DM (default off)
};

export async function syncSettings(patch?: Partial<UserSettings>): Promise<UserSettings | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, ...(patch ?? {}) }),
      keepalive: true,
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { settings?: UserSettings };
    return j.settings ?? null;
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

// Event reminders (the bot DMs the user ~2h before a saved event). Like favourites, the
// reminder set is account-scoped. Pass nothing to just LIST; pass (eventId, on) to toggle.
// Returns the account's active reminder event-ids, or null outside Telegram / on error.
export async function syncReminders(): Promise<string[] | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/reminders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { ids?: string[] };
    return Array.isArray(j.ids) ? j.ids : null;
  } catch {
    return null;
  }
}

export async function toggleReminderRemote(eventId: string, on: boolean): Promise<string[] | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/reminders`, {
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

// Venue follows ("следить за площадкой") — account-scoped like favourites/reminders. Pass
// nothing to LIST; pass (venueId, on) to toggle. Returns the followed venue-ids, or null.
export async function syncVenueFollows(): Promise<string[] | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/venues`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { ids?: string[] };
    return Array.isArray(j.ids) ? j.ids : null;
  } catch {
    return null;
  }
}

export async function toggleVenueFollowRemote(venueId: string | number, on: boolean): Promise<string[] | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/venues`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, venue_id: Number(venueId), on }),
      keepalive: true,
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { ids?: string[] };
    return Array.isArray(j.ids) ? j.ids : null;
  } catch {
    return null;
  }
}
