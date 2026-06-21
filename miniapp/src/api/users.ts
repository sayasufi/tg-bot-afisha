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
  notify_reminders?: boolean; // global mute for the per-event reminder DMs (default on)
  notify_digest?: boolean; // opt-in to the weekly digest DM (default off)
  notify_friends?: boolean; // friend DMs + digest friends section (default on)
  friends_private?: boolean; // hide ALL my favourites from friends (default off)
};

// A friend mini-profile — the faces in the «друг сохранил это» social proof + the profile friend list.
export type Friend = { id: number; name: string; username?: string | null; photo_url?: string | null };

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

// Heart / un-heart. Favouriting also arms the event's reminder server-side (if profile notifications
// are on). When done via a «Пойдём?» invite, pass (inviter, sig) so the bot DMs the inviter once.
export type FavoriteResult = { ids: string[] | null; friend: "accepted" | "pending" | "none"; firstFriend: boolean };
export async function toggleFavoriteRemote(
  eventId: string,
  on: boolean,
  inviter?: number | null,
  sig?: string | null,
): Promise<FavoriteResult> {
  const init = initData();
  const miss: FavoriteResult = { ids: null, friend: "none", firstFriend: false };
  if (!init) return miss;
  try {
    const r = await fetch(`${API_BASE}/v1/users/favorites`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, event_id: eventId, on, inviter_id: inviter ?? undefined, sig: sig ?? undefined }),
      keepalive: true,
    });
    if (!r.ok) return miss;
    const j = (await r.json()) as { ids?: string[]; friend?: string; first_friend?: boolean };
    return {
      ids: Array.isArray(j.ids) ? j.ids : null,
      friend: j.friend === "accepted" || j.friend === "pending" ? j.friend : "none",
      firstFriend: !!j.first_friend,
    };
  } catch {
    return miss;
  }
}

// For the given events, which of MY friends saved each (event_id → faces), plus which of these I've
// hidden from friends. The «друг сохранил это» signal in the event sheet. Null outside Telegram / error.
export async function fetchFriendsFavorited(
  eventIds: string[],
): Promise<{ friends: Record<string, Friend[]>; hidden: string[]; hasFriends: boolean } | null> {
  const init = initData();
  if (!init || !eventIds.length) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/friends-favorited`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, event_ids: eventIds }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { friends?: Record<string, Friend[]>; hidden?: string[]; has_friends?: boolean };
    return { friends: j.friends ?? {}, hidden: Array.isArray(j.hidden) ? j.hidden : [], hasFriends: !!j.has_friends };
  } catch {
    return null;
  }
}

// List my friends + incoming requests, or act on one (accept / decline a request, remove / block /
// unblock). Returns {friends, requests, firstFriend} (firstFriend=true when an accept made my first
// friend → one-time disclosure), or null outside Telegram / on error.
export type FriendsState = { friends: Friend[]; requests: Friend[]; firstFriend: boolean };
export async function manageFriends(
  action?: "accept" | "decline" | "remove" | "block" | "unblock",
  friendId?: number,
): Promise<FriendsState | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/friends`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, action, friend_id: friendId }),
      keepalive: true,
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { friends?: Friend[]; requests?: Friend[]; first_friend?: boolean };
    return {
      friends: Array.isArray(j.friends) ? j.friends : [],
      requests: Array.isArray(j.requests) ? j.requests : [],
      firstFriend: !!j.first_friend,
    };
  } catch {
    return null;
  }
}

// A friend's profile — «что он лайкнул»: their visible favourite event_ids (+ identity). Null outside
// Telegram / on error / 403 (not a mutual friend). `private` = they've globally hidden their saves.
export type FriendProfile = {
  id: number;
  name: string;
  username?: string | null;
  photo_url?: string | null;
  private: boolean;
  favorite_ids: string[];
};
export async function fetchFriendProfile(friendId: number): Promise<FriendProfile | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/friend-profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, friend_id: friendId }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as Partial<FriendProfile>;
    return {
      id: j.id ?? friendId,
      name: j.name ?? "",
      username: j.username ?? null,
      photo_url: j.photo_url ?? null,
      private: !!j.private,
      favorite_ids: Array.isArray(j.favorite_ids) ? j.favorite_ids : [],
    };
  } catch {
    return null;
  }
}

// A personal «add me as a friend» deep-link for the current account (durable, reshareable). Null on error.
export async function createFriendLink(): Promise<string | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/friend-link`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { link?: string };
    return typeof j.link === "string" ? j.link : null;
  } catch {
    return null;
  }
}

// Who's behind an «add me» link (name/photo for the accept screen). Null if the sig is invalid / self.
export async function peekFriendLink(inviterId: number, sig: string): Promise<Friend | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/friend-peek`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, inviter_id: inviterId, sig }),
    });
    if (!r.ok) return null;
    const j = (await r.json()) as Partial<Friend>;
    return { id: j.id ?? inviterId, name: j.name ?? "", username: j.username ?? null, photo_url: j.photo_url ?? null };
  } catch {
    return null;
  }
}

// Accept an «add me» link → instant mutual friends. Returns the new friend + whether it's your first.
export async function acceptFriendLink(
  inviterId: number,
  sig: string,
): Promise<{ friend: Friend | null; firstFriend: boolean; added: boolean } | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/friend-accept`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, inviter_id: inviterId, sig }),
      keepalive: true,
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { friend?: Friend | null; first_friend?: boolean; added?: boolean };
    return { friend: j.friend ?? null, firstFriend: !!j.first_friend, added: !!j.added };
  } catch {
    return null;
  }
}

// Hide / unhide one of my favourites from friends (per-item privacy). Returns whether it persisted.
export async function hideFavoriteRemote(eventId: string, hidden: boolean): Promise<boolean> {
  const init = initData();
  if (!init) return false;
  try {
    const r = await fetch(`${API_BASE}/v1/users/favorites/hide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, event_id: eventId, hidden }),
      keepalive: true,
    });
    return r.ok;
  } catch {
    return false;
  }
}

// «Пойдём?» invite opened → attribute the inviter + warm a cold feed from their taste. The sig (set
// by our share endpoint) is re-verified server-side; a forged inviter returns nothing. Returns the
// interests now driving the feed (so the app can apply them this session), or null.
export async function markInvited(eventId: string, inviterId: number, sig: string): Promise<string[] | null> {
  const init = initData();
  if (!init) return null;
  try {
    const r = await fetch(`${API_BASE}/v1/users/invited`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: init, inviter_id: inviterId, event_id: eventId, sig }),
      keepalive: true,
    });
    if (!r.ok) return null;
    const j = (await r.json()) as { interests?: string[] };
    return Array.isArray(j.interests) ? j.interests : null;
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
