import { useEffect, useState } from "react";

import { syncFavorites as syncRemote, toggleFavoriteRemote } from "../api/users";

// Favorites sync per Telegram account (server-side). localStorage is kept as an instant
// cache + offline/non-Telegram fallback; the server is the source of truth once synced.
const KEY = "afisha_favorites";
// Set once per device after we've merged this device's local favourites into the
// account — so we migrate old per-device hearts up exactly once, then become pull-only.
const MERGED_KEY = "afisha_favorites_merged";

function read(): Set<string> {
  try {
    const raw = localStorage.getItem(KEY);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

let favs = read();
const subscribers = new Set<() => void>();

function emit() {
  for (const fn of subscribers) fn();
}

function setLocal(next: Set<string>): void {
  favs = next;
  try {
    localStorage.setItem(KEY, JSON.stringify([...next]));
  } catch {
    /* cache write is best-effort */
  }
  emit();
}

export function toggleFavorite(id: string): void {
  const next = new Set(favs);
  const on = !next.has(id);
  if (on) next.add(id);
  else next.delete(id);
  setLocal(next); // optimistic — the UI flips instantly
  // Persist to the account (best-effort); adopt the server's authoritative list back.
  toggleFavoriteRemote(id, on)
    .then((ids) => {
      if (ids) setLocal(new Set(ids));
    })
    .catch(() => {
      /* the local toggle already stands; next sync reconciles */
    });
}

let syncing = false;

// Pull the account's favourites (merging this device's local ones on its first run).
// Called once on app start. No-op / keeps local set when outside Telegram or offline.
export async function syncFavorites(): Promise<void> {
  if (syncing) return;
  syncing = true;
  try {
    let merged = false;
    try {
      merged = localStorage.getItem(MERGED_KEY) === "1";
    } catch {
      /* ignore */
    }
    const ids = await syncRemote(merged ? [] : [...favs]);
    if (ids) {
      setLocal(new Set(ids));
      try {
        localStorage.setItem(MERGED_KEY, "1");
      } catch {
        /* ignore */
      }
    }
  } finally {
    syncing = false;
  }
}

// Reactive hook: re-renders subscribers whenever favorites change. `ids` is a
// fresh copy so callers can't mutate the store directly (only toggle() can).
export function useFavorites() {
  const [, force] = useState(0);
  useEffect(() => {
    const fn = () => force((x) => x + 1);
    subscribers.add(fn);
    return () => {
      subscribers.delete(fn);
    };
  }, []);
  return {
    ids: new Set(favs),
    has: (id: string) => favs.has(id),
    toggle: toggleFavorite,
  };
}
